"""
Generate 10 independent passenger OD matrix instances and three parcel sets each.

For each instance a passenger OD matrix is realised by sampling once from the
base Normal distribution (mean, sqrt(variance)) per (hour, origin, destination)
entry. Three parcel sets are then produced from 1 % of the total realised trips:

  uniform   – parcel OD drawn uniformly over all ordered station pairs
  positive  – parcel OD proportional to aggregated passenger flow
              (parcels go where passengers go → easy delivery)
  negative  – parcel OD inversely proportional to aggregated passenger flow
              (parcels go to low-traffic routes → worst-case scenario)

Output layout
-------------
data/instances/
  instance_00/
    od_matrix.csv          realised counts; variance_passengers = 0 (deterministic)
    parcels_uniform.csv
    parcels_positive.csv
    parcels_negative.csv
    metadata.json
  instance_01/ ...
"""

from __future__ import annotations
import argparse
import csv
import json
import math
import random
from pathlib import Path

from simulator.loader import load_od_matrices, load_stations
from simulator.model import ODEntry


def _poisson(rng: random.Random, lam: float) -> int:
    """Sample from Poisson(lam). Knuth's algorithm for lam ≤ 30, Normal approx above."""
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


DATA_DIR      = Path(__file__).parent / "data"
INSTANCES_DIR = DATA_DIR / "instances"

PARCEL_FRACTION = 0.01       # 1 % of total daily realised passenger trips
RELEASE_START   = 7  * 60   # 07:00 — earliest parcel release on day 0 (minutes since midnight)
RELEASE_END     = 19 * 60   # 19:00 — latest  parcel release on day 0

PARCEL_MODES = ("uniform", "positive", "negative")


# ---------------------------------------------------------------------------
# OD matrix realisation
# ---------------------------------------------------------------------------

def realize_od_matrix(base: list[ODEntry], rng: random.Random) -> list[ODEntry]:
    """Sample one Poisson realisation from the base distribution; store with variance = 0."""
    out: list[ODEntry] = []
    for e in base:
        count = float(_poisson(rng, e.mean_passengers))
        out.append(ODEntry(
            hour=e.hour,
            origin=e.origin,
            destination=e.destination,
            mean_passengers=count,
            variance_passengers=0.0,
        ))
    return out


def aggregate_od_flow(entries: list[ODEntry]) -> dict[tuple[str, str], float]:
    """Total passengers summed over all hours for each (origin, destination) pair."""
    flow: dict[tuple[str, str], float] = {}
    for e in entries:
        key = (e.origin, e.destination)
        flow[key] = flow.get(key, 0.0) + e.mean_passengers
    return flow


# ---------------------------------------------------------------------------
# Parcel generation
# ---------------------------------------------------------------------------

def _parcel_weights(
    all_pairs: list[tuple[str, str]],
    od_flow: dict[tuple[str, str], float],
    mode: str,
) -> list[float] | None:
    """Return sampling weights for all_pairs (None = uniform)."""
    if mode == "uniform":
        return None
    if mode == "positive":
        # proportional to passenger flow; +ε so zero-flow pairs are still reachable
        return [od_flow.get(p, 0.0) + 1e-6 for p in all_pairs]
    if mode == "negative":
        # inversely proportional: scarce volunteer coverage → harder delivery
        return [1.0 / (od_flow.get(p, 0.0) + 1.0) for p in all_pairs]
    raise ValueError(f"Unknown mode: {mode!r}")


