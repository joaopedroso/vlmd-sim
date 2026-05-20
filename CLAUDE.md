# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Project Overview

**vlmd-sim** — a discrete-event simulator for volunteer-based last-mile parcel delivery (VLMD) over metro networks. The research goal is to study delivery rate and delivery span (time from parcel release to delivery) as a function of the fraction of passengers acting as volunteers.

Parcels are placed in station lockers and moved toward their destination by ordinary commuters who volunteer to carry them on their regular routes. Data is based on the Porto, Portugal metro network (85 stations, 6 lines, GTFS snapshot Feb 2025).

---

## Commands

```bash
uv sync                                              # install dependencies

uv run python main.py                                # single run (10% volunteers, hop)
uv run python main.py -p 0.05 --heuristic flow+      # 5%, flow+ heuristic
uv run python main.py --sweep                        # sweep 0–100%
uv run python main.py --locker-stats                 # also write per-station locker occupancy CSV

uv run python generate_instances.py                  # generate 10 instances (1% parcel fraction)
uv run python run_experiment.py                      # 2400-run sweep → results/experiment/summary.csv
uv run python run_experiment.py --resume             # resume interrupted sweep (append, skip done rows)
uv run python analyse.py                             # read summary.csv, print tables, save plots
uv run python analyse_loads.py                       # cross-load delivery rate comparison

uv run python debug_track.py --instance 2 --mode negative --fraction 0.1
uv run python diagnose_stuck.py --heuristic flow+ --instance 0 --mode negative
```

---

## Project Structure

```
SIMULATOR/
├── main.py                  # CLI entry point; single-run and sweep modes
├── run_experiment.py        # Full 2400-run experimental sweep (supports --resume)
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

Eight heuristics are implemented in a 2×2 factorial plus crossing design:

| Heuristic | Distance metric | Fallback threshold | Hub targeting |
|---|---|---|---|
| `hop` | BFS hops | none | — |
| `flow` | 1/OD-flow Dijkstra | none | — |
| `hop+` | BFS hops | 1-day wait | OD flow, any busier station |
| `flow+` | 1/OD-flow | 1-day wait | OD flow, any busier station |
| `hop++` | BFS hops | time-of-day (noon / 18:00) | transit flow, two-tier (transfer first) |
| `flow++` | 1/OD-flow | time-of-day (noon / 18:00) | transit flow, two-tier (transfer first) |
| `hop+++` | BFS hops | 1-day wait | transit flow, two-tier (transfer first) |
| `flow+++` | 1/OD-flow | 1-day wait | transit flow, two-tier (transfer first) |

`hop+++` / `flow+++` are the **crossing variants**: they combine `+`'s 1-day-wait threshold with `++`'s transit-flow + two-tier targeting. This isolates threshold vs metric/targeting effects.

**Pick-up rule (Phase 1)**: accept iff some remaining valid station is strictly closer to destination than the current locker. This guarantees monotone progress toward the destination.

**Drop-off rule**: drop at the earliest valid station no further from destination than any station ahead, or deliver directly when hops = 0.

**Phase-2 fallback** (`hop+` / `flow+` / `hop+++` / `flow+++`): when Phase 1 finds no strict-progress candidate, a volunteer picks up a parcel if:
1. The parcel has been waiting in its current locker for **at least 1 day (1440 min)**.
2. There is a valid station ahead with better hub quality (OD flow for `+`, transit flow for `+++`).

The 1-day wait threshold is critical: without it, the fallback fires on day 1 and displaces parcels before same-day Phase 1 volunteers can pick them up.

**Phase-3 fallback** (`hop++` / `flow++`): time-of-day gating instead of 1-day threshold.
- 12:00–18:00: move parcel to a **network-level transfer station** ahead with higher transit flow.
- After 18:00: move parcel to **any valid station** ahead with higher transit flow.
- Before 12:00: no fallback (Phase 1 only).

**Transit flow** (`++` / `+++` variants): computed as the total OD flow that passes through each station as an intermediate stop on BFS shortest paths. Distinct from OD flow which counts only origins/destinations. Implemented via `precompute_transit_flows(od_flows)` → `transit_flow(station)`.

Phase-2 fallback is most effective at 10–20% volunteer fractions for the negative parcel mode. For positive and uniform modes, Phase 1 already handles most parcels.

### Network
- All-pairs BFS hop distances precomputed at initialisation.
- `_station_lines` dict built at init; `is_transfer_station(station)` returns True iff station is served by >1 metro line.
- `valid_stations(route)` returns the frozenset of permitted locker-interaction stations.
- Flow-weighted Dijkstra distances precomputed once per instance (reused across fractions and heuristics).
- `precompute_station_flows(od_flows)` computes total daily (in + out) OD flow per station; called automatically by `precompute_flow_distances()`.
- `precompute_transit_flows(od_flows)` computes total OD flow transiting through each interior station; required by `++`/`+++` variants.

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
10 instances × 3 parcel modes × 10 volunteer fractions × 8 heuristics = 2400 runs
```

