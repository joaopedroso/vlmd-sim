# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**vlmd-sim** — a discrete-event simulator for volunteer-based last-mile parcel delivery (VLMD) over metro networks. The research goal is to study delivery rate and delivery span (time from parcel release to delivery) as a function of the fraction of passengers acting as volunteers.

Parcels are placed in station lockers and moved toward their destination by ordinary commuters who volunteer to carry them on their regular routes. Data is based on the Porto, Portugal metro network (85 stations, 6 lines + Bx express, GTFS snapshot Feb 2025).

---

## Commands

```bash
uv sync                                              # install dependencies

uv run python main.py                                # single run (10% volunteers, hop)
uv run python main.py -p 0.05 --heuristic flow+      # 5%, flow+ heuristic
uv run python main.py --sweep                        # sweep 0–100%
uv run python main.py --locker-stats                 # also write per-station locker occupancy CSV

uv run python generate_instances.py                  # generate 10 instances (1% parcel fraction)
uv run python run_experiment.py                      # 1200-run sweep → results/experiment/summary.csv
uv run python run_experiment.py --resume             # resume interrupted sweep (append, skip done rows)
uv run python analyse.py                             # read summary.csv, print tables, save plots
uv run python analyse_loads.py                       # cross-load delivery rate comparison

uv run python debug_track.py --instance 2 --mode negative --fraction 0.1
uv run python diagnose_stuck.py --heuristic flow+ --instance 0 --mode negative

uv run python docs/make_figures.py                   # regenerate 4 publication figures from summary.csv
```

---

## Project Structure

```
SIMULATOR/
├── main.py                  # CLI entry point; single-run and sweep modes
├── run_experiment.py        # Full 1200-run experimental sweep (supports --resume)
├── generate_instances.py    # Generate reproducible instances from od_matrices.csv
├── analyse.py               # Aggregate summary.csv → tables + 4 plots
├── analyse_loads.py         # Cross-load comparison plots (delivery rate vs parcel count)
├── debug_track.py           # Trace individual parcel movements
├── diagnose_stuck.py        # Explain undelivered parcels (BUG vs STUCK vs AT-ORIGIN)
│
├── simulator/
│   ├── model.py             # Dataclasses: Station, Edge, ODEntry, Parcel, Volunteer, Event, Movement
│   ├── network.py           # Dijkstra shortest paths; BFS all-pairs hop distances; transfer detection
│   ├── loader.py            # CSV loaders; timetable index builder (multi-day aware)
│   ├── volunteers.py        # Stochastic volunteer generation from OD matrices
│   ├── scheduler.py         # Discrete-event engine + transshipment heuristic
│   └── reporter.py          # Statistics (delivery rate, same-day rate, span, locker occupancy) and CSV output
│
├── docs/
│   ├── report.tex           # Full internal report (LaTeX, two-column)
│   ├── make_figures.py      # Generate 4 publication-quality figures from summary.csv
│   ├── figures/             # Output PDFs: fig_delivery_rate, fig_sameday_rate, fig_delivery_span, fig_phase2_gain
│   └── VLMDL/               # Symlink to the ISC2 conference paper directory
│                            # (maintained separately at ~/texts/papers/...; git-ignored here)
│
└── data/
    ├── graph.csv            # Directed metro edges: from, to, travel_time_min, line (324 rows — one per edge×line)
    ├── stations.csv         # 85 stations: station_id, name
    ├── od_matrices.csv      # Hourly OD matrices: hour, origin, destination, mean, variance
    ├── timetable.csv        # GTFS timetable: trip_id, station, arrival_time (HH:MM)
    ├── parcels.csv          # 20 sample parcels for single-run mode
    └── instances/           # 10 pre-generated instances (git-ignored)
        └── instance_NN/
            ├── od_matrix.csv         # Poisson realisation (variance = 0)
            ├── parcels_uniform.csv
            ├── parcels_positive.csv
            ├── parcels_negative.csv
            └── metadata.json
```

Results written to `results/` (git-ignored).

---

## Architecture & Key Design Decisions

