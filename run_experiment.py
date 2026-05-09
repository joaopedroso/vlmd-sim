"""
Run the full experimental sweep.

Experiment design
-----------------
  10 instances × 3 parcel modes × 11 volunteer fractions × 2 heuristics = 660 runs

Each run uses the instance-specific OD matrix (already realised, variance = 0)
and the corresponding parcel file. The timetable is shared across all runs.

Common-random-numbers design: the seed depends only on (instance, mode), NOT
on the volunteer fraction or heuristic. This guarantees that volunteers at
fraction p are a strict subset of those at fraction p' > p, and that both
heuristics see exactly the same set of volunteers.

Heuristics
----------
  hop   – pick-up / drop-off decided by unweighted hop distance (baseline)
  flow  – pick-up / drop-off decided by flow-weighted Dijkstra distance,
           where arc weight = 1 / daily_OD_flow(A→B)

Output
------
  results/experiment/summary.csv    — one row per run, all statistics

Usage
-----
  uv run python run_experiment.py
  uv run python run_experiment.py --end-time 1380 --leg-time 3
"""

from __future__ import annotations
import argparse
import csv
import random
from pathlib import Path

from simulator.loader import (
    load_graph, load_od_matrices, load_parcels,
    load_timetable, build_timetable_index, od_daily_flows,
)
from simulator.network import Network
from simulator.volunteers import generate_volunteers
from simulator.scheduler import Simulator
from simulator.reporter import compute_stats

DATA_DIR      = Path(__file__).parent / "data"
INSTANCES_DIR = DATA_DIR / "instances"
RESULTS_DIR   = Path(__file__).parent / "results" / "experiment"

PARCEL_MODES         = ("uniform", "positive", "negative")
VOLUNTEER_FRACTIONS  = [round(i / 10, 1) for i in range(11)]
N_INSTANCES          = 10
HEURISTICS           = ("hop", "flow")

SUMMARY_FIELDS = [
    "instance", "parcel_mode", "volunteer_fraction", "heuristic",
    "n_total", "n_delivered", "n_in_transit", "n_at_origin", "delivery_rate",
    "mean_span_min", "median_span_min", "stdev_span_min",
    "min_span_min", "max_span_min",
]


def _seed(instance: int, mode: str) -> int:
    # Seed is independent of volunteer_fraction and heuristic (common random numbers).
    return 1000 * (instance + 1) + 100 * PARCEL_MODES.index(mode)


def run_one(
    instance_idx: int,
    mode: str,
    volunteer_fraction: float,
    heuristic: str,
    network: Network,
    timetable: dict,
    args: argparse.Namespace,
) -> dict:
    instance_dir = INSTANCES_DIR / f"instance_{instance_idx:02d}"
    od_entries   = load_od_matrices(instance_dir / "od_matrix.csv")
    parcels      = load_parcels(instance_dir / f"parcels_{mode}.csv")

    seed = _seed(instance_idx, mode)
    rng  = random.Random(seed)

    volunteers = generate_volunteers(
        od_entries, network, volunteer_fraction, rng, timetable,
        n_days=args.n_days,
    )
    sim = Simulator(
        parcels, volunteers, network,
        leg_time=args.leg_time, timetable=timetable, rng=rng,
        heuristic=heuristic,
    )
    sim.run()

    stats = compute_stats(parcels)
    return {
        "instance":            instance_idx,
        "parcel_mode":         mode,
        "volunteer_fraction":  volunteer_fraction,
        "heuristic":           heuristic,
        **stats,
    }


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.4f}"
    return str(v)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full VLMD experiment sweep")
    parser.add_argument("--data-dir",  type=Path, default=DATA_DIR)
    parser.add_argument("--out-dir",   type=Path, default=RESULTS_DIR)
    parser.add_argument("--n-days",    type=int,  default=7,
                        help="Days volunteers repeat commute (default 7 = one week)")
    parser.add_argument("--leg-time",  type=int,  default=3,
                        help="Fallback leg time in minutes (default 3)")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # --- Shared network and timetable ---
    graph_edges = load_graph(args.data_dir / "graph.csv")
    network     = Network(graph_edges)
    timetable_path = args.data_dir / "timetable.csv"
    timetable   = (
        build_timetable_index(load_timetable(timetable_path), n_days=args.n_days)
        if timetable_path.exists() else {}
    )

    total_runs = N_INSTANCES * len(PARCEL_MODES) * len(VOLUNTEER_FRACTIONS) * len(HEURISTICS)
    print(f"Running {total_runs} simulations "
          f"({N_INSTANCES} instances × {len(PARCEL_MODES)} modes × "
          f"{len(VOLUNTEER_FRACTIONS)} fractions × {len(HEURISTICS)} heuristics)\n")

    summary_path = args.out_dir / "summary.csv"
    with open(summary_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()

        run_idx = 0
        for instance_idx in range(N_INSTANCES):
            # Precompute flow-weighted distances for this instance's OD matrix.
            # Done once per instance; reused across all (mode, fraction, heuristic).
            instance_dir = INSTANCES_DIR / f"instance_{instance_idx:02d}"
            od_for_flow  = load_od_matrices(instance_dir / "od_matrix.csv")
            network.precompute_flow_distances(od_daily_flows(od_for_flow))

            for mode in PARCEL_MODES:
                for p in VOLUNTEER_FRACTIONS:
                    for heuristic in HEURISTICS:
                        run_idx += 1
                        result = run_one(
                            instance_idx, mode, p, heuristic,
                            network, timetable, args,
                        )
                        writer.writerow({k: _fmt(result[k]) for k in SUMMARY_FIELDS})
                        f.flush()

                        rate = result["delivery_rate"]
                        span = result["mean_span_min"]
                        span_str = f"{span:6.1f} min" if span is not None else "    N/A    "
                        print(
                            f"  [{run_idx:3d}/{total_runs}] "
                            f"instance_{instance_idx:02d}  {mode:8s}  p={p:.1f}  "
                            f"{heuristic:3s}  "
                            f"→ {rate:5.1%}  "
                            f"(del={result['n_delivered']:4d} "
                            f"transit={result['n_in_transit']:3d} "
                            f"origin={result['n_at_origin']:3d} / {result['n_total']})  "
                            f"span {span_str}"
                        )

    print(f"\nSummary written to {summary_path}")


if __name__ == "__main__":
    main()