**Instances**: 10 independent Poisson realisations of the base OD matrix. Each instance generates three parcel sets of size `round(total_trips × parcel_fraction)`.

**Parcel modes**:
- `uniform` — OD pairs drawn uniformly over all ordered station pairs.
- `positive` — proportional to passenger flow (easy: parcels go where volunteers go).
- `negative` — inversely proportional to passenger flow (hard / worst case).

**Volunteer fractions**: 0.1%, 0.2%, 0.5%, 1%, 2%, 5%, 10%, 20%, 50%, 100% (log-spaced).

**Heuristics**: `hop`, `flow`, `hop+`, `flow+`, `hop++`, `flow++`, `hop+++`, `flow+++`.

**Common-random-numbers design**: seed = `1000*(instance+1) + 100*mode_index`. Same seed for all fractions and heuristics within a (instance, mode) pair. Volunteers at fraction `p` are a strict subset of those at `p' > p`.

**Output metrics** (per run, written to `summary.csv`):
- `n_total`, `n_delivered`, `n_in_transit`, `n_at_origin`, `n_same_day`
- `delivery_rate`, `same_day_rate`
- `mean_span_min`, `median_span_min`, `stdev_span_min`, `min_span_min`, `max_span_min`

**Plots** (written to `results/experiment/`):
- `delivery_rate.png`, `same_day_rate.png`, `delivery_span.png`, `parcel_fate.png`
- All x-axes use log scale (volunteer fraction shown as %).
- Line style encoding: solid = flow variants, dashed = hop variants; line width encodes Phase-2 strength.

---

## Key Findings

### Delivery rate vs volunteer fraction
- With **positive** correlation, ~5% participation → ~89% delivery rate; ~10% → ~99%.
- With **uniform** parcels, ~20% participation → ~100% delivery (with any Phase-2 variant).
- With **negative** correlation (worst case), ~20% participation → ~100% delivery rate with any `+` variant.
- `flow+` is the best heuristic overall; gains vs `hop` are largest for negative mode at 5–20% fractions.

### 2×2 crossing experiment: threshold vs metric/targeting
The `+++` crossing variants (transit flow + 1-day wait) isolate the two factors:

| Heuristic | @ 10% neg delivery | @ 100% same-day |
|---|---|---|
| `hop` | 38.8% | 97.9% |
| `hop+` (OD flow + 1-day) | 41.4% | 97.9% |
| `hop++` (transit + time-of-day) | 40.4% | 90.8% |
| `hop+++` (transit + 1-day) | 40.4% | 97.9% |
| `flow` | 40.9% | 97.9% |
| `flow+` (OD flow + 1-day) | 44.8% | 97.9% |
| `flow++` (transit + time-of-day) | 43.4% | 90.3% |
| `flow+++` (transit + 1-day) | 44.4% | 97.9% |

**Main conclusion**: `+++` ≈ `+` in every metric — transit flow + two-tier targeting offers no meaningful advantage over OD flow + any-busier-station when holding the threshold fixed. The **threshold** (1-day vs time-of-day) is the dominant factor. `++` gains marginally in delivery rate (~1 pp) at the cost of a severe same-day penalty (~7 pp at 100% volunteers). `++` is not recommended where same-day rate matters.

### Delivery rate vs parcel load
- Delivery rate is approximately **independent of parcel load** across modes and fractions. This is a structural property: the binding constraint is volunteer route coverage (can relay chains reach the destination?), not throughput. The 7-day window drains any queue at bottleneck stations. Delivery rate reflects P(OD pair has adequate volunteer chain coverage).

