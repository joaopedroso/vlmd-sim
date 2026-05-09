# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**vlmd-sim** — a discrete-event simulator for volunteer-based last-mile parcel delivery over metro networks. The research goal is to study delivery span (time from parcel release to delivery) as a function of the fraction of passengers acting as volunteers.

The simulator models parcels moving through metro-station lockers, carried by commuter-volunteers on their regular routes. Data is based on the Porto, Portugal metro network.

## Commands

This project uses `uv` for dependency management.

```bash
# Install dependencies
uv sync

# Run main entry point
uv run python main.py

# Run with a specific volunteer fraction
uv run python main.py --volunteer-fraction 0.3

# Sweep all volunteer fractions from 0% to 100% (step 10%)
uv run python main.py --sweep

# Additional options
uv run python main.py -p 0.5 --leg-time 4 --seed 123 --quiet
```

---

## Project Structure

```
SIMULATOR/
├── main.py                  # CLI entry point; orchestrates simulation runs and sweep mode
├── simulator/
│   ├── model.py             # Dataclass definitions (Station, Edge, ODEntry, Parcel, Volunteer, Event, Movement)
│   ├── network.py           # Graph representation; Dijkstra + BFS hop-distance precomputation
│   ├── loader.py            # CSV loaders for graph, OD matrices, parcels, stations, timetable
│   ├── volunteers.py        # Stochastic volunteer generation from OD matrices
│   ├── scheduler.py         # Discrete-event simulation engine + transshipment heuristic
│   └── reporter.py          # Statistics computation and CSV output
└── data/
    ├── graph.csv            # Metro edges with travel times and line identifiers
    ├── stations.csv         # Station IDs and names
    ├── od_matrices.csv      # Hourly OD matrices with mean and variance of passenger counts
    ├── parcels.csv          # 21 sample parcels (origin, destination, release time)
    └── timetable.csv        # Train timetable (loaded but not yet used in simulation)
```

Results are written to `results/` (git-ignored): `movements_p<X>.csv` and `parcels_p<X>.csv` per volunteer fraction.

---

## Architecture & Key Design Decisions

### Simulation model
- **Discrete-event simulation** using a heap-based priority queue. Events: `parcel_released`, `volunteer_at`, `end`.
- Volunteers are generated stochastically from OD matrices (Normal distribution over passenger counts, using explicit mean and variance per OD entry).
- Each volunteer has a shortest-path route; departures are spread uniformly within the hour.

### Transshipment heuristic (greedy, hop-distance based)
- Volunteers interact with lockers **only at valid stations**: their origin, destination, and any metro line transfer points along their route. This models realistic behaviour (volunteers don't stop at every station).
- **Pick-up**: a volunteer picks up a parcel only if some valid remaining station on their route is strictly closer (fewer hops) to the parcel's destination.
- **Drop-off**: the volunteer drops the parcel at the earliest valid station that is no worse (same or fewer hops) than any station ahead — or delivers it directly if hops = 0.
- Parcels thus monotonically approach their destination when volunteers are available.

### Network
- All-pairs hop distances are precomputed via BFS at initialization.
- `transfer_stations()` identifies stations where the metro line changes.
- `valid_stations()` returns the frozenset {origin, destination} ∪ transfer_stations for a route.

---

## What Has Been Done

1. **Full simulator implemented** (commits `8741e02` and `c3a2757`):
   - Data model, CSV loaders, graph/network module, volunteer generator, event scheduler, statistics reporter.
   - CLI with single-run and sweep modes.
   - Sample Porto metro dataset (26 stations, 5 lines, 144 OD pairs, 21 parcels).

2. **Refinements applied** (commit `c3a2757`, 2026-03-12):
   - `ODEntry.variance_passengers` added (was hard-coded as 0.1 × mean); CSV loader updated.
   - `Edge.line` added; `graph.csv` updated with line identifiers.
   - Network enhanced: hop-distance precomputation (BFS), `transfer_stations()`, `valid_stations()`.
   - `Volunteer.valid_stations` (frozenset) introduced.
   - Scheduler refactored: locker interactions restricted to valid stations; transshipment heuristic implemented.

3. All three TODO items from `PROBLEM.md` are now resolved:
   - ~~Variance as ODEntry attribute~~ — done.
   - ~~Adapt model for transshipments~~ — done (scheduler transshipment logic).
   - ~~Heuristics for approaching parcels to destination~~ — done (hop-distance greedy).

---

## What Is Pending / Should Be Tackled Next

### Timetable integration
- `load_timetable()` and `load_stations()` exist but are unused. The simulation currently uses a fixed `--leg-time` per arc.
- **Next step**: replace or supplement fixed leg-time with actual train schedules, so volunteer arrivals are aligned with real departure times.

### Analysis and visualisation
- No analysis or plotting scripts exist. Results CSV files are produced but not analysed.
- **Next step**: add a script (e.g., `analyse.py`) to read sweep results and plot delivery rate and span metrics vs. volunteer fraction.

### Validation and testing
- No unit or integration tests exist.
- **Next step**: add tests for network (shortest path, hop distances, transfer station detection) and scheduler (parcel delivery in simple topologies).

### Possible model improvements
- Current pick-up/drop-off is greedy and myopic; a look-ahead or optimisation-based heuristic could improve delivery rates.
- Volunteer routes are always shortest paths; exploring probabilistic or empirical route choices could add realism.
- Parcel priority or time-window constraints are not modelled.
