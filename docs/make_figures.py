"""
Generate publication-quality figures for the VLMD report.

Output (written to docs/figures/):
  fig_delivery_rate.pdf   — delivery rate vs volunteer fraction (3 panels)
  fig_delivery_span.pdf   — mean delivery span vs fraction (3 panels)
  fig_sameday_rate.pdf    — same-day delivery rate vs fraction (3 panels)
  fig_phase2_gain.pdf     — Phase-2 delivery-rate gain vs fraction (negative mode)

All figures are sized for a single column of a two-column paper (3.5 in wide).

Usage
-----
  uv run python docs/make_figures.py
  uv run python docs/make_figures.py --summary results/experiment/summary.csv
"""

from __future__ import annotations
import argparse
import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import matplotlib.lines as mlines

# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------
COL_W   = 3.5          # single-column width in inches
ROW_H   = 1.55         # height per panel row
MARGIN  = 0.22         # extra vertical margin multiplier

MODES        = ("uniform", "positive", "negative")
MODE_LABELS  = {"uniform": "Uniform", "positive": "Positive", "negative": "Negative"}
HEURISTICS   = ("hop", "flow", "hop+", "flow+")
FRACTIONS    = [0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]

# Visual encoding:
#   line style  → distance metric (dashed = hop, solid = flow)
#   line weight → Phase-2 (thin = no fallback, thick = with fallback)
#   colour      → Phase-2 family (grey family = base, colour family = +)
STYLE = {
    "hop":   dict(color="#555555", linestyle="--", linewidth=1.1, alpha=0.85),
    "flow":  dict(color="#4e79a7", linestyle="-",  linewidth=1.1, alpha=0.85),
    "hop+":  dict(color="#e15759", linestyle="--", linewidth=1.9, alpha=0.90),
    "flow+": dict(color="#f28e2b", linestyle="-",  linewidth=1.9, alpha=0.95),
}

LABEL = {
    "hop":   r"\texttt{hop}",
    "flow":  r"\texttt{flow}",
    "hop+":  r"\texttt{hop+}",
    "flow+": r"\texttt{flow+}",
}

# ---------------------------------------------------------------------------
# Matplotlib global style
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family":       "serif",
    "font.size":         8,
    "axes.labelsize":    8,
    "axes.titlesize":    8.5,
    "xtick.labelsize":   7,
    "ytick.labelsize":   7,
    "legend.fontsize":   7,
    "legend.framealpha": 0.85,
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "lines.markersize":  3,
    "figure.dpi":        150,
    "savefig.dpi":       300,
    "savefig.bbox":      "tight",
    "text.usetex":       False,   # set True if LaTeX is desired for labels
})


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_summary(path: Path) -> dict:
    """Return nested dict: data[heuristic][mode][fraction] = {metric: [values]}."""
    data: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(list))))
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            h   = row["heuristic"]
            m   = row["parcel_mode"]
            p   = float(row["volunteer_fraction"])
            if h not in HEURISTICS:
                continue
            for metric in ("delivery_rate", "same_day_rate", "mean_span_min"):
                v = row.get(metric, "")
                if v:
                    data[h][m][p][metric].append(float(v))
    return data


def mean_std(values: list[float]) -> tuple[float, float]:
    if not values:
        return float("nan"), float("nan")
    mu = statistics.mean(values)
    sd = statistics.pstdev(values) if len(values) > 1 else 0.0
    return mu, sd


def series(data, heuristic: str, mode: str, metric: str):
    """Return (x_pct, y_mean, y_std) arrays for the given heuristic/mode/metric."""
    xs, ys, es = [], [], []
    for p in FRACTIONS:
        vals = data[heuristic][mode][p][metric]
        if vals:
            mu, sd = mean_std(vals)
            if not math.isnan(mu):
                xs.append(p * 100)
                ys.append(mu)
                es.append(sd)
    return xs, ys, es


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def log_x_axis(ax, minor=True):
    ax.set_xscale("log")
    ax.set_xlim(0.08, 120)
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(
        lambda v, _: f"{v:g}%"
    ))
    ax.xaxis.set_major_locator(mticker.LogLocator(base=10, numticks=6))
    if minor:
        ax.xaxis.set_minor_locator(mticker.LogLocator(base=10, subs=[2, 5], numticks=12))
        ax.xaxis.set_minor_formatter(mticker.NullFormatter())
    ax.tick_params(axis="x", which="minor", length=2)