### Discrete-event simulation
- Heap-based priority queue. Three event types: `parcel_released`, `volunteer_at`, `end`.
- Volunteers are generated from OD matrices; each day is an **independent Poisson draw** (moved inside the day loop so sparse OD pairs have multiple chances to generate a volunteer across the week).
- Each volunteer travels their shortest-path route; departures are spread uniformly within the hour (or aligned to timetable departures when available).

### Transshipment heuristic
Volunteers interact with lockers **only at valid stations**: {origin} ∪ {destination} ∪ {inter-line interchange stations along route}. This models realistic behaviour — commuters do not detour.

Four heuristics are available, in a clean 2×2 design (distance metric × Phase-2 on/off):

| Heuristic | Distance metric | Phase-2 fallback |
|---|---|---|
| `hop` | BFS hops | none |
| `flow` | 1/OD-flow Dijkstra | none |
| `hop+` | BFS hops | 1-day wait, move to busier hub |
| `flow+` | 1/OD-flow Dijkstra | 1-day wait, move to busier hub |

**Pick-up rule (Phase 1)**: accept iff some remaining valid station is strictly closer to destination than the current locker. This guarantees monotone progress toward the destination.

**Drop-off rule**: drop at the earliest valid station no further from destination than any station ahead, or deliver directly when hops = 0.

**Phase-2 fallback** (`hop+` / `flow+`): when Phase 1 finds no strict-progress candidate, a volunteer picks up a parcel if:
1. The parcel has been waiting in its current locker for **at least 1 day (1440 min)**.
2. There is a valid station ahead with higher **combined hub attractivity**: h(s) = F^OD(s) + F^tr(s).

The 1-day wait threshold is critical: without it, the fallback fires on day 1 and displaces parcels before same-day Phase 1 volunteers can pick them up, catastrophically reducing same-day delivery rate.

Phase-2 fallback is most effective at 10–20% volunteer fractions for the negative parcel mode.

### Network
- All-pairs BFS hop distances precomputed at initialisation.
- `_station_lines` dict built at init; `is_transfer_station(station)` returns True iff station is served by >1 metro line (after Bx→B canonicalization).
- `_edge_lines: dict[tuple[str, str], set[str]]` stores the **full set** of lines serving each directed edge. This is essential for correctly identifying transfer stations on shared-trunk segments (e.g. Campanhã–Heroísmo is served by both A and B).
- `valid_stations(route)` returns {origin, destination} ∪ {is_transfer_station stations on interior of route}. With the corrected network this gives 19 genuine inter-line interchange stations as potential interaction points.
- `transfer_stations(route)` detects where commuters must change trains: stations where incoming and outgoing edge line-sets are disjoint.
- Flow-weighted Dijkstra distances precomputed once per instance (reused across fractions and heuristics).
- `precompute_station_flows(od_flows)` computes total daily (in + out) OD flow per station; called automatically by `precompute_flow_distances()`.
- `precompute_transit_flows(od_flows)` computes total OD flow transiting through each interior station on BFS shortest paths.

### B/Bx line handling (critical)
Lines B and Bx are the **same physical track**. Bx is an express service that skips some intermediate stops (e.g. Alto de Pega, São Brás). Without canonicalization, network.py would see B and Bx as different lines and incorrectly label stations like Campanhã, Trindade, and Bolhão as single-line stations.

Fix applied in two places:
1. **`network.py`**: `_LINE_ALIASES = {"Bx": "B"}`. All Bx edges are stored as B in `_station_lines` and `_edge_lines`.
2. **`PORTO_METRO/export_simulator_data.py`**: graph.csv now keeps **all distinct lines** per edge (one row per edge×line), not just the most frequent. This means shared-trunk edges carry their full line set (e.g. both A and B for the Campanhã–Senhora da Hora segment).

Result: graph.csv grew from ~180 rows to 324 rows; 19 genuine inter-line interchange stations are correctly identified (was incorrectly 5 before the fix).

### Locker occupancy statistics
The scheduler tracks every parcel's entry and exit time at each locker via `_locker_history` (list of `(station_id, parcel_id, enter_time, exit_time)`) and `_locker_since` (most recent entry time per parcel). `get_locker_history(end_time)` closes open stays at `end_time`.