def generate_parcels(
    n: int,
    station_ids: list[str],
    od_flow: dict[tuple[str, str], float],
    mode: str,
    rng: random.Random,
) -> list[dict]:
    all_pairs = [(o, d) for o in station_ids for d in station_ids if o != d]
    weights   = _parcel_weights(all_pairs, od_flow, mode)

    chosen: list[tuple[str, str]] = rng.choices(all_pairs, weights=weights, k=n)

    records: list[dict] = []
    for i, (origin, dest) in enumerate(chosen):
        t = rng.randint(RELEASE_START, RELEASE_END)
        records.append({
            "parcel_id":    f"P{i:05d}",
            "release_time": f"{t // 60:02d}:{t % 60:02d}",
            "origin":       origin,
            "destination":  dest,
            "current_locker": origin,
        })
    # sort by release time for readability
    records.sort(key=lambda r: r["release_time"])
    # re-number after sort
    for i, r in enumerate(records):
        r["parcel_id"] = f"P{i:05d}"
    return records


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def save_od_matrix(entries: list[ODEntry], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["hour", "origin", "destination",
                           "mean_passengers", "variance_passengers"],
        )
        w.writeheader()
        for e in entries:
            w.writerow({
                "hour": e.hour,
                "origin": e.origin,
                "destination": e.destination,
                "mean_passengers": f"{e.mean_passengers:.4f}",
                "variance_passengers": f"{e.variance_passengers:.4f}",
            })


def save_parcels(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=["parcel_id", "release_time", "origin",
                           "destination", "current_locker"],
        )
        w.writeheader()
        w.writerows(records)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate experiment instances")
    parser.add_argument("--n-instances",     type=int,   default=10)
    parser.add_argument("--base-seed",       type=int,   default=0)
    parser.add_argument("--parcel-fraction", type=float, default=PARCEL_FRACTION)
    parser.add_argument("--data-dir",        type=Path,  default=DATA_DIR)
    parser.add_argument("--out-dir",         type=Path,  default=INSTANCES_DIR)
    args = parser.parse_args()

    base_entries  = load_od_matrices(args.data_dir / "od_matrices.csv")
    stations_dict = load_stations(args.data_dir / "stations.csv")

    # Restrict parcel OD to stations that actually appear in the OD matrix.
    # Stations in graph.csv but absent from od_matrices.csv have no volunteer
    # coverage (no commuters use them as origin/destination) and would create
    # permanently undeliverable parcels.
    od_stations = {e.origin for e in base_entries} | {e.destination for e in base_entries}
    station_ids = sorted(od_stations & set(stations_dict.keys()))

    base_total = sum(e.mean_passengers for e in base_entries)
    print(f"Base OD matrix : {len(base_entries)} entries | "
          f"{base_total:.0f} mean passenger-trips | "
          f"{len(station_ids)} stations (OD-covered)")
    print(f"Parcel fraction: {args.parcel_fraction:.1%}  "
          f"(≈{round(base_total * args.parcel_fraction)} parcels/instance)\n")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    for i in range(args.n_instances):
        seed = args.base_seed + i
        rng  = random.Random(seed)

        instance_dir = args.out_dir / f"instance_{i:02d}"

        # Realise OD matrix
        realized    = realize_od_matrix(base_entries, rng)
        total_trips = sum(e.mean_passengers for e in realized)
        n_parcels   = max(1, round(total_trips * args.parcel_fraction))
        od_flow     = aggregate_od_flow(realized)

        save_od_matrix(realized, instance_dir / "od_matrix.csv")

        # Generate parcel sets
        for mode in PARCEL_MODES:
            records = generate_parcels(n_parcels, station_ids, od_flow, mode, rng)
            save_parcels(records, instance_dir / f"parcels_{mode}.csv")

        # Save metadata
        meta = {
            "instance":        i,
            "seed":            seed,
            "total_trips":     round(total_trips, 2),
            "n_parcels":       n_parcels,
            "parcel_fraction": args.parcel_fraction,
            "n_stations":      len(station_ids),
            "parcel_modes":    list(PARCEL_MODES),
        }
        with open(instance_dir / "metadata.json", "w") as f:
            json.dump(meta, f, indent=2)

        print(f"  instance_{i:02d}  seed={seed}  "
              f"trips={total_trips:.0f}  parcels={n_parcels}")

    print(f"\nDone — {args.n_instances} instances written to {args.out_dir}")


if __name__ == "__main__":
    main()