def panel_label(ax, letter: str, title: str):
    ax.set_title(f"({letter}) {title}", loc="left", fontsize=8, pad=3)


def heuristic_legend(ax, loc="lower right", ncol=2):
    handles = [
        mlines.Line2D([], [], label=f"{'hop':6s}", **STYLE["hop"]),
        mlines.Line2D([], [], label=f"{'flow':6s}", **STYLE["flow"]),
        mlines.Line2D([], [], label=f"{'hop+':6s}", **STYLE["hop+"]),
        mlines.Line2D([], [], label=f"{'flow+':6s}", **STYLE["flow+"]),
    ]
    ax.legend(handles=handles, loc=loc, ncol=ncol,
              handlelength=1.8, columnspacing=0.8, handletextpad=0.4)


# ---------------------------------------------------------------------------
# Figure 1: Delivery rate
# ---------------------------------------------------------------------------

def fig_delivery_rate(data: dict, out: Path) -> None:
    letters = ("a", "b", "c")
    fig, axes = plt.subplots(3, 1, figsize=(COL_W, 3 * ROW_H + MARGIN),
                             sharex=True)
    for ax, mode, letter in zip(axes, MODES, letters):
        for h in HEURISTICS:
            xs, ys, _ = series(data, h, mode, "delivery_rate")
            ys_pct = [v * 100 for v in ys]
            ax.plot(xs, ys_pct, **STYLE[h])
        ax.set_ylim(-3, 103)
        ax.set_ylabel("Delivery rate (%)")
        ax.yaxis.set_major_locator(mticker.MultipleLocator(25))
        ax.axhline(100, color="0.75", lw=0.5, ls=":")
        panel_label(ax, letter, MODE_LABELS[mode])
        log_x_axis(ax)

    axes[-1].set_xlabel("Volunteer fraction")
    heuristic_legend(axes[0], loc="upper left", ncol=2)
    fig.tight_layout(h_pad=0.6)
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Figure 2: Delivery span
# ---------------------------------------------------------------------------

def fig_delivery_span(data: dict, out: Path) -> None:
    letters = ("a", "b", "c")
    fig, axes = plt.subplots(3, 1, figsize=(COL_W, 3 * ROW_H + MARGIN),
                             sharex=True)
    for ax, mode, letter in zip(axes, MODES, letters):
        has_data = False
        for h in HEURISTICS:
            xs, ys, _ = series(data, h, mode, "mean_span_min")
            if xs:
                ax.plot(xs, ys, **STYLE[h])
                has_data = True
        ax.set_yscale("log")
        ax.set_ylabel("Mean span (min)")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}"))
        ax.yaxis.set_minor_formatter(mticker.NullFormatter())
        panel_label(ax, letter, MODE_LABELS[mode])
        log_x_axis(ax)

    axes[-1].set_xlabel("Volunteer fraction")
    heuristic_legend(axes[0], loc="upper right", ncol=2)
    fig.tight_layout(h_pad=0.6)
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Figure 3: Same-day delivery rate
# ---------------------------------------------------------------------------