`reporter.compute_locker_stats()` uses a sweep-line algorithm over events to compute:
- **peak_occupancy**: maximum concurrent parcels at a station during the simulation.
- **mean_occupancy**: time-weighted average concurrent occupancy.
- **total_parcels**: distinct parcels that passed through the station.

Enabled by `--locker-stats`; writes `results/locker_stats_p<X>.csv`.

---

## Experiment Design

```
10 instances × 3 parcel modes × 10 volunteer fractions × 4 heuristics = 1200 runs
```

**Instances**: 10 independent Poisson realisations of the base OD matrix. Each instance generates three parcel sets of size `round(total_trips × 0.01)` (~1,950 parcels per instance).

**Parcel release times**: drawn uniformly between 07:00 and 19:00 on the first simulation day.

**Parcel modes**:
- `uniform` — OD pairs drawn uniformly over all ordered station pairs.
- `positive` — proportional to passenger flow (easy: parcels go where volunteers go).
- `negative` — inversely proportional to passenger flow (hard / worst case).

**Volunteer fractions**: 0.1%, 0.2%, 0.5%, 1%, 2%, 5%, 10%, 20%, 50%, 100% (log-spaced).

**Heuristics**: `hop`, `flow`, `hop+`, `flow+`.

**Common-random-numbers design**: seed = `1000*(instance+1) + 100*mode_index`. Same seed for all fractions and heuristics within a (instance, mode) pair. Volunteers at fraction `p` are a strict subset of those at `p' > p`.

**Output metrics** (per run, written to `summary.csv`):
- `n_total`, `n_delivered`, `n_in_transit`, `n_at_origin`, `n_same_day`
- `delivery_rate`, `same_day_rate`
- `mean_span_min`, `median_span_min`, `stdev_span_min`, `min_span_min`, `max_span_min`

**Publication figures** (written to `docs/figures/` by `docs/make_figures.py`):
- `fig_delivery_rate.pdf`, `fig_sameday_rate.pdf`, `fig_delivery_span.pdf`, `fig_phase2_gain.pdf`
- All x-axes use log scale (volunteer fraction shown as %).
- Line style encoding: solid = flow variants, dashed = hop variants; line weight = Phase-2 on/off.

---

## Key Findings

### Delivery rate vs volunteer fraction (corrected network, 1200 runs)

| Fraction | hop (pos/uni/neg) | flow+ (pos/uni/neg) |
|---|---|---|
| 10% | 59.4 / 97.8 / 39.9 | 64.3 / 98.1 / 45.1 |
| 20% | 99.4 / 100.0 / 99.1 | 100.0 / 100.0 / 100.0 |

- With **positive** correlation, ~5% participation → ~89% delivery rate; ~10% → ~98%.
- With **uniform** parcels, ~10% participation → ~98%; ~20% → ~100%.
- With **negative** correlation (worst case), ~20% participation → ~99–100% with `hop+`/`flow+`.
- `flow+` is the best heuristic overall; at 10% negative mode, it outperforms `hop` by ~5 percentage points.
- Flow metric alone (`flow` vs `hop`) contributes ~2–3 pp; Phase-2 alone (`hop+` vs `hop`) contributes ~1–2 pp.

### Same-day delivery rate
- Same-day rate is substantially lower than overall delivery rate at all fractions.
- At 10% volunteers: hop 28.3 / 89.6 / 11.7 % (pos/uni/neg); flow 30.1 / 90.0 / 13.9 %.
- Even at 100% volunteers, some parcels require more than one day.
- Phase-2 heuristics (`hop+`, `flow+`) do **not** improve same-day rate — by design, Phase-2 only fires after a 1-day wait.

### Delivery span
- Mean span drops sharply between 10% and 20% participation and flattens beyond 50%.
- At 20% volunteers (negative mode): `flow+` achieves mean 547 min / max 912 min; `hop` achieves 591 / 1001.
- `flow+` consistently achieves shorter spans than `hop` at all fractions.

### Delivery rate vs parcel load
- Delivery rate is approximately **independent of parcel load** across modes and fractions. The binding constraint is volunteer route coverage (can relay chains reach the destination?), not throughput. The 7-day window drains any queue at bottleneck stations.

