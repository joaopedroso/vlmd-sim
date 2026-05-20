"""
Run the full experimental sweep.

Experiment design
-----------------
  10 instances × 3 parcel modes × 10 volunteer fractions × 4 heuristics = 1200 runs

Each run uses the instance-specific OD matrix (already realised, variance = 0)
and the corresponding parcel file. The timetable is shared across all runs.

Common-random-numbers design: the seed depends only on (instance, mode), NOT
on the volunteer fraction or heuristic.

Heuristics
----------
  hop   – Phase 1 only; unweighted hop distance (baseline)
  flow  – Phase 1 only; flow-weighted Dijkstra distance (arc = 1/OD_flow)
  hop+  – hop + Phase-2 fallback: move to busier hub (OD+transit flow) after ≥1-day wait
  flow+ – flow + Phase-2 fallback

Output
------
  results/experiment/summary.csv    — one row per run, all statistics

Usage
-----
  uv run python run_experiment.py
  uv run python run_experiment.py --resume   # append, skipping already-done rows
  uv run python run_experiment.py --leg-time 3
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
VOLUNTEER_FRACTIONS  = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
N_INSTANCES          = 10
HEURISTICS           = ("hop", "flow", "hop+", "flow+")

SUMMARY_FIELDS = [
    "instance", "parcel_mode", "volunteer_fraction", "heuristic",
    "n_total", "n_delivered", "n_in_transit", "n_at_origin", "n_same_day",
    "delivery_rate", "same_day_rate",
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
    instance_dir = args.instances_dir / f"instance_{instance_idx:02d}"
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
    parser.add_argument("--data-dir",      type=Path, default=DATA_DIR)
    parser.add_argument("--instances-dir", type=Path, default=INSTANCES_DIR)
    parser.add_argument("--out-dir",       type=Path, default=RESULTS_DIR)
    parser.add_argument("--n-days",    type=int,  default=7,
                        help="Days volunteers repeat commute (default 7 = one week)")
    parser.add_argument("--leg-time",  type=int,  default=3,
                        help="Fallback leg time in minutes (default 3)")
    parser.add_argument("--resume",    action="store_true",
                        help="Append to existing summary.csv, skipping already-completed runs")
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

    # Count already-completed rows when resuming.
    skip_runs = 0
    if args.resume and summary_path.exists():
        with open(summary_path, newline="") as rf:
            skip_runs = sum(1 for _ in rf) - 1  # subtract header
        skip_runs = max(skip_runs, 0)
        print(f"Resuming: skipping first {skip_runs} completed runs\n")

    file_mode = "a" if (args.resume and skip_runs > 0) else "w"
    with open(summary_path, file_mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDS)
        if file_mode == "w":
            writer.writeheader()

        run_idx = 0
        for instance_idx in range(N_INSTANCES):
            # Check if this entire instance is already done; if so skip precompute.
            runs_in_instance = len(PARCEL_MODES) * len(VOLUNTEER_FRACTIONS) * len(HEURISTICS)
            if skip_runs >= run_idx + runs_in_instance:
                run_idx += runs_in_instance
                continue

            # Precompute distances for this instance's OD matrix.
            # Done once per instance; reused across all (mode, fraction, heuristic).
            instance_dir = args.instances_dir / f"instance_{instance_idx:02d}"
            od_for_flow  = load_od_matrices(instance_dir / "od_matrix.csv")
            flows_for_instance = od_daily_flows(od_for_flow)
            # precompute_flow_distances also computes station flows and transit flows
            network.precompute_flow_distances(flows_for_instance)

            for mode in PARCEL_MODES:
                for p in VOLUNTEER_FRACTIONS:
                    for heuristic in HEURISTICS:
                        run_idx += 1
                        if run_idx <= skip_runs:
                            continue

                        result = run_one(
                            instance_idx, mode, p, heuristic,
                            network, timetable, args,
                        )
                        writer.writerow({k: _fmt(result[k]) for k in SUMMARY_FIELDS})
                        f.flush()

                        rate = result["delivery_rate"]
                        sdr  = result["same_day_rate"]
                        span = result["mean_span_min"]
                        span_str = f"{span:6.1f} min" if span is not None else "    N/A    "
                        print(
                            f"  [{run_idx:3d}/{total_runs}] "
                            f"instance_{instance_idx:02d}  {mode:8s}  p={p*100:.3g}%  "
                            f"{heuristic:8s}  "
                            f"→ {rate:5.1%} (sd {sdr:5.1%})  "
                            f"(del={result['n_delivered']:4d} "
                            f"transit={result['n_in_transit']:3d} "
                            f"origin={result['n_at_origin']:3d} / {result['n_total']})  "
                            f"span {span_str}"
                        )

    print(f"\nSummary written to {summary_path}")


if __name__ == "__main__":
    main()
