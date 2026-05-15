"""
Analyse delivery performance as a function of parcel load.

Reads multiple summary.csv files (one per parcel fraction) and produces
plots with parcel load on the x-axis, aggregated over volunteer fractions.

Usage
-----
  uv run python analyse_loads.py               # uses default load table below
  uv run python analyse_loads.py --out-dir results/loads
  uv run python analyse_loads.py --heuristic hop

Each summary file must have been produced by run_experiment.py.

Output (written to --out-dir, default results/loads/)
------------------------------------------------------
  delivery_rate_vs_load.png   — delivery rate vs parcel load
  same_day_rate_vs_load.png   — same-day delivery rate vs parcel load
  delivery_span_vs_load.png   — mean delivery span vs parcel load
"""

from __future__ import annotations
import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.cm as cm
import numpy as np

# ---------------------------------------------------------------------------
# Default experiment table: (parcel_fraction_pct, summary_csv_path)
# ---------------------------------------------------------------------------

_BASE = Path(__file__).parent / "results"

DEFAULT_LOADS: list[tuple[float, Path]] = [
    (0.01, _BASE / "experiment_0.01pct" / "summary.csv"),
    (0.02, _BASE / "experiment_0.02pct" / "summary.csv"),
    (0.05, _BASE / "experiment_0.05pct" / "summary.csv"),
    (0.1,  _BASE / "experiment_0.1pct"  / "summary.csv"),
    (0.2,  _BASE / "experiment_0.2pct"  / "summary.csv"),
    (0.5,  _BASE / "experiment_0.5pct"  / "summary.csv"),
    (1.0,  _BASE / "experiment"         / "summary.csv"),
]

MODES = ("uniform", "positive", "negative")
MODE_LABELS = {
    "uniform":  "Uniform",
    "positive": "Positive correlation",
    "negative": "Negative correlation",
}

# Volunteer fractions used in experiments
VOL_FRACTIONS = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]


# ---------------------------------------------------------------------------
# Data loading and aggregation
# ---------------------------------------------------------------------------

def load_summary(path: Path, heuristic: str) -> list[dict]:
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("heuristic", "hop") != heuristic:
                continue
            r["volunteer_fraction"] = float(r["volunteer_fraction"])
            r["delivery_rate"]      = float(r["delivery_rate"])
            r["same_day_rate"]      = float(r["same_day_rate"]) if r.get("same_day_rate") else 0.0
            r["mean_span_min"]      = float(r["mean_span_min"]) if r.get("mean_span_min") else None
            r["n_total"]            = int(r["n_total"])
            rows.append(r)
    return rows


def aggregate(rows: list[dict], key: str) -> dict[tuple[str, float], tuple[float, float]]:
    """
    Return {(mode, vol_frac): (mean, std)} for the given key across instances.
    """
    buckets: dict[tuple[str, float], list[float]] = defaultdict(list)
    for r in rows:
        if r["parcel_mode"] not in MODES:
            continue
        val = r.get(key)
        if val is None:
            continue
        buckets[(r["parcel_mode"], r["volunteer_fraction"])].append(float(val))
    out = {}
    for k, vals in buckets.items():
        out[k] = (
            statistics.mean(vals),
            statistics.stdev(vals) if len(vals) > 1 else 0.0,
        )
    return out


# ---------------------------------------------------------------------------
# Colour map: one colour per volunteer fraction
# ---------------------------------------------------------------------------

def _vol_colormap() -> dict[float, tuple]:
    cmap = matplotlib.colormaps["plasma"].resampled(len(VOL_FRACTIONS))
    return {f: cmap(i) for i, f in enumerate(VOL_FRACTIONS)}


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def _pct_x(ax, loads: list[float]) -> None:
    ax.set_xscale("log")
    ax.set_xticks(loads)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.4g}%"))
    ax.tick_params(axis="x", which="minor", bottom=False)
    ax.set_xlim(loads[0] / 1.5, loads[-1] * 1.5)


def _pct_y(ax) -> None:
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1.0, decimals=0))