### Failure mode analysis
Undelivered parcels split into two categories:
- **At-origin** (never picked up): the dominant failure mode. Root cause: no volunteer route covers the parcel's origin → destination relay chain. Common sub-causes:
  - No volunteer ever visits the station (`no_volunteer_ever_at_station`)
  - Volunteer routes all end at the stuck station (`route_ends_at_stuck_station`)
  - No onward valid station improves distance (`no_volunteer_route_improves_distance`)
- **In-transit** (stranded mid-route): relay chain broke, typically at branch-end stations.

### Branch-end traps
Some stations are structural bottlenecks because they sit at the end of a branch with highly directional volunteer flow:
- **Alto de Pega** and **São Brás**: served only by line B (local stops skipped by Bx express). Very few volunteers travel outbound to these stations; parcels destined for them accumulate in the network.
- **Póvoa de Varzim**: true terminus of line B. Volunteer flow is city-inbound; outbound deliveries rarely complete.
- **Vila do Conde**: the last inter-line interchange (B/Bx junction) before the branch stubs above. Phase 2 successfully moves parcels *toward* Vila do Conde from the city, but the final outbound segment to Alto de Pega, São Brás, or Póvoa de Varzim has insufficient volunteer coverage. This is a network topology limitation, not addressable by heuristic changes alone.

Note: locker capacity statistics from the previous (pre-fix) model are stale and should not be cited. Re-run with `--locker-stats` after the network correction to obtain current figures.

---

## Data Pipeline (PORTO_METRO → SIMULATOR)

Managed separately in `../PORTO_METRO/`:

```
DATA/ (GTFS, Feb 2025)
  read_gtfs.py            → metro_porto_travel_times.csv
  generate_od_matrix.py   → synthetic_hourly_od_matrix.csv
  export_simulator_data.py → SIMULATOR/data/*.csv
```

### OD matrix generation (`generate_od_matrix.py`)
- Uses OpenStreetMap via `osmnx`.
- **Production** (trip origins): residential/apartment/house buildings within 1000 m of station.
- **Attraction** (trip destinations): commercial, office, retail, university, industrial, warehouse, factory buildings and industrial/commercial/retail landuse polygons within 1000 m.
- Gravity model: `flow(i→j) = production(i) × attraction(j) / distance(i,j)^1.5`.

### OD matrix post-processing (`export_simulator_data.py`)
- **Evening reversal**: for hours 17–19, flow(i→j) = morning mean flow(j→i), applied across all pairs (including those absent from the gravity model output).
- **Floor**: ε = 0.1 trips/hour minimum for every connected pair.
- **IPF (Furness)**: doubly-constrained balancing with station-level production/attraction floors = number of train stops per station.
- **Calibration**: normalised to TARGET = 259,000 / 1.326 ≈ 195,324 OD trips/day (real Metro do Porto 2025 validations, divided by average boardings per journey computed from network topology).
- **Variance**: `variance_passengers = mean_passengers` (Poisson model).
- **Multi-line edges**: graph.csv keeps all distinct lines per (from, to) pair — one row per edge×line. This is required so that shared-trunk segments carry the correct line set for transfer-station detection.

---

## Decisions Made

