"""
Diagnose why parcels remain undelivered after simulation.

For each undelivered parcel classifies the cause:
  A) at_origin    — never picked up; explains WHY no volunteer took it
  B) in_transit   — moved ≥1 hop but stranded; explains WHY no one continued

Usage
-----
  uv run python diagnose_stuck.py                         # instance 0, uniform, p=1.0
  uv run python diagnose_stuck.py --instance 2 --mode negative --fraction 0.1
"""

from __future__ import annotations
import argparse
import random
from collections import defaultdict
from pathlib import Path

from simulator.loader import (
    load_graph, load_od_matrices, load_parcels, load_stations,
    load_timetable, build_timetable_index,
)
from simulator.model import Parcel, Volunteer
from simulator.network import Network
from simulator.scheduler import Simulator
from simulator.volunteers import generate_volunteers

DATA_DIR      = Path(__file__).parent / "data"
INSTANCES_DIR = DATA_DIR / "instances"
PARCEL_MODES  = ("uniform", "positive", "negative")
N_DAYS        = 7


def _seed(instance: int, mode: str) -> int:
    return 1000 * (instance + 1) + 100 * PARCEL_MODES.index(mode)


# ---------------------------------------------------------------------------
# Instrumented simulator: records every valid-station visit
# ---------------------------------------------------------------------------

