"""Discrete-event simulation engine."""

from __future__ import annotations
import heapq
import random
from .model import Event, Parcel, Volunteer, Movement
from .network import Network


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
    """

    def __init__(
        self,
        parcels: list[Parcel],
        volunteers: list[Volunteer],
        network: Network,
        end_time: int,          # minutes since midnight
        leg_time: int = 3,      # default minutes per inter-station leg
        rng: random.Random | None = None,
    ) -> None:
        self._parcels: dict[str, Parcel] = {p.parcel_id: p for p in parcels}
        self._volunteers = volunteers
        self._network = network
        self._end_time = end_time
        self._leg_time = leg_time
        self._rng = rng or random.Random()

        # lockers: station_id -> list of parcel_ids available there
        self._lockers: dict[str, list[str]] = {}
        self._movements: list[Movement] = []
        self._heap: list[Event] = []

    # ------------------------------------------------------------------
    def run(self) -> list[Movement]:
        self._movements.clear()
        self._lockers.clear()
        self._heap.clear()

        for p in self._parcels.values():
            heapq.heappush(self._heap, Event(p.release_time, "parcel_released", p.parcel_id))

        for v in self._volunteers:
            heapq.heappush(self._heap, Event(v.board_time, "volunteer_at", (v, 0)))

        heapq.heappush(self._heap, Event(self._end_time, "end", None))

        while self._heap:
            event = heapq.heappop(self._heap)
            if event.kind == "end" or event.time > self._end_time:
                break
            self._dispatch(event)

        return self._movements

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

                hops_here = self._network.hop_distance(current_station, p.destination)
                best_ahead = min(
                    (self._network.hop_distance(s, p.destination) for s in valid_remaining),
                    default=hops_here + 1,  # no valid stations ahead → deposit here
                )

                if best_ahead < hops_here:
                    # A valid station further ahead is closer to destination; keep carrying.
                    pass
                else:
                    # Current station is at least as good as any valid station still ahead.
                    if hops_here == 0:
                        p.delivered = True
                        p.delivery_time = event.time
                    p.current_locker = current_station
                    if not p.delivered:
                        self._lockers.setdefault(current_station, []).append(p.parcel_id)
                    self._record_movement(p, volunteer.volunteer_id, prev_station, current_station, event.time)
                    volunteer.carrying = None

            # --- Pick up a parcel if not carrying one ---
            if volunteer.carrying is None:
                available = self._lockers.get(current_station, [])
                candidates: list[tuple[int, str]] = []

                for pid in available:
                    p = self._parcels[pid]
                    if p.delivered:
                        continue
                    hops_here = self._network.hop_distance(current_station, p.destination)
                    best_ahead = min(
                        (self._network.hop_distance(s, p.destination) for s in valid_remaining),
                        default=hops_here + 1,
                    )
                    if best_ahead < hops_here:
                        candidates.append((best_ahead, pid))

                if candidates:
                    best_pid = min(candidates)[1]
                    available.remove(best_pid)
                    if not available:
                        del self._lockers[current_station]
                    volunteer.carrying = best_pid

        # --- Advance to next station ---
        next_idx = station_idx + 1
        if next_idx < len(volunteer.route):
            heapq.heappush(self._heap, Event(
                event.time + self._leg_time,
                "volunteer_at",
                (volunteer, next_idx),
            ))

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
