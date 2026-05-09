"""
Debug script: track log for undelivered parcels.

For each undelivered parcel prints:
  origin → destination  [released HH:MM]  status
  leg N:  picked up at <station> (HH:MM)  →  dropped at <station> (HH:MM)  [Δ min]

Usage
-----
  uv run python debug_track.py                                       # instance 0, uniform, p=0.5, hop
  uv run python debug_track.py --fraction 0.8 --mode negative
  uv run python debug_track.py --instance 2 --fraction 1.0 --heuristic flow
  uv run python debug_track.py --all        # show delivered parcels too
"""

from __future__ import annotations
import argparse
import random
from dataclasses import dataclass
from pathlib import Path

from simulator.loader import (
    load_graph, load_od_matrices, load_parcels, load_stations,
    load_timetable, build_timetable_index, od_daily_flows,
)
from simulator.network import Network
from simulator.volunteers import generate_volunteers
from simulator.scheduler import Simulator
from simulator.reporter import compute_stats

DATA_DIR      = Path("data")
INSTANCES_DIR = DATA_DIR / "instances"
N_DAYS        = 7
LEG_TIME      = 3
PARCEL_MODES  = ("uniform", "positive", "negative")


def _seed(instance: int, mode: str) -> int:
    return 1000 * (instance + 1) + 100 * PARCEL_MODES.index(mode)


def _hhmm(minutes: int) -> str:
    day  = minutes // (24 * 60)
    hhmm = minutes % (24 * 60)
    h, m = hhmm // 60, hhmm % 60
    if day == 0:
        return f"{h:02d}:{m:02d}"
    return f"Day{day+1} {h:02d}:{m:02d}"


# ---------------------------------------------------------------------------
# Instrumented simulator: records (parcel_id, station, time) on every pickup
# ---------------------------------------------------------------------------

@dataclass
class PickupEvent:
    parcel_id: str
    station: str
    time: int


class TrackingSimulator(Simulator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pickups: list[PickupEvent] = []

    def run(self):
        self._pickups.clear()
        return super().run()

    def _on_volunteer_at(self, event):
        volunteer, station_idx = event.payload
        current_station = volunteer.route[station_idx]
        carrying_before = volunteer.carrying

        super()._on_volunteer_at(event)

        # Record a pickup whenever the carried parcel changes to a new one,
        # whether the volunteer arrived empty or dropped-and-picked-up.
        carrying_after = volunteer.carrying
        if carrying_after is not None and carrying_after != carrying_before:
            self._pickups.append(PickupEvent(
                parcel_id=carrying_after,
                station=current_station,
                time=event.time,
            ))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance",  type=int,   default=0)
    parser.add_argument("--mode",      default="uniform", choices=list(PARCEL_MODES))
    parser.add_argument("--fraction",  type=float, default=0.5)
    parser.add_argument("--heuristic", default="hop", choices=["hop", "flow"])
    parser.add_argument("--all",       action="store_true",
                        help="Show delivered parcels too (default: undelivered only)")
    args = parser.parse_args()

    instance_dir = INSTANCES_DIR / f"instance_{args.instance:02d}"

    graph_edges = load_graph(DATA_DIR / "graph.csv")
    network     = Network(graph_edges)
    stations    = load_stations(DATA_DIR / "stations.csv")
    timetable   = build_timetable_index(
        load_timetable(DATA_DIR / "timetable.csv"), n_days=N_DAYS
    )

    od_entries = load_od_matrices(instance_dir / "od_matrix.csv")
    parcels    = load_parcels(instance_dir / f"parcels_{args.mode}.csv")

    if args.heuristic == "flow":
        network.precompute_flow_distances(od_daily_flows(od_entries))

    rng = random.Random(_seed(args.instance, args.mode))
    volunteers = generate_volunteers(
        od_entries, network, args.fraction, rng, timetable, n_days=N_DAYS,
    )

    sim = TrackingSimulator(
        parcels, volunteers, network,
        leg_time=LEG_TIME, timetable=timetable, rng=rng,
        heuristic=args.heuristic,
    )
    movements = sim.run()

    def sname(sid: str) -> str:
        return stations[sid].name if sid in stations else sid

    pickups_by_parcel: dict[str, list[PickupEvent]] = {}
    for pe in sorted(sim._pickups, key=lambda e: e.time):
        pickups_by_parcel.setdefault(pe.parcel_id, []).append(pe)

    from simulator.model import Movement
    dropoffs_by_parcel: dict[str, list[Movement]] = {}
    for m in sorted(movements, key=lambda m: m.timestamp):
        dropoffs_by_parcel.setdefault(m.parcel_id, []).append(m)

    stats = compute_stats(parcels)
    print(
        f"Instance {args.instance:02d}  mode={args.mode}  p={args.fraction}  heuristic={args.heuristic}\n"
        f"Delivered {stats['n_delivered']}/{stats['n_total']}  "
        f"in-transit {stats['n_in_transit']}  at-origin {stats['n_at_origin']}\n"
    )

    show = parcels if args.all else [p for p in parcels if not p.delivered]
    show = sorted(show, key=lambda p: p.parcel_id)

    if not show:
        print("All parcels delivered.")
        return

    for parcel in show:
        orig = sname(parcel.origin)
        dest = sname(parcel.destination)
        rel  = _hhmm(parcel.release_time)

        picks = pickups_by_parcel.get(parcel.parcel_id, [])
        drops = dropoffs_by_parcel.get(parcel.parcel_id, [])

        if parcel.delivered:
            status = f"DELIVERED at {_hhmm(parcel.delivery_time)}  (span {parcel.delivery_time - parcel.release_time} min)"
        elif parcel.current_locker != parcel.origin:
            status = f"IN TRANSIT — last locker: {sname(parcel.current_locker)}"
        else:
            status = "AT ORIGIN (never moved)"

        print(f"Parcel {parcel.parcel_id}: {orig} → {dest}  [released {rel}]  {status}")

        if not picks and not drops:
            print("  (no movements)")
        else:
            n_legs = max(len(picks), len(drops))
            for i in range(n_legs):
                pu_str = (
                    f"picked up at {sname(picks[i].station)} ({_hhmm(picks[i].time)})"
                    if i < len(picks) else "pickup ?"
                )
                if i < len(drops):
                    dr = drops[i]
                    dr_str = f"dropped at {sname(dr.to_station)} ({_hhmm(dr.timestamp)})"
                    if i < len(picks):
                        dr_str += f"  [Δ {drops[i].timestamp - picks[i].time} min]"
                else:
                    dr_str = "drop ?"
                print(f"  leg {i+1}: {pu_str}  →  {dr_str}")

        print()


if __name__ == "__main__":
    main()
