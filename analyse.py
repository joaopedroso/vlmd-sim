"""
Analyse experimental sweep results and produce comparison plots.

Reads results/experiment/summary.csv (produced by run_experiment.py).

If the summary contains both heuristics (hop + flow), produces side-by-side
comparison plots.  If only one heuristic is present the plots degrade
gracefully to single-heuristic figures.

Output (written to --out-dir, default results/experiment/)
----------------------------------------------------------
  delivery_rate.png   — delivery rate vs volunteer fraction
  delivery_span.png   — mean delivery span vs volunteer fraction
  parcel_fate.png     — stacked fate breakdown (delivered / in-transit / stuck)

Each figure has 3 panels (one per parcel mode).  Within each panel, solid
lines = flow heuristic, dashed lines = hop heuristic.

Usage
-----
  uv run python analyse.py
  uv run python analyse.py --summary results/experiment/summary.csv
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

RESULTS_DIR = Path(__file__).parent / "results" / "experiment"

MODES = ("uniform", "positive", "negative")
MODE_LABELS = {
    "uniform":  "Uniform",
    "positive": "Positive correlation",
    "negative": "Negative correlation",
}
MODE_COLORS = {
    "uniform":  "#4e79a7",
    "positive": "#59a14f",
    "negative": "#e15759",
}
HEURISTIC_STYLE = {
    "hop":  {"linestyle": "--", "alpha": 0.85},
    "flow": {"linestyle": "-",  "alpha": 1.00},
}
HEURISTIC_LABEL = {"hop": "hop", "flow": "flow"}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_summary(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["volunteer_fraction"] = float(r["volunteer_fraction"])
        r["delivery_rate"]      = float(r["delivery_rate"])
        r["mean_span_min"]      = float(r["mean_span_min"]) if r["mean_span_min"] else None
        r["n_total"]            = int(r["n_total"])
        r["n_in_transit"]       = int(r["n_in_transit"])  if r.get("n_in_transit")  else 0
        r["n_at_origin"]        = int(r["n_at_origin"])   if r.get("n_at_origin")   else 0
        # backward compat: summary files without heuristic column are treated as "hop"
        r.setdefault("heuristic", "hop")
    return rows


def aggregate(rows: list[dict]) -> dict:
    """
    Return nested dict: heuristic → mode → fraction → stats-dict.
    """
    heuristics = sorted({r["heuristic"] for r in rows})
    result: dict[str, dict] = {}
    for h in heuristics:
        h_rows = [r for r in rows if r["heuristic"] == h]
        result[h] = _aggregate_one(h_rows)
    return result


def _aggregate_one(rows: list[dict]) -> dict:
    bucket: dict[str, dict[float, list]] = {m: defaultdict(list) for m in MODES}
    for r in rows:
        if r["parcel_mode"] in bucket:
            bucket[r["parcel_mode"]][r["volunteer_fraction"]].append(r)

    out: dict[str, dict] = {}
    for mode in MODES:
        out[mode] = {}
        for frac, rlist in sorted(bucket[mode].items()):
            rates    = [r["delivery_rate"] for r in rlist]
            spans    = [r["mean_span_min"] for r in rlist if r["mean_span_min"] is not None]
            transits = [r["n_in_transit"] / r["n_total"] for r in rlist]
            origins  = [r["n_at_origin"]  / r["n_total"] for r in rlist]
            out[mode][frac] = {
                "mean_rate":    statistics.mean(rates),
                "std_rate":     statistics.stdev(rates)    if len(rates)  > 1 else 0.0,
                "mean_span":    statistics.mean(spans)     if spans            else None,
                "std_span":     statistics.stdev(spans)    if len(spans)  > 1  else None,
                "mean_transit": statistics.mean(transits),
                "std_transit":  statistics.stdev(transits) if len(transits) > 1 else 0.0,
                "mean_origin":  statistics.mean(origins),
                "n_instances":  len(rates),
            }
    return out


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

def _pct_labels(ax, axis: str = "y") -> None:
    fmt = mticker.PercentFormatter(xmax=1.0, decimals=0)
    if axis == "y":
        ax.yaxis.set_major_formatter(fmt)
    else:
        ax.xaxis.set_major_formatter(fmt)


def _heuristic_legend(ax, heuristics: list[str]) -> None:
    """Add a small secondary legend for linestyle → heuristic mapping."""
    if len(heuristics) < 2:
        return
    from matplotlib.lines import Line2D
    handles = [
        Line2D([0], [0], color="grey", **HEURISTIC_STYLE[h], linewidth=1.6,
               label=HEURISTIC_LABEL[h])
        for h in heuristics
    ]
    ax.legend(handles=handles, fontsize=8, loc="lower right", framealpha=0.8)


# ---------------------------------------------------------------------------
# Figure 1 — Delivery rate
# ---------------------------------------------------------------------------

def plot_delivery_rate(agg: dict, out_path: Path) -> None:
    heuristics = sorted(agg.keys())
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), sharey=True)

    for ax, mode in zip(axes, MODES):
        color = MODE_COLORS[mode]
        for h in heuristics:
            data  = agg[h][mode]
            fracs = sorted(data.keys())
            means = [data[f]["mean_rate"] for f in fracs]
            stds  = [data[f]["std_rate"]  for f in fracs]
            style = HEURISTIC_STYLE[h]
            ax.plot(fracs, means, marker="o", markersize=3, color=color,
                    linewidth=1.8, label=HEURISTIC_LABEL[h], **style)
            ax.fill_between(
                fracs,
                [m - s for m, s in zip(means, stds)],
                [m + s for m, s in zip(means, stds)],
                alpha=0.10, color=color,
            )
        ax.set_title(MODE_LABELS[mode], fontsize=10)
        ax.set_xlabel("Volunteer fraction", fontsize=9)
        _pct_labels(ax, "x")
        _pct_labels(ax, "y")
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.05)
        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        ax.grid(axis="x", linestyle=":",  linewidth=0.4, alpha=0.4)
        _heuristic_legend(ax, heuristics)

    axes[0].set_ylabel("Delivery rate", fontsize=10)
    fig.suptitle("Delivery rate vs volunteer fraction  "
                 "(solid = flow, dashed = hop)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Figure 2 — Delivery span
# ---------------------------------------------------------------------------

def plot_delivery_span(agg: dict, out_path: Path) -> None:
    heuristics = sorted(agg.keys())
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), sharey=True)

    for ax, mode in zip(axes, MODES):
        color = MODE_COLORS[mode]
        for h in heuristics:
            data  = agg[h][mode]
            fracs = sorted(data.keys())
            xs, ys, y_lo, y_hi = [], [], [], []
            for f in fracs:
                m = data[f]["mean_span"]
                s = data[f]["std_span"]
                if m is not None:
                    xs.append(f); ys.append(m)
                    y_lo.append(m - (s or 0.0))
                    y_hi.append(m + (s or 0.0))
            if not xs:
                continue
            style = HEURISTIC_STYLE[h]
            ax.plot(xs, ys, marker="o", markersize=3, color=color,
                    linewidth=1.8, label=HEURISTIC_LABEL[h], **style)
            ax.fill_between(xs, y_lo, y_hi, alpha=0.10, color=color)
        ax.set_title(MODE_LABELS[mode], fontsize=10)
        ax.set_xlabel("Volunteer fraction", fontsize=9)
        _pct_labels(ax, "x")
        ax.set_xlim(-0.02, 1.02)
        ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        ax.grid(axis="x", linestyle=":",  linewidth=0.4, alpha=0.4)
        _heuristic_legend(ax, heuristics)

    axes[0].set_ylabel("Mean delivery span (min)", fontsize=10)
    fig.suptitle("Mean delivery span vs volunteer fraction  "
                 "(solid = flow, dashed = hop)", fontsize=11)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Figure 3 — Parcel fate (stacked area, one row per heuristic)
# ---------------------------------------------------------------------------

def plot_parcel_fate(agg: dict, out_path: Path) -> None:
    heuristics = sorted(agg.keys())
    n_h = len(heuristics)
    fig, axes = plt.subplots(n_h, 3, figsize=(13, 4.5 * n_h), sharey=True, squeeze=False)

    for row, h in enumerate(heuristics):
        for col, mode in enumerate(MODES):
            ax   = axes[row][col]
            data = agg[h][mode]
            fracs     = sorted(data.keys())
            delivered = [data[f]["mean_rate"]    for f in fracs]
            transit   = [data[f]["mean_transit"] for f in fracs]
            origin    = [data[f]["mean_origin"]  for f in fracs]
            ax.stackplot(
                fracs, delivered, transit, origin,
                labels=["Delivered", "In transit", "Never moved"],
                colors=["#59a14f", "#f28e2b", "#e15759"],
                alpha=0.85,
            )
            title = MODE_LABELS[mode]
            if n_h > 1:
                title += f"\n({h})"
            ax.set_title(title, fontsize=9)
            ax.set_xlabel("Volunteer fraction", fontsize=8)
            _pct_labels(ax, "x")
            _pct_labels(ax, "y")
            ax.set_xlim(-0.02, 1.02)
            ax.set_ylim(0, 1.05)
            ax.grid(axis="y", linestyle="--", linewidth=0.5, alpha=0.5)
        axes[row][0].set_ylabel("Fraction of parcels", fontsize=9)

    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3, fontsize=9,
               bbox_to_anchor=(0.5, -0.04))
    fig.suptitle("Parcel fate at end of simulation (mean over 10 instances)", fontsize=11)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Summary table
# ---------------------------------------------------------------------------

def print_summary_table(agg: dict) -> None:
    heuristics = sorted(agg.keys())
    for h in heuristics:
        data  = agg[h]
        fracs = sorted(next(iter(data.values())).keys())

        print(f"\n=== Heuristic: {h} ===")
        header = f"{'p':>6}  " + "  ".join(f"{'rate_'+m[:3]:>10}" for m in MODES)

        print("--- Delivery rate (mean ± std) ---")
        print(header)
        for f in fracs:
            row = f"{f:>6.1f}  "
            for mode in MODES:
                d = data[mode][f]
                row += f"  {d['mean_rate']:4.1%}±{d['std_rate']:4.1%}"
            print(row)

        print("--- Mean delivery span (min, mean ± std) ---")
        print(header.replace("rate_", "span_"))
        for f in fracs:
            row = f"{f:>6.1f}  "
            for mode in MODES:
                d = data[mode][f]
                m, s = d["mean_span"], d["std_span"]
                if m is not None:
                    row += f"  {m:5.1f}±{(s or 0.0):4.1f} "
                else:
                    row += f"  {'N/A':>11}"
            print(row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse VLMD experiment results")
    parser.add_argument("--summary", type=Path, default=RESULTS_DIR / "summary.csv")
    parser.add_argument("--out-dir", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    if not args.summary.exists():
        raise SystemExit(
            f"Summary file not found: {args.summary}\n"
            "Run `uv run python run_experiment.py` first."
        )

    rows = load_summary(args.summary)
    agg  = aggregate(rows)

    print_summary_table(agg)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    plot_delivery_rate(agg, args.out_dir / "delivery_rate.png")
    plot_delivery_span(agg, args.out_dir / "delivery_span.png")
    plot_parcel_fate(agg,   args.out_dir / "parcel_fate.png")


if __name__ == "__main__":
    main()