# ---------------------------------------------------------------------------
# Figure factory
# ---------------------------------------------------------------------------

def _plot_metric(
    data_by_load: dict[float, dict],   # load_pct → {(mode, vol_frac): (mean, std)}
    metric: str,
    ylabel: str,
    title: str,
    out_path: Path,
    is_rate: bool = True,
) -> None:
    loads = sorted(data_by_load.keys())
    colors = _vol_colormap()

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), sharey=True)

    for ax, mode in zip(axes, MODES):
        for vf in VOL_FRACTIONS:
            xs, ys, y_lo, y_hi = [], [], [], []
            for load in loads:
                entry = data_by_load[load].get((mode, vf))
                if entry is None:
                    continue
                m, s = entry
                xs.append(load); ys.append(m)
                y_lo.append(m - s); y_hi.append(m + s)
            if not xs:
                continue
            label = f"{vf*100:.4g}%"
            ax.plot(xs, ys, marker="o", markersize=3, linewidth=1.5,
                    color=colors[vf], label=label)
            ax.fill_between(xs, y_lo, y_hi, alpha=0.08, color=colors[vf])

        ax.set_title(MODE_LABELS[mode], fontsize=10)
        ax.set_xlabel("Parcel load (% of daily trips)", fontsize=9)
        _pct_x(ax, loads)
        if is_rate:
            _pct_y(ax)
            ax.set_ylim(-0.02, 1.05)
        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        ax.grid(axis="x", linestyle=":",  linewidth=0.4, alpha=0.4)

    axes[0].set_ylabel(ylabel, fontsize=10)

    # Single legend for volunteer fractions
    handles, labels = axes[-1].get_legend_handles_labels()
    fig.legend(handles, labels, title="Volunteer %", loc="center right",
               fontsize=7, title_fontsize=8, bbox_to_anchor=(1.01, 0.5))
    fig.suptitle(title, fontsize=11)
    fig.tight_layout(rect=[0, 0, 0.92, 1])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse delivery vs parcel load")
    parser.add_argument("--out-dir",   type=Path, default=Path("results/loads"))
    parser.add_argument("--heuristic", default="flow", choices=["hop", "flow"])
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Load all available summary files
    available = [(load, path) for load, path in DEFAULT_LOADS if path.exists()]
    if not available:
        raise SystemExit("No summary files found. Run run_experiment.py for each load first.")

    missing = [load for load, path in DEFAULT_LOADS if not path.exists()]
    if missing:
        print(f"Note: missing results for loads: {[f'{l}%' for l in missing]} — skipped.")

    print(f"Loading {len(available)} load levels "
          f"({[f'{l}%' for l, _ in available]}), heuristic={args.heuristic}\n")

    rate_by_load: dict[float, dict] = {}
    sday_by_load: dict[float, dict] = {}
    span_by_load: dict[float, dict] = {}

    for load_pct, path in available:
        rows = load_summary(path, args.heuristic)
        rate_by_load[load_pct] = aggregate(rows, "delivery_rate")
        sday_by_load[load_pct] = aggregate(rows, "same_day_rate")
        span_by_load[load_pct] = aggregate(rows, "mean_span_min")

    _plot_metric(
        rate_by_load, "delivery_rate", "Delivery rate",
        f"Delivery rate vs parcel load  (heuristic={args.heuristic})",
        args.out_dir / "delivery_rate_vs_load.png",
        is_rate=True,
    )
    _plot_metric(
        sday_by_load, "same_day_rate", "Same-day delivery rate",
        f"Same-day delivery rate vs parcel load  (heuristic={args.heuristic})",
        args.out_dir / "same_day_rate_vs_load.png",
        is_rate=True,
    )
    _plot_metric(
        span_by_load, "mean_span_min", "Mean delivery span (min)",
        f"Mean delivery span vs parcel load  (heuristic={args.heuristic})",
        args.out_dir / "delivery_span_vs_load.png",
        is_rate=False,
    )


if __name__ == "__main__":
    main()
