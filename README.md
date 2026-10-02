# vlmd-sim

Discrete-event simulator for **Volunteer-based Last-Mile Delivery (VLMD)** over urban metro networks.

Parcels are placed in station lockers and carried toward their destination by ordinary commuters who volunteer to transport them on their regular daily trips. The simulator studies how delivery rate and delivery span vary as a function of the fraction of passengers acting as volunteers.

The network and passenger data are based on the **Porto Metro** (Portugal), using real GTFS timetables and a gravity-model OD matrix calibrated to ~259,000 daily validations (2025).

The experimental work is written up in a conference paper (ISC2 2026, co-authored with A. Viana — see the Citation section below). Paper sources are maintained in a separate location.

---

## Research questions

- What volunteer participation rate is needed to achieve a target delivery rate?
- How does delivery span (time from parcel release to delivery) decrease as participation grows?
- How do parcel OD characteristics (uniform / positively / negatively correlated with passenger flow) affect outcomes?
- Do routing heuristics based on passenger flow outperform hop-count heuristics?
- What locker capacity is needed at each station to support a given delivery rate?

---

## Installation

The project uses [uv](https://github.com/astral-sh/uv) for dependency management. Python 3.12+ required.

```bash
cd SIMULATOR
uv sync
```

---

## Quick start

```bash
# Single run — 10% volunteer fraction, default settings
uv run python main.py

# Specific fraction and heuristic
uv run python main.py --volunteer-fraction 0.05 --heuristic flow+

# Single run with locker occupancy statistics
uv run python main.py -p 0.1 --locker-stats

# Full experiment sweep (10 instances × 3 parcel modes × 10 fractions × 4 heuristics = 1200 runs)
uv run python run_experiment.py

# Analyse results and produce plots
uv run python analyse.py

# Regenerate publication figures
uv run python docs/make_figures.py
```

---

## Project structure

```
SIMULATOR/
├── main.py                  # CLI entry point (single run or sweep)
├── run_experiment.py        # Full experimental sweep → results/experiment/summary.csv
├── generate_instances.py    # Generate 10 reproducible instances from od_matrices.csv
├── analyse.py               # Read summary.csv, print tables, save plots
├── analyse_loads.py         # Cross-load delivery rate comparison plots
├── debug_track.py           # Trace individual parcel movements for debugging
├── diagnose_stuck.py        # Identify and explain undelivered parcels
│
├── simulator/
│   ├── model.py             # Dataclasses: Station, Edge, ODEntry, Parcel, Volunteer, Event, Movement
│   ├── network.py           # Graph: Dijkstra shortest paths, BFS hop distances, transfer detection
│   ├── loader.py            # CSV loaders; timetable index builder
│   ├── volunteers.py        # Stochastic volunteer generation from OD matrices
│   ├── scheduler.py         # Discrete-event engine + transshipment heuristic
│   └── reporter.py          # Statistics (delivery rate, span, same-day rate, locker occupancy) and CSV output
│
├── docs/
│   ├── report.tex           # Internal technical report (LaTeX, two-column)
│   ├── make_figures.py      # Generate 4 publication figures from summary.csv
│   └── figures/             # fig_delivery_rate.pdf, fig_sameday_rate.pdf, fig_delivery_span.pdf, fig_phase2_gain.pdf
│
└── data/
    ├── graph.csv            # Directed metro edges: from, to, travel_time_min, line (324 rows — one per edge×line)
    ├── stations.csv         # Station IDs and names (85 stations)
    ├── od_matrices.csv      # Hourly OD matrices (mean + variance, Poisson model)
    ├── timetable.csv        # Full GTFS timetable (arrival time per stop per trip)
    ├── parcels.csv          # 20 sample parcels for single-run mode
    └── instances/           # 10 pre-generated instances (od_matrix.csv + parcels_*.csv)
```

Results are written to `results/` (git-ignored).

---

## Simulation model

### Volunteers

For each hourly OD entry, the number of commuters is drawn independently each day from a Poisson distribution with the entry's mean. A fraction `p` of those commuters become volunteers. Each volunteer travels their shortest-path route and may carry at most one parcel at a time.

Volunteers interact with lockers **only at valid stations**: their origin, their destination, and any inter-line interchange stations along their route. With the corrected network model (19 genuine interchange stations), this provides realistic and meaningful relay opportunities without requiring detours.

### Transshipment heuristic

Four heuristics are available, selectable with `--heuristic`:

| Heuristic | Distance metric | Phase-2 fallback |
|-----------|----------------|------------------|
| `hop`     | Unweighted BFS hop count | No |
| `flow`    | 1 / daily OD flow (Dijkstra) | No |
| `hop+`    | Unweighted BFS hop count | Yes |
| `flow+`   | 1 / daily OD flow (Dijkstra) | Yes |

**Phase 1 — pick-up rule**: a volunteer picks up a parcel only if at least one of their remaining valid stations is strictly closer to the destination than the parcel's current locker. Parcels thus monotonically approach their destination.

**Phase 1 — drop-off rule**: the volunteer drops the parcel at the earliest valid station that is no further from the destination than any station ahead on their route, or delivers directly when that station is the destination.

**Phase 2 fallback** (`hop+` / `flow+`): when Phase 1 finds no strict-progress candidate, a volunteer may still pick up a parcel if a valid station ahead has higher **combined hub attractivity** (OD flow + transit flow through the station) and the parcel has been waiting in its locker for at least 1 day. This breaks "at-origin" stagnation for parcels stranded at low-traffic stations. The 1-day wait prevents Phase 2 from displacing parcels before same-day Phase 1 volunteers arrive.

### Events

The priority queue contains three event types:
- `parcel_released` — parcel becomes available for pickup at its origin locker.
- `volunteer_at` — volunteer arrives at successive stations along their route.
- `end` — simulation terminates.

### Multi-day simulation

The simulation runs for 7 days (configurable). Each day is an independent Poisson draw for volunteer counts, so sparse OD pairs have multiple chances to generate a volunteer during the week.

### Network model

Lines B and Bx are the same physical track — Bx is an express service that skips some intermediate stops. The network correctly canonicalizes Bx → B so that shared-trunk stations (Campanhã, Trindade, Bolhão, etc.) are identified as inter-line interchanges. `graph.csv` contains one row per (from_station, to_station, line) pair (324 rows total), preserving the full line set for each directed edge.

---

## Experiment design

```
10 instances × 3 parcel modes × 10 volunteer fractions × 4 heuristics = 1200 runs
```

**Instances**: 10 independent Poisson realisations of the OD matrix; each instance has ~1,950 parcels (1% of realised trips). Parcel release times are drawn uniformly between 07:00 and 19:00 on the first simulation day.

**Parcel modes**:
- `uniform` — OD pairs drawn uniformly at random from the network.
- `positive` — OD pairs sampled proportionally to passenger flow (easy case).
- `negative` — OD pairs sampled inversely to passenger flow (hard case).

**Volunteer fractions**: 0.1%, 0.2%, 0.5%, 1%, 2%, 5%, 10%, 20%, 50%, 100% (log-spaced).

**Heuristics**: `hop`, `flow`, `hop+`, `flow+`.

**Common random numbers**: seeds depend only on (instance, mode), not on fraction or heuristic. Volunteers at fraction `p` are a strict subset of those at `p' > p`.

**Output metrics**: delivery rate, same-day delivery rate, mean/median/stdev/min/max delivery span.

---

## Key findings

### Delivery rate vs volunteer fraction

- With **positive** parcel-passenger correlation, ~5% participation achieves ~89% delivery rate; ~10% achieves ~98%.
- With **uniform** parcels, ~10% participation achieves ~98%; ~20% achieves ~100%.
- With **negative** correlation (worst case), ~20% participation achieves ~99–100% with any Phase-2 heuristic.
- `flow+` is the best overall heuristic; at 10% negative mode it outperforms `hop` by ~5 percentage points (45% vs 40%).
- The flow distance metric contributes ~2–3 pp; Phase-2 contributes ~1–2 pp; both combined give ~5 pp total gain.

### Same-day delivery rate

Same-day delivery is substantially harder than overall delivery. At 10% volunteers: hop achieves 28% / 90% / 12% (positive/uniform/negative); flow achieves 30% / 90% / 14%. Phase-2 heuristics do not improve same-day rate — by design, Phase-2 only fires after a 1-day wait.

### Delivery span

Span drops sharply between 10% and 20% participation and flattens beyond 50%. At 20% volunteers (negative mode): `flow+` achieves mean 547 min / max 912 min versus `hop`'s 591 / 1001 min.

### Delivery rate vs parcel load

Delivery rate is approximately **independent of parcel load**. The binding constraint is volunteer route topology (can relay chains reach the destination?), not throughput. The 7-day window drains any queue at bottleneck stations.

### Failure modes

- **At-origin** (never picked up): dominant failure. Root causes: no volunteer visits the origin, or all volunteers who do have no valid onward station that reduces distance.
- **In-transit** (stranded mid-route): relay chain broke. Common near branch-end stations.

### Branch-end traps

Stations at the end of low-traffic branches are structural bottlenecks:

- **Alto de Pega** and **São Brás**: served only by line B local stops (skipped by Bx express). Almost no volunteer route terminates there; outbound deliveries rarely complete.
- **Póvoa de Varzim**: true line terminus. Volunteer flow is predominantly city-inbound; parcels needing outbound delivery remain stranded.
- **Vila do Conde**: the last inter-line interchange (B/Bx junction) before the above branch stubs. Phase 2 successfully moves parcels toward Vila do Conde from the city, but the final outbound segment has insufficient volunteer coverage.

This is a network topology limitation, not addressable by heuristic changes alone.

---

## Data pipeline

The Porto Metro dataset is prepared in the companion `PORTO_METRO/` directory:

```
PORTO_METRO/DATA/  (GTFS snapshot, Feb 2025)
    │
    ├── read_gtfs.py            → metro_porto_travel_times.csv
    ├── generate_od_matrix.py   → synthetic_hourly_od_matrix.csv
    │     (OSM gravity model: residential production, employment/industrial attraction,
    │      1000 m catchment radius, calibrated to 259k daily validations)
    └── export_simulator_data.py → SIMULATOR/data/*.csv
          (IPF balancing, evening reversal fix, Poisson variance, 195k OD trips/day target,
           all lines per edge preserved for correct transfer-station identification)
```

---

## Configuration

Key parameters in `run_experiment.py` and `main.py`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--volunteer-fraction` | 0.1 | Fraction of passengers acting as volunteers |
| `--heuristic` | `hop` | Transshipment heuristic: `hop`, `flow`, `hop+`, or `flow+` |
| `--leg-time` | 3 | Fallback leg time in minutes (when timetable unavailable) |
| `--n-days` | 7 | Number of simulation days |
| `--seed` | 42 | Random seed |
| `--locker-stats` | off | Write per-station locker occupancy CSV after each run |
| `--sweep` | off | Sweep volunteer fraction 0%–100% in steps of 10% |

---

## Citation

If you use this simulator in your research, please cite:

> J.P. Pedroso and A. Viana, *A model for last-mile delivery with lockers and volunteers*, IEEE International Smart Cities Conference (ISC2), 2026.

Software repository:

> J.P. Pedroso, *vlmd-sim: A discrete-event simulator for volunteer-based last-mile delivery over metro networks*, 2026. https://github.com/joaopedroso/vlmd-sim