class DiagSimulator(Simulator):
    """Records, for each station, all volunteer visits (time, valid_remaining, carrying).
    Also records the first time each parcel was deposited at each station."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # station → list of (time, volunteer_id, valid_remaining, carrying_pid, picked_pid)
        # picked_pid: the parcel actually picked up at this visit (None if none)
        self.visits: dict[str, list[tuple]] = defaultdict(list)
        # (parcel_id, station) → time the parcel first arrived at that station
        self.parcel_arrival: dict[tuple[str, str], int] = {}

    def _on_volunteer_at(self, event):
        volunteer: Volunteer
        station_idx: int
        volunteer, station_idx = event.payload
        current_station = volunteer.route[station_idx]

        if current_station in volunteer.valid_stations:
            remaining = volunteer.route[station_idx + 1:]
            valid_remaining = [s for s in remaining if s in volunteer.valid_stations]
            carrying_before = volunteer.carrying
            super()._on_volunteer_at(event)
            # Detect an actual pick-up: volunteer was empty, now holds a parcel
            picked = (
                volunteer.carrying
                if carrying_before is None and volunteer.carrying is not None
                else None
            )
            self.visits[current_station].append((
                event.time,
                volunteer.volunteer_id,
                list(valid_remaining),
                carrying_before,
                picked,
            ))
        else:
            super()._on_volunteer_at(event)

        # Record when a parcel was deposited at a station (first occurrence only)
        for pid, locker in [
            (p.parcel_id, p.current_locker)
            for p in self._parcels.values()
            if not p.delivered
        ]:
            key = (pid, locker)
            if key not in self.parcel_arrival:
                self.parcel_arrival[key] = event.time


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_time(minutes: int) -> str:
    day   = minutes // 1440
    hhmm  = minutes %  1440
    h, m  = divmod(hhmm, 60)
    if day:
        return f"Day{day} {h:02d}:{m:02d}"
    return f"{h:02d}:{m:02d}"


def _summarise_visits(
    visits: list[tuple],
    parcel: Parcel,
    network: Network,
    *,
    max_print: int = 6,
) -> list[str]:
    """Explain why each volunteer visit at the stuck station did NOT pick up the parcel."""
    dest = parcel.destination
    stuck = parcel.current_locker
    hops_stuck = network.hop_distance(stuck, dest)
    release_min = parcel.release_time

    reasons: dict[str, int] = defaultdict(int)  # reason → count
    total = 0

    for (t, vid, valid_rem, carrying, picked) in visits:
        if t < release_min:
            reasons["before_release"] += 1
            total += 1
            continue
        if carrying is not None:
            reasons["already_carrying"] += 1
            total += 1
            continue
        best_ahead = min(
            (network.hop_distance(s, dest) for s in valid_rem),
            default=hops_stuck + 1,
        )
        if best_ahead >= hops_stuck:
            if not valid_rem:
                reasons["no_valid_ahead"] += 1
            else:
                reasons["no_improvement_ahead"] += 1
        else:
            # This parcel qualified for pick-up; check what actually happened.
            if picked is not None and picked != parcel.parcel_id:
                # Scheduler correctly chose a competing parcel with a better score.
                reasons["other_parcel_picked_instead"] += 1
            else:
                # No parcel was picked despite this one qualifying — real bug.
                reasons["should_have_picked_up"] += 1
        total += 1

    lines = [f"    {total} volunteer visit(s) at {stuck}:"]
    for reason, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
        label = {
            "before_release":        "arrived before parcel released",
            "already_carrying":      "already carrying another parcel",
            "no_valid_ahead":        "no valid stations ahead (route ends here)",
            "no_improvement_ahead":  "no valid station ahead improves hop distance",
            "other_parcel_picked_instead": "competing parcel in locker had better score",
            "should_have_picked_up": "*** BUG: qualified but no parcel was picked up ***",
        }.get(reason, reason)
        lines.append(f"      {cnt:4d} × {label}")
    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance",  type=int,   default=0)
    parser.add_argument("--mode",      default="uniform",
                        choices=list(PARCEL_MODES))
    parser.add_argument("--fraction",  type=float, default=1.0)
    parser.add_argument("--leg-time",  type=int,   default=3)
    parser.add_argument("--max-parcels", type=int, default=50,
                        help="Print at most this many stuck-parcel details")
    args = parser.parse_args()

    instance_dir = INSTANCES_DIR / f"instance_{args.instance:02d}"

    graph_edges  = load_graph(DATA_DIR / "graph.csv")
    network      = Network(graph_edges)
    stations     = load_stations(DATA_DIR / "stations.csv")

    timetable_path = DATA_DIR / "timetable.csv"
    timetable = (
        build_timetable_index(load_timetable(timetable_path), n_days=N_DAYS)
        if timetable_path.exists() else {}
    )

    od_entries = load_od_matrices(instance_dir / "od_matrix.csv")
    parcels    = load_parcels(instance_dir / f"parcels_{args.mode}.csv")

    seed = _seed(args.instance, args.mode)
    rng  = random.Random(seed)

    volunteers = generate_volunteers(
        od_entries, network, args.fraction, rng, timetable, n_days=N_DAYS,
    )
    print(f"Instance {args.instance:02d}  mode={args.mode}  p={args.fraction:.1f}")
    print(f"Parcels: {len(parcels)}   Volunteers: {len(volunteers)}\n")

    sim = DiagSimulator(
        parcels, volunteers, network, leg_time=args.leg_time, timetable=timetable,
    )
    sim.run()

    # Split undelivered into two buckets
    at_origin   = [p for p in parcels if not p.delivered and p.current_locker == p.origin]
    in_transit  = [p for p in parcels if not p.delivered and p.current_locker != p.origin]
    n_delivered = sum(1 for p in parcels if p.delivered)

    print(f"Delivered : {n_delivered}/{len(parcels)}  "
          f"({100*n_delivered/len(parcels):.1f}%)")
    print(f"At-origin : {len(at_origin)}")
    print(f"In-transit: {len(in_transit)}\n")

    def _station_name(sid: str) -> str:
        s = stations.get(sid)
        return s.name if s else sid

    # ------------------------------------------------------------------
    # Category A: at-origin
    # ------------------------------------------------------------------
    if at_origin:
        print("=" * 70)
        print(f"CATEGORY A — {len(at_origin)} parcel(s) NEVER PICKED UP (stuck at origin)")
        print("=" * 70)
        for p in at_origin[:args.max_parcels]:
            hops = network.hop_distance(p.origin, p.destination)
            print(f"\n  {p.parcel_id}: {_station_name(p.origin)} → {_station_name(p.destination)}"
                  f"  ({hops} hop{'s' if hops != 1 else ''})"
                  f"  released {_fmt_time(p.release_time)}")
            visits = sim.visits.get(p.origin, [])
            lines  = _summarise_visits(visits, p, network)
            print("\n".join(lines))
        if len(at_origin) > args.max_parcels:
            print(f"\n  ... and {len(at_origin) - args.max_parcels} more (use --max-parcels to see all)")

    # ------------------------------------------------------------------
    # Category B: in-transit
    # ------------------------------------------------------------------
    if in_transit:
        print()
        print("=" * 70)
        print(f"CATEGORY B — {len(in_transit)} parcel(s) STRANDED mid-route")
        print("=" * 70)

        # Group by stranded station to see if there's a pattern
        by_station: dict[str, list[Parcel]] = defaultdict(list)
        for p in in_transit:
            by_station[p.current_locker].append(p)

        print(f"\nStranded stations ({len(by_station)} distinct):")
        for st, ps in sorted(by_station.items(), key=lambda x: -len(x[1])):
            print(f"  {_station_name(st):30s}  ({len(ps)} parcel(s))")

        print()
        shown = 0
        for p in in_transit[:args.max_parcels]:
            shown += 1
            hops_here = network.hop_distance(p.current_locker, p.destination)
            hops_orig = network.hop_distance(p.origin, p.destination)
            print(f"\n  {p.parcel_id}: {_station_name(p.origin)} → {_station_name(p.destination)}"
                  f"  (orig {hops_orig} hops)"
                  f"  released {_fmt_time(p.release_time)}")
            print(f"    Stranded at: {_station_name(p.current_locker)}"
                  f"  ({hops_here} hop{'s' if hops_here != 1 else ''} to dest)")
            visits = sim.visits.get(p.current_locker, [])
            # Filter by when the parcel actually arrived at the stuck station,
            # not just its release time (it may have been in transit for a while).
            arrived_at = sim.parcel_arrival.get(
                (p.parcel_id, p.current_locker), p.release_time
            )
            later_visits = [(t, vid, vr, c, pk) for (t, vid, vr, c, pk) in visits if t >= arrived_at]
            lines = _summarise_visits(later_visits, p, network)
            print("\n".join(lines))
        if len(in_transit) > args.max_parcels:
            print(f"\n  ... and {len(in_transit) - args.max_parcels} more")

    # ------------------------------------------------------------------
    # Summary of root causes across all undelivered
    # ------------------------------------------------------------------
    print()
    print("=" * 70)
    print("ROOT-CAUSE TALLY (all undelivered parcels)")
    print("=" * 70)
    cause_counts: dict[str, int] = defaultdict(int)

    def _dominant_cause(p: Parcel) -> str:
        stuck   = p.current_locker
        hops_stuck = network.hop_distance(stuck, p.destination)
        visits  = sim.visits.get(stuck, [])
        arrived_at = sim.parcel_arrival.get((p.parcel_id, stuck), p.release_time)
        later   = [(t, vid, vr, c, pk) for (t, vid, vr, c, pk) in visits if t >= arrived_at]

        if not later:
            if not visits:
                return "no_volunteer_ever_at_station"
            return "all_volunteers_passed_before_release"

        before  = sum(1 for (t,*_) in visits if t < p.release_time)
        carrying = sum(1 for (_,_,_,c,_pk) in later if c is not None)
        no_ahead = sum(1 for (_,_,vr,c,_pk) in later if c is None and not vr)
        no_improv = sum(1 for (_,_,vr,c,_pk) in later
                        if c is None and vr and
                        min(network.hop_distance(s, p.destination) for s in vr) >= hops_stuck)

        other_picked = sum(1 for (_,_,vr,c,pk) in later
                           if c is None and pk is not None and pk != p.parcel_id and
                           min((network.hop_distance(s, p.destination) for s in vr), default=hops_stuck+1) < hops_stuck)

        # dominant reason among post-release visits
        if no_ahead + no_improv + other_picked == len(later) - carrying:
            if other_picked > no_ahead and other_picked > no_improv:
                return "competing_parcel_always_wins"
            if no_ahead > no_improv:
                return "route_ends_at_stuck_station"
            return "no_volunteer_route_improves_hops"
        if carrying == len(later):
            return "all_post_release_volunteers_carrying"
        return "mixed"

    for p in at_origin + in_transit:
        cause_counts[_dominant_cause(p)] += 1

    for cause, cnt in sorted(cause_counts.items(), key=lambda x: -x[1]):
        label = {
            "no_volunteer_ever_at_station":         "No volunteer ever visited the stuck station",
            "all_volunteers_passed_before_release": "All visitors arrived before parcel release",
            "route_ends_at_stuck_station":          "Volunteer routes end at stuck station (no onward leg)",
            "no_volunteer_route_improves_hops":     "Visitors' onward valid stations don't reduce hop count",
            "all_post_release_volunteers_carrying": "All post-release visitors already carrying a parcel",
            "competing_parcel_always_wins":         "A competing locker parcel always outranked this one",
            "mixed":                                "Multiple reasons (mixed)",
        }.get(cause, cause)
        print(f"  {cnt:4d}  {label}")


if __name__ == "__main__":
    main()
