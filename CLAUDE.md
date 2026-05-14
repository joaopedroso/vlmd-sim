# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**vlmd-sim** — a discrete-event simulator for volunteer-based last-mile parcel delivery (VLMD) over metro networks. The research goal is to study delivery rate and delivery span (time from parcel release to delivery) as a function of the fraction of passengers acting as volunteers.

Parcels are placed in station lockers and moved toward their destination by ordinary commuters who volunteer to carry them on their regular routes. Data is based on the Porto, Portugal metro network (85 stations, 6 lines, GTFS snapshot Feb 2025).

---

## Commands

```bash
uv sync                                         # install dependencies

uv run python main.py                           # single run (10% volunteers)
uv run python main.py -p 0.05 --heuristic flow  # 5%, flow heuristic
uv run python main.py --sweep                   # sweep 0–100%

uv run python generate_instances.py             # generate 10 instances (1% parcel fraction)
uv run python run_experiment.py                 # 600-run sweep → results/experiment/summary.csv
uv run python analyse.py                        # read summary.csv, print tables, save plots

uv run python debug_track.py --instance 2 --mode negative --fraction 0.1
uv run python diagnose_stuck.py
```

---

## Project Structure

```
SIMULATOR/
├── main.py                  # CLI entry point; single-run and sweep modes
├── run_experiment.py        # Full 600-run experimental sweep
├── generate_instances.py    # Generate reproducible instances from od_matrices.csv
├── analyse.py               # Aggregate summary.csv → tables + 4 plots
├── debug_track.py           # Trace individual parcel movements
├── diagnose_stuck.py        # Explain undelivered parcels (BUG vs STUCK vs AT-ORIGIN)
│
├── simulator/
│   ├── model.py             # Dataclasses: Station, Edge, ODEntry, Parcel, Volunteer, Event, Movement
│   ├── network.py           # Dijkstra shortest paths; BFS all-pairs hop distances; transfer detection
│   ├── loader.py            # CSV loaders; timetable index builder (multi-day aware)
│   ├── volunteers.py        # Stochastic volunteer generation from OD matrices
│   ├── scheduler.py         # Discrete-event engine + transshipment heuristic
│   └── reporter.py          # Statistics (delivery rate, same-day rate, span) and CSV output
│
└── data/
    ├── graph.csv            # Directed metro edges: from, to, travel_time_min, line
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
Volunteers interact with lockers **only at valid stations**: {origin} ∪ {destination} ∪ {line-transfer stations along route}. This models realistic behaviour — commuters do not detour.

Two heuristics are implemented:
- **hop** (baseline): pick-up/drop-off by unweighted BFS hop distance.
- **flow**: arc weights = `1 / daily_OD_flow(A→B)`; favours high-traffic corridors.

**Pick-up rule**: accept iff some remaining valid station is strictly closer to destination than the current locker.

**Drop-off rule**: drop at the earliest valid station no further from destination than any station ahead, or deliver directly when hops = 0. Parcels monotonically approach their destination.

### Network
- All-pairs BFS hop distances precomputed at initialisation.
- `transfer_stations(route)` detects where the metro line changes.
- `valid_stations(route)` returns the frozenset of permitted locker-interaction stations.
- Flow-weighted Dijkstra distances precomputed once per instance (reused across fractions and heuristics).

---

## Experiment Design

```
10 instances × 3 parcel modes × 10 volunteer fractions × 2 heuristics = 600 runs
```

**Instances**: 10 independent Poisson realisations of the base OD matrix. Each instance generates three parcel sets of size `round(total_trips × parcel_fraction)`.

**Parcel modes**:
- `uniform` — OD pairs drawn uniformly over all ordered station pairs.
- `positive` — proportional to passenger flow (easy: parcels go where volunteers go).
- `negative` — inversely proportional to passenger flow (hard / worst case).

**Volunteer fractions**: 0.1%, 0.2%, 0.5%, 1%, 2%, 5%, 10%, 20%, 50%, 100% (log-spaced).

**Common-random-numbers design**: seed = `1000*(instance+1) + 100*mode_index`. Same seed for all fractions and heuristics within a (instance, mode) pair. Volunteers at fraction `p` are a strict subset of those at `p' > p`.

**Output metrics** (per run, written to `summary.csv`):
- `n_total`, `n_delivered`, `n_in_transit`, `n_at_origin`, `n_same_day`
- `delivery_rate`, `same_day_rate`
- `mean_span_min`, `median_span_min`, `stdev_span_min`, `min_span_min`, `max_span_min`

**Plots** (written to `results/experiment/`):
- `delivery_rate.png`, `same_day_rate.png`, `delivery_span.png`, `parcel_fate.png`
- All x-axes use log scale (volunteer fraction shown as %).

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

---

## Decisions Made

| Decision | Rationale |
|---|---|
| Locker interactions only at {origin, destination, transfers} | Realistic: volunteers don't detour |
| Independent Poisson draw per day | Sparse OD pairs get multiple weekly chances; P(stuck all week) = p₀ⁿ instead of p₀ |
| Log-spaced volunteer fractions 0.1%–100% | Real crowdsourcing participation is 1–5%; log spacing gives resolution where behaviour changes fastest |
| Same-day delivery metric | Distinguishes parcels delivered within hours from those needing multiple days |
| Parcel fraction = 1% of total trips | Starting point; likely above system capacity at realistic volunteer rates |
| ε = 0.1 floor + IPF + target normalisation | Prevents terminal-station trap while keeping total volume calibrated to real data |
| Industrial tags + 1000 m radius in OSM query | Industrial zones (e.g. Zona Industrial) are pure employment centres far from stations; gravity model severely underestimated their outbound flow without this fix |

---

## What Is Pending / Should Be Tackled Next

### Immediate: capacity analysis
- **Re-run experiment with parcel_fraction = 0.1%** (~195 parcels/instance). At 1%, most fractions below 10% deliver very few parcels; a lower parcel load will reveal where the system transitions from capacity-constrained to volunteer-constrained. Analyse delivery rate and span as a function of parcel volume.

### Timetable integration
- `load_timetable()` and the timetable index are built and passed to the volunteer generator, which already uses train departure times when available. However, the scheduler still uses a fixed `--leg-time` for travel between stations (default 3 min). Replacing this with actual arc travel times from `graph.csv` (or GTFS) would improve realism.

### Analysis improvements
- Compare results across parcel fractions (0.1% vs 1%) in a single plot to visualise capacity.
- Median/percentile span plots (current plots show mean ± std, which is sensitive to outliers at low fractions).

### Model improvements
- Volunteer routes are always shortest paths; probabilistic or empirical route choice would add realism.
- Parcel priority or time-window constraints are not modelled.
- Look-ahead or optimisation-based heuristic (vs current greedy myopic approach).

### Validation and testing
- No unit or integration tests exist.
- Priority targets: `network.py` (shortest path, BFS, transfer detection) and `scheduler.py` (delivery in simple hand-crafted topologies).

### OD matrix improvements
- Station-level boarding/alighting data from Metro do Porto (if accessible) would replace synthetic gravity-model marginals with real observations.
- Employment data from INE census grids would improve production/attraction estimates.
