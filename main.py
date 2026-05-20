"""Entry point for the parcel delivery simulator."""

from __future__ import annotations
import argparse
import random
from pathlib import Path

from simulator.loader import (
    load_graph, load_od_matrices, load_parcels,
    load_timetable, build_timetable_index, od_daily_flows,
)
from simulator.network import Network
from simulator.volunteers import generate_volunteers
from simulator.scheduler import Simulator
from simulator.reporter import (
    compute_stats, save_movements, save_parcel_summary,
    compute_locker_stats, save_locker_stats,
)
from simulator.loader import load_stations


DATA_DIR = Path(__file__).parent / "data"
RESULTS_DIR = Path(__file__).parent / "results"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crowd-sourced parcel delivery simulator")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--results-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument(
        "--volunteer-fraction", "-p", type=float, default=0.1,
        help="Fraction of commuters that act as volunteers (default: 0.1). "
             "Use 0.0 to sweep all fractions from 0%% to 100%%.",
    )
    parser.add_argument(
        "--n-days", type=int, default=1,
        help="Number of days volunteers repeat their commute (default: 1). "
             "end-time defaults to n-days × 1440 min unless overridden.",
    )
    parser.add_argument(
        "--end-time", type=int, default=None,
        help="Hard cutoff in minutes (default: none — runs until queue is empty)",
    )
    parser.add_argument(
        "--leg-time", type=int, default=3,
        help="Default travel time per metro leg in minutes (default: 3)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-run output")
    parser.add_argument("--locker-stats", action="store_true",
                        help="Write per-station locker occupancy CSV after each run")
    parser.add_argument("--sweep", action="store_true",
                        help="Sweep volunteer fraction from 0%% to 100%% in steps of 10%%")
    parser.add_argument(
        "--heuristic",
        choices=("hop", "flow", "hop+", "flow+"),
        default="hop",
        help="Transshipment heuristic: 'hop' (BFS hops) or 'flow' (1/OD-flow Dijkstra); "
             "'+' adds 1-day-wait fallback to combined (OD+transit) flow hub",
    )
    return parser.parse_args()


def run_simulation(args: argparse.Namespace, volunteer_fraction: float) -> dict:
    rng = random.Random(args.seed)

    graph_edges = load_graph(args.data_dir / "graph.csv")
    network = Network(graph_edges)
    od_entries = load_od_matrices(args.data_dir / "od_matrices.csv")
    flows = od_daily_flows(od_entries)
    if args.heuristic in ("flow", "flow+"):
        network.precompute_flow_distances(flows)   # also computes station+transit flows
    elif args.heuristic == "hop+":
        network.precompute_station_flows(flows)
        network.precompute_transit_flows(flows)
    parcels = load_parcels(args.data_dir / "parcels.csv")

    timetable_path = args.data_dir / "timetable.csv"
    timetable = (
        build_timetable_index(load_timetable(timetable_path), n_days=args.n_days)
        if timetable_path.exists() else {}
    )

    volunteers = generate_volunteers(
        od_entries, network, volunteer_fraction=volunteer_fraction,
        rng=rng, timetable=timetable, n_days=args.n_days,
    )

    if not args.quiet:
        print(f"\n[p={volunteer_fraction:.2f}] {len(volunteers)} volunteers | {len(parcels)} parcels")

    sim = Simulator(
        parcels, volunteers, network,
        end_time=args.end_time, leg_time=args.leg_time, timetable=timetable, rng=rng,
        heuristic=args.heuristic,
    )
    movements = sim.run()

    stats = compute_stats(parcels)
    if not args.quiet:
        print(f"  Delivered: {stats['n_delivered']}/{stats['n_total']} "
              f"({stats['delivery_rate']:.1%})")
        if stats["mean_span_min"] is not None:
            print(f"  Mean delivery span: {stats['mean_span_min']:.1f} min  "
                  f"(median {stats['median_span_min']:.1f} min, "
                  f"range [{stats['min_span_min']:.0f}, {stats['max_span_min']:.0f}] min)")

    tag = f"p{int(volunteer_fraction * 100):03d}"
    save_movements(movements, args.results_dir / f"movements_{tag}.csv")
    save_parcel_summary(parcels, args.results_dir / f"parcels_{tag}.csv")

    if args.locker_stats:
        station_names = {sid: s.name for sid, s in
                         load_stations(args.data_dir / "stations.csv").items()}
        history = sim.get_locker_history(end_time=args.n_days * 1440)
        lstats  = compute_locker_stats(history, station_names)
        save_locker_stats(lstats, args.results_dir / f"locker_stats_{tag}.csv")
        if not args.quiet:
            print(f"\n  Top-10 stations by peak locker occupancy:")
            print(f"  {'Station':30s}  {'peak':>5}  {'total':>6}  {'mean':>6}")
            for row in lstats[:10]:
                print(f"  {row['station_name']:30s}  {row['peak_occupancy']:>5d}"
                      f"  {row['total_parcels']:>6d}  {row['mean_occupancy']:>6.2f}")

    return {"volunteer_fraction": volunteer_fraction, **stats}


def main() -> None:
    args = parse_args()

    if args.sweep:
        fractions = [round(i / 10, 1) for i in range(0, 11)]
        print("Sweeping volunteer fraction from 0% to 100% ...")
        all_stats = [run_simulation(args, p) for p in fractions]
        print("\n--- Summary ---")
        print(f"{'p':>6}  {'delivered':>10}  {'rate':>8}  {'mean_span':>12}  {'median_span':>12}")
        for s in all_stats:
            mean_s = f"{s['mean_span_min']:.1f}" if s["mean_span_min"] is not None else "N/A"
            med_s = f"{s['median_span_min']:.1f}" if s["median_span_min"] is not None else "N/A"
            print(f"{s['volunteer_fraction']:>6.2f}  {s['n_delivered']:>4}/{s['n_total']:<5}  "
                  f"{s['delivery_rate']:>7.1%}  {mean_s:>12}  {med_s:>12}")
    else:
        run_simulation(args, args.volunteer_fraction)


if __name__ == "__main__":
    main()