### Failure mode analysis
Undelivered parcels split into two categories:
- **At-origin** (never picked up): the dominant failure mode. Root cause: no volunteer route covers the parcel's origin → destination relay chain. Common sub-causes:
  - No volunteer ever visits the station (`no_volunteer_ever_at_station`)
  - Volunteer routes all end at the stuck station (`route_ends_at_stuck_station`)
  - No onward valid station improves distance (`no_volunteer_route_improves_distance`)
- **In-transit** (stranded mid-route): relay chain broke. Often caused by terminus traps (see below).

### Terminus traps
Stations like Vila do Conde, Varziela, and Ramalde accumulate parcels because volunteer flow is predominantly city-inbound. Parcels needing outbound delivery are structurally trapped. Phase 2 moves some parcels *to* these high-flow intermediate hubs (e.g. Senhora da Hora) but cannot complete the final outbound leg because no outbound volunteers carry them further. This is a network topology limitation, not addressable by heuristic changes alone.

### Locker capacity (negative mode, 10% volunteers, ~1950 parcels)
- `flow+`: Viso 144, Vila do Conde 138, Varziela 123, Ramalde 97, Senhora da Hora 97 (peak concurrent parcels)
- `positive` mode is 3–5× cheaper: peak ~39 at Viso.
- Vila do Conde mean occupancy ~106 over 7 days (parcels stay nearly the full window — terminus trap confirmed).

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
| Phase-2 requires 1-day wait before firing | Without this threshold, Phase 2 displaces parcels before same-day Phase 1 volunteers arrive, catastrophically reducing delivery rate |
| Anti-cycling safeguard deferred | Cycling (Phase 2 bouncing a parcel between hubs) was analytically possible but not observed empirically at 1440 min threshold; evaluation pending |
| 4 heuristics (hop, flow, hop+, flow+) | Clean 2×2 design: distance metric (hop vs flow) × Phase-2 (on vs off) |
| Phase-2 hub attractivity = OD flow + transit flow | Transit flow (passengers passing through as intermediate) adds robustness; empirically the combined metric selects the same hubs as OD-only, confirming major interchanges dominate both signals |
| Experimental confirmation: threshold dominates metric | Tested hop++/flow++ (transit+time-of-day) and hop+++/flow+++ (transit+1-day) crossing variants; `+++`≈`+` and `++` pays −7 pp same-day penalty; threshold is the key design parameter |

---

## What Is Pending / Should Be Tackled Next

### Capacity analysis at lower parcel loads
- **Re-run experiment with parcel_fraction = 0.1%** (~195 parcels/instance). Delivery rate is approximately independent of load, but delivery *span* and same-day rate may differ. Comparing 0.1% and 1% in a single plot (`analyse_loads.py`) will reveal whether span is volunteer-constrained or topology-constrained.
- Update `analyse_loads.py` to support `hop+`/`flow+` in addition to `hop`/`flow`.

### Timetable integration
- `load_timetable()` and the timetable index are built and passed to the volunteer generator, which already uses train departure times when available. However, the scheduler still uses a fixed `--leg-time` for travel between stations (default 3 min). Replacing this with actual arc travel times from `graph.csv` (or GTFS) would improve realism.

### Analysis improvements
- Median/percentile span plots (current plots show mean ± std, which is sensitive to outliers at low fractions).
- Locker capacity plots: peak occupancy vs volunteer fraction per station, to support infrastructure planning.

### Model improvements
- **Acceptance probability**: currently, every volunteer accepts every eligible parcel. A separate parameter `q` (probability of accepting a specific parcel given eligibility) would allow disentangling participation rate from per-parcel acceptance behaviour.
- Volunteer routes are always shortest paths; probabilistic or empirical route choice would add realism.
- Parcel priority or time-window constraints are not modelled.
- Look-ahead or optimisation-based heuristic (vs current greedy myopic approach).
- Anti-cycling safeguard for Phase 2 (currently deferred pending empirical evaluation).

### Validation and testing
- No unit or integration tests exist.
- Priority targets: `network.py` (shortest path, BFS, transfer detection) and `scheduler.py` (delivery in simple hand-crafted topologies).

### OD matrix improvements
- Station-level boarding/alighting data from Metro do Porto (if accessible) would replace synthetic gravity-model marginals with real observations.
- Employment data from INE census grids would improve production/attraction estimates.