def fig_sameday_rate(data: dict, out: Path) -> None:
    letters = ("a", "b", "c")
    fig, axes = plt.subplots(3, 1, figsize=(COL_W, 3 * ROW_H + MARGIN),
                             sharex=True)
    # hop≡hop+ and flow≡flow+ for same-day, so show only 2 lines but label
    # them to match the full heuristic table.
    shown = ("hop", "flow")
    for ax, mode, letter in zip(axes, MODES, letters):
        for h in shown:
            xs, ys, _ = series(data, h, mode, "same_day_rate")
            ys_pct = [v * 100 for v in ys]
            ax.plot(xs, ys_pct, label=h, **STYLE[h])
        ax.set_ylim(-3, 103)
        ax.set_ylabel("Same-day rate (%)")
        ax.yaxis.set_major_locator(mticker.MultipleLocator(25))
        ax.axhline(100, color="0.75", lw=0.5, ls=":")
        panel_label(ax, letter, MODE_LABELS[mode])
        log_x_axis(ax)

    axes[-1].set_xlabel("Volunteer fraction")
    # Custom legend noting that + variants are identical
    handles = [
        mlines.Line2D([], [], label="hop  (= hop+)",  **STYLE["hop"]),
        mlines.Line2D([], [], label="flow (= flow+)", **STYLE["flow"]),
    ]
    axes[0].legend(handles=handles, loc="upper left",
                   handlelength=1.8, handletextpad=0.4)
    fig.tight_layout(h_pad=0.6)
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Figure 4: Phase-2 gain (negative mode, delivery rate)
# ---------------------------------------------------------------------------

def fig_phase2_gain(data: dict, out: Path) -> None:
    """Δdelivery rate from Phase-2, for both metrics, all three modes."""
    fig, axes = plt.subplots(3, 1, figsize=(COL_W, 3 * ROW_H + MARGIN),
                             sharex=True)
    letters = ("a", "b", "c")

    hop_style  = dict(color=STYLE["hop+"]["color"],   linestyle="--",
                      linewidth=1.6, alpha=0.90)
    flow_style = dict(color=STYLE["flow+"]["color"],  linestyle="-",
                      linewidth=1.6, alpha=0.95)

    for ax, mode, letter in zip(axes, MODES, letters):
        # Δ = (hop+ rate) − (hop rate) and (flow+ rate) − (flow rate)
        for (base, plus), sty, label in [
            (("hop",  "hop+"),  hop_style,  "hop+ − hop"),
            (("flow", "flow+"), flow_style, "flow+ − flow"),
        ]:
            base_d = {p: statistics.mean(data[base][mode][p]["delivery_rate"])
                      for p in FRACTIONS
                      if data[base][mode][p]["delivery_rate"]}
            plus_d = {p: statistics.mean(data[plus][mode][p]["delivery_rate"])
                      for p in FRACTIONS
                      if data[plus][mode][p]["delivery_rate"]}
            ps = sorted(set(base_d) & set(plus_d))
            xs = [p * 100 for p in ps]
            ys = [(plus_d[p] - base_d[p]) * 100 for p in ps]
            ax.plot(xs, ys, label=label, **sty)

        ax.axhline(0, color="0.6", lw=0.6, ls=":")
        ax.set_ylabel("Δ Delivery rate (pp)")   # Δ
        panel_label(ax, letter, MODE_LABELS[mode])
        log_x_axis(ax)

    axes[-1].set_xlabel("Volunteer fraction")
    axes[0].legend(loc="upper right", handlelength=1.8, handletextpad=0.4)
    fig.tight_layout(h_pad=0.6)
    fig.savefig(out)
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=Path,
                        default=Path(__file__).parent.parent /
                                "results" / "experiment" / "summary.csv")
    parser.add_argument("--out-dir", type=Path,
                        default=Path(__file__).parent / "figures")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    data = load_summary(args.summary)

    fig_delivery_rate(data, args.out_dir / "fig_delivery_rate.pdf")
    fig_delivery_span(data, args.out_dir / "fig_delivery_span.pdf")
    fig_sameday_rate(data,  args.out_dir / "fig_sameday_rate.pdf")
    fig_phase2_gain(data,   args.out_dir / "fig_phase2_gain.pdf")


if __name__ == "__main__":
    main()
