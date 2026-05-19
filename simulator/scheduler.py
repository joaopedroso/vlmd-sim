"""Discrete-event simulation engine."""

from __future__ import annotations
import heapq
import random
from .model import Event, Parcel, Volunteer, Movement
from .network import Network
from .loader import TimetableIndex, next_arrival


class Simulator:
    """
    Event types
    -----------
    'parcel_released'  – payload: parcel_id (str)
    'volunteer_at'     – payload: (Volunteer, station_index: int)
    'end'              – payload: None

    Transshipment heuristic
    -----------------------
    A volunteer picks up a parcel at their current station if at least one
    station on their remaining route is strictly closer (fewer hops) to the
    parcel's destination than the current locker.

    The volunteer deposits the parcel as soon as no remaining station on their
    route improves on the current station's hop distance to the destination
    (i.e. the current station is at least as good as anywhere still ahead).
    This naturally includes direct delivery when the destination is reached.
    Heuristics
    ----------
    'hop'   – distances measured in unweighted graph hops (original)
    'flow'  – distances measured as weighted shortest path with arc weight
               1 / daily_OD_flow(A→B); lower cost = more volunteer coverage.
               Requires network.precompute_flow_distances() to have been called.
    """

    def __init__(
        self,
        parcels: list[Parcel],
        volunteers: list[Volunteer],
        network: Network,
        end_time: int | None = None,        # None = run until queue is exhausted
        leg_time: int = 3,                  # fallback minutes per inter-station leg
        timetable: TimetableIndex | None = None,
        rng: random.Random | None = None,
        heuristic: str = "hop",             # "hop" or "flow"
    ) -> None:
        self._parcels: dict[str, Parcel] = {p.parcel_id: p for p in parcels}
        self._volunteers = volunteers
        self._network = network
        self._end_time = end_time
        self._leg_time = leg_time
        self._timetable: TimetableIndex = timetable or {}
        self._rng = rng or random.Random()
        # "hop+" / "flow+" mean base heuristic + Phase-2 fallback to busier stations
        self._heuristic = heuristic.rstrip("+")
        self._phase2 = heuristic.endswith("+")

        # lockers: station_id -> list of parcel_ids available there
        self._lockers: dict[str, list[str]] = {}
        # time each parcel was last placed into its current locker (for Phase-2 delay)
        self._locker_since: dict[str, int] = {}
        # completed locker stays: (station_id, parcel_id, enter_time, exit_time)
        self._locker_history: list[tuple[str, str, int, int]] = []
        self._movements: list[Movement] = []
        self._heap: list[Event] = []

    # ------------------------------------------------------------------
    def run(self) -> list[Movement]:
        self._movements.clear()
        self._lockers.clear()
        self._locker_since.clear()
        self._locker_history.clear()
        self._heap.clear()

        self._n_undelivered = len(self._parcels)

        for p in self._parcels.values():
            heapq.heappush(self._heap, Event(p.release_time, "parcel_released", p.parcel_id))

        for v in self._volunteers:
            heapq.heappush(self._heap, Event(v.board_time, "volunteer_at", (v, 0)))

        if self._end_time is not None:
            heapq.heappush(self._heap, Event(self._end_time, "end", None))

        while self._heap:
            event = heapq.heappop(self._heap)
            if event.kind == "end":
                break
            self._dispatch(event)
            if self._n_undelivered == 0:
                break

        return self._movements

    # ------------------------------------------------------------------
    def _dist(self, station: str, destination: str) -> float:
        """Distance from station to destination under the active heuristic."""
        if self._heuristic == "flow":
            return self._network.flow_distance(station, destination)
        return float(self._network.hop_distance(station, destination))

    # ------------------------------------------------------------------
    def _dispatch(self, event: Event) -> None:
        if event.kind == "parcel_released":
            self._on_parcel_released(event)
        elif event.kind == "volunteer_at":
            self._on_volunteer_at(event)

    def _on_parcel_released(self, event: Event) -> None:
        pid: str = event.payload
        p = self._parcels[pid]
        self._lockers.setdefault(p.current_locker, []).append(pid)
        self._locker_since[pid] = event.time

    def _on_volunteer_at(self, event: Event) -> None:
        volunteer: Volunteer
        station_idx: int
        volunteer, station_idx = event.payload

        current_station = volunteer.route[station_idx]
        prev_station = volunteer.route[station_idx - 1] if station_idx > 0 else current_station
        remaining = volunteer.route[station_idx + 1:]   # stations strictly after current

        # Locker interactions are only allowed at valid stations (origin, destination,
        # or transfer points where the volunteer changes metro line).
        if current_station in volunteer.valid_stations:
            # Among remaining stations, only those where interaction is allowed matter
            # for hop-distance comparisons (the parcel can only be picked up there).
            valid_remaining = [s for s in remaining if s in volunteer.valid_stations]

            # --- Drop off or keep carrying ---
            if volunteer.carrying is not None:
                p = self._parcels[volunteer.carrying]

                dist_here = self._dist(current_station, p.destination)
                best_ahead = min(
                    (self._dist(s, p.destination) for s in valid_remaining),
                    default=float("inf"),   # no valid stations ahead → deposit here
                )

                if best_ahead < dist_here:
                    # A valid station further ahead is closer to destination; keep carrying.
                    pass
                else:
                    # Current station is at least as good as any valid station still ahead.
                    if self._network.hop_distance(current_station, p.destination) == 0:
                        p.delivered = True
                        p.delivery_time = event.time
                        self._n_undelivered -= 1
                    p.current_locker = current_station
                    if not p.delivered:
                        self._lockers.setdefault(current_station, []).append(p.parcel_id)
                        self._locker_since[p.parcel_id] = event.time
                    self._record_movement(p, volunteer.volunteer_id, prev_station, current_station, event.time)
                    volunteer.carrying = None

            # --- Pick up a parcel if not carrying one ---
            if volunteer.carrying is None:
                available = self._lockers.get(current_station, [])
                candidates: list[tuple[float, str]] = []

                for pid in available:
                    p = self._parcels[pid]
                    if p.delivered:
                        continue
                    dist_here = self._dist(current_station, p.destination)
                    best_ahead = min(
                        (self._dist(s, p.destination) for s in valid_remaining),
                        default=float("inf"),
                    )
                    if best_ahead < dist_here:
                        candidates.append((best_ahead, pid))

                if candidates:
                    # Phase 1: strict progress — pick the parcel we can bring closest.
                    best_pid = min(candidates)[1]
                    self._do_pickup(available, current_station, best_pid, event.time)
                    volunteer.carrying = best_pid
                elif self._phase2 and available:
                    # Phase 2 fallback: no strict progress possible, but move the
                    # parcel to a busier hub to improve relay-chain chances.
                    # Only consider parcels that have been waiting ≥ 1 day so that
                    # Phase-1 volunteers have had a full day of chances first.
                    flow_here = self._network.station_flow(current_station)
                    best_flow_ahead = max(
                        (self._network.station_flow(s) for s in valid_remaining),
                        default=0.0,
                    )
                    if best_flow_ahead > flow_here:
                        eligible = [
                            pid for pid in available
                            if not self._parcels[pid].delivered
                            and event.time - self._locker_since.get(pid, 0) >= 1440
                        ]
                        if eligible:
                            # Among eligible parcels prefer the one closest to its
                            # destination — most likely to be completed from the hub.
                            best_pid = min(
                                eligible,
                                key=lambda pid: self._dist(
                                    current_station, self._parcels[pid].destination
                                ),
                            )
                            self._do_pickup(available, current_station, best_pid, event.time)
                            volunteer.carrying = best_pid

        # --- Advance to next station ---
        next_idx = station_idx + 1
        if next_idx < len(volunteer.route):
            next_station = volunteer.route[next_idx]
            arrive = next_arrival(self._timetable, current_station, next_station, event.time)
            if arrive is None:
                arrive = event.time + self._leg_time
            heapq.heappush(self._heap, Event(arrive, "volunteer_at", (volunteer, next_idx)))

    def _do_pickup(
        self, available: list[str], station: str, pid: str, now: int
    ) -> None:
        """Remove pid from the station locker and log the completed stay."""
        self._locker_history.append(
            (station, pid, self._locker_since.get(pid, 0), now)
        )
        available.remove(pid)
        if not available:
            del self._lockers[station]

    def get_locker_history(
        self, end_time: int | None = None
    ) -> list[tuple[str, str, int, int]]:
        """Return completed locker stays plus open stays for parcels still in lockers.

        end_time defaults to 7 × 1440 (7-day simulation window).
        Each entry: (station_id, parcel_id, enter_time, exit_time).
        """
        close = end_time if end_time is not None else 7 * 1440
        result = list(self._locker_history)
        for station, pids in self._lockers.items():
            for pid in pids:
                result.append((station, pid, self._locker_since.get(pid, 0), close))
        return result

    def _record_movement(
        self,
        parcel: Parcel,
        volunteer_id: str,
        from_station: str,
        to_station: str,
        timestamp: int,
    ) -> None:
        self._movements.append(Movement(
            parcel_id=parcel.parcel_id,
            volunteer_id=volunteer_id,
            from_station=from_station,
            to_station=to_station,
            timestamp=timestamp,
        ))