| Decision | Rationale |
|---|---|
| Locker interactions only at {origin, destination, interchange stations} | Realistic: volunteers don't detour; with 19 true interchanges, this is a meaningful set |
| Valid stations use `is_transfer_station()` on route interior | More robust than per-edge line-change detection; correctly handles multi-line shared trunk |
| Bx → B canonicalization in `_LINE_ALIASES` | B and Bx are the same physical track; treating them as different lines created 12 false transfer stations |
| graph.csv: one row per edge×line | Shared-trunk edges (e.g. A+B between Campanhã and Senhora da Hora) must carry both lines to allow correct transfer detection and multi-line valid_station identification |
| Independent Poisson draw per day | Sparse OD pairs get multiple weekly chances; P(stuck all week) = p₀ⁿ instead of p₀ |
| Log-spaced volunteer fractions 0.1%–100% | Real crowdsourcing participation is 1–5%; log spacing gives resolution where behaviour changes fastest |
| Same-day delivery metric | Distinguishes parcels delivered within hours from those needing multiple days |
| Parcel fraction = 1% of total trips | Starting point; likely above system capacity at realistic volunteer rates |
| ε = 0.1 floor + IPF + target normalisation | Prevents terminal-station trap while keeping total volume calibrated to real data |
| Industrial tags + 1000 m radius in OSM query | Industrial zones (e.g. Zona Industrial) are pure employment centres far from stations; gravity model severely underestimated their outbound flow without this fix |
| Phase-2 requires 1-day wait before firing | Without this threshold, Phase 2 displaces parcels before same-day Phase 1 volunteers arrive, catastrophically reducing same-day delivery rate |
| 4 heuristics (hop, flow, hop+, flow+) | Clean 2×2 design: distance metric (hop vs flow) × Phase-2 (on vs off) |
| Phase-2 hub attractivity = OD flow + transit flow | Transit flow (passengers passing through as intermediate) adds robustness; empirically the combined metric selects the same hubs as OD-only |
| ++/+++ crossing variants tested and retired | hop++/flow++ (transit+time-of-day) and hop+++/flow+++ (transit+1-day) were evaluated; `+++`≈`+` in all metrics; `++` pays −7 pp same-day penalty. Threshold dominates; variants removed from standard experiment |
| Anti-cycling safeguard deferred | Cycling (Phase 2 bouncing a parcel between hubs) was analytically possible but not observed empirically at 1440 min threshold |

---

## What Is Pending / Should Be Tackled Next

### Locker capacity re-analysis
- The locker statistics from before the B/Bx and multi-line edge fix are stale. Re-run with `--locker-stats` for the corrected network to obtain valid peak and mean occupancy figures.
- Consider adding locker capacity plots: peak occupancy vs volunteer fraction per station.

### Capacity analysis at lower parcel loads
- **Re-run experiment with parcel_fraction = 0.1%** (~195 parcels/instance). Delivery rate is approximately independent of load, but delivery *span* and same-day rate may differ. Comparing 0.1% and 1% in a single plot (`analyse_loads.py`) will reveal whether span is volunteer-constrained or topology-constrained.
- Update `analyse_loads.py` to support `hop+`/`flow+` in addition to `hop`/`flow`.

### Timetable integration
- `load_timetable()` and the timetable index are built and passed to the volunteer generator, which already uses train departure times when available. However, the scheduler still uses a fixed `--leg-time` for travel between stations (default 3 min). Replacing this with actual arc travel times from `graph.csv` would improve realism.

### Analysis improvements
- Median/percentile span plots (current plots show mean, which is sensitive to outliers at low fractions).
- Locker capacity plots: peak occupancy vs volunteer fraction per station, to support infrastructure planning.

### Model improvements
- **Acceptance probability**: currently, every volunteer accepts every eligible parcel. A separate parameter `q` (probability of accepting a specific parcel given eligibility) would disentangle participation rate from per-parcel acceptance behaviour.
- Volunteer routes are always shortest paths; probabilistic or empirical route choice would add realism.
- Parcel priority or time-window constraints are not modelled.
- Look-ahead or optimisation-based heuristic (vs current greedy myopic approach).
- Anti-cycling safeguard for Phase 2 (currently deferred pending empirical evaluation).

### Validation and testing
- No unit or integration tests exist.
- Priority targets: `network.py` (shortest path, BFS, transfer detection — especially with multi-line edges) and `scheduler.py` (delivery in simple hand-crafted topologies).

### OD matrix improvements
- Station-level boarding/alighting data from Metro do Porto (if accessible) would replace synthetic gravity-model marginals with real observations.
- Employment data from INE census grids would improve production/attraction estimates.

---

## Conference paper (ISC2 2026)

The experimental work is written up as a conference paper. The paper sources
live in a separate location on the author's machine and are reached from this
repo via a symlink at `docs/VLMDL/` (git-ignored). Contents of the paper
directory:

- `vlmdl.tex` — original submission (co-authored with Ana Viana, INESC TEC / ISEP).
- `vlmdl_r1.tex` — R1 revision prepared in response to reviewer comments. The paper is 6 pages (IEEE conference, two-column).
- `vlmdl.bib` — bibliography.
- `figures/` — local copy of the figures referenced by the paper (must be kept in sync with the simulator repo's `docs/figures/`).
- `prepare_metro_figure.py` — standalone script to produce the Metro do Porto network map figure.
- `isc2-report_*.txt` — anonymous reviewer comments (confidential; not in any public repo).
- `letter_to_editor.*` — response-to-reviewers letter (confidential; not in any public repo).

### R1 revision highlights

Reviewer-driven changes applied in `vlmdl_r1.tex`:

- **Realistic participation framing**: added paragraphs distinguishing stated-preference willingness (high in surveys) from observed per-trip participation in field pilots (much lower). The specific "1--5%" figure was dropped as unsupported.
- **New primary reference**: `fessler2023` (Fessler, Cash, Thorhauge, Haustein — *Transport Policy* 134, 106--118, 2023) for the Denmark public-transport crowdshipping field trial. Replaces the weaker Archetti/Sampaio citations as the empirical anchor for sparse participation.
- **Clearance vs. customer service**: Conclusion now explicitly separates eventual network clearance (7-day delivery rate, complement = overdue rate under a one-week service promise) from acceptable customer service (same-day rate, span statistics).
- **Model-limitation caveats**: added paragraphs on the gravity-model synthetic OD, idealized volunteer acceptance (every eligible volunteer accepts every eligible parcel), and locker-capacity expected first-order effect (delaying transfers rather than changing deliverability).
- **Travel-time disclosure**: in-vehicle travel is approximated by a fixed 3-minute leg time (only volunteer departures are timetable-aligned). Stated in Section IV-C alongside the span discussion.
- **Compactness** (Reviewer 3): removed the standalone same-day-rate table (same information already in Fig. 2b), removed the duplicate all-heuristics table at $p=10\%,20\%$ (folded inline), dropped $p=0.1\%$ and $p=50\%$ rows from the remaining tables. Removed Dijkstra and Furness citations (background algorithms).
- **References fix** (Reviewer 4): the Metro do Porto press release is now in standard form (English title, press-release note, publisher URL, access date).
- **Figure 2**: panel labels (Uniform / Positive / Negative) now sit inside the axes top-left; heuristic legend moved to center-left of the top panel.
- **Highlighting macro**: `\rev{...}` colored additions in blue during the revision. In the final version the macro reduces to identity so the submitted PDF is uniform black.

### Fitting 6 pages

Several deliberate tightening moves keep the revised paper at 6 pages:
- Network map at `.55\linewidth` to absorb the extra `fessler2023` reference and the added revision paragraphs.
- Acknowledgements wrapped in `{\scriptsize ...\par}`.
- Bibliography wrapped in `{\scriptsize ...\par}`.
- Metro do Porto references use short `metrodoporto.pt/` URL with inline "accessed" note.

### What is deferred

The response letter (`letter_to_editor.tex`) itemizes requests that could not fit in six pages:
- Explicit locker capacity constraints and per-station sizing.
- Per-volunteer acceptance probability `q<1` as a separate parameter.
- Delivery-time percentiles beyond median; formal overdue-rate curves at various service promises.
- Station-level performance tables and volunteer workload distributions.
- Multi-objective front combining delivery rate and delay.
- Validation against observed Metro do Porto passenger flows.
- Benchmarking against Wyrowski et al.'s exact formulation and additional rule-based baselines.

All deferred items are also listed as future work (i)--(viii) in Section V of the revised paper.

### Pending

- The `--rev` highlighting macro was already toggled to identity, implying the paper is close to a clean camera-ready. Final check that no stray `\rev{...}` wrapping remains after acceptance.
- Confirm that `docs/VLMDL/figures/` is in sync with `docs/figures/`: `make_figures.py` writes to the latter; the paper reads from the former. A one-line `cp -f` after each regeneration is required, or the paper's `\includegraphics` paths should be re-pointed to `../figures/`.
