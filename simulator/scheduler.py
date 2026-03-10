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
    'parcel_released'  – payload: Parcel
    'volunteer_at'     – payload: (Volunteer, station_index: int)
    'end'              – payload: None
    """

    def __init__(
        self,
        parcels: list[Parcel],
        volunteers: list[Volunteer],
        network: Network,
        end_time: int,          # minutes since midnight
        leg_time: int = 3,      # default minutes per inter-station leg if timetable absent
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

        # Schedule parcel-release events
        for p in self._parcels.values():
            heapq.heappush(self._heap, Event(p.release_time, "parcel_released", p.parcel_id))

        # Schedule first volunteer arrival (at their origin station)
        for v in self._volunteers:
            heapq.heappush(self._heap, Event(v.board_time, "volunteer_at", (v, 0)))

        # End-of-simulation sentinel
        heapq.heappush(self._heap, Event(self._end_time, "end", None))

        while self._heap:
            event = heapq.heappop(self._heap)
            if event.kind == "end":
                break
            if event.time > self._end_time:
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

        # --- Drop off carried parcel if destination reached ---
        if volunteer.carrying is not None:
            p = self._parcels[volunteer.carrying]
            if p.destination == current_station:
                p.delivered = True
                p.delivery_time = event.time
                p.current_locker = current_station
                self._movements.append(Movement(
                    parcel_id=p.parcel_id,
                    volunteer_id=volunteer.volunteer_id,
                    from_station=volunteer.route[station_idx - 1] if station_idx > 0 else current_station,
                    to_station=current_station,
                    timestamp=event.time,
                ))
                volunteer.carrying = None
            elif p.destination in self._network.stations_after(volunteer.route, current_station):
                # Keep carrying — will deliver later
                pass
            else:
                # Volunteer's route doesn't reach destination; deposit in locker here
                p.current_locker = current_station
                self._lockers.setdefault(current_station, []).append(p.parcel_id)
                self._movements.append(Movement(
                    parcel_id=p.parcel_id,
                    volunteer_id=volunteer.volunteer_id,
                    from_station=volunteer.route[station_idx - 1] if station_idx > 0 else current_station,
                    to_station=current_station,
                    timestamp=event.time,
                ))
                volunteer.carrying = None

        # --- Pick up a parcel if not carrying one ---
        if volunteer.carrying is None:
            ahead = self._network.stations_after(volunteer.route, current_station)
            ahead_set = set(ahead)
            available = self._lockers.get(current_station, [])
            # Find parcels whose destination is on the volunteer's remaining route
            candidates = [
                pid for pid in available
                if not self._parcels[pid].delivered
                and self._parcels[pid].destination in ahead_set
            ]
            if candidates:
                # Greedy: pick the parcel whose destination appears earliest on route
                def route_idx(pid: str) -> int:
                    dest = self._parcels[pid].destination
                    return ahead.index(dest) if dest in ahead else len(ahead)

                best = min(candidates, key=route_idx)
                available.remove(best)
                if not available:
                    del self._lockers[current_station]
                volunteer.carrying = best
                self._parcels[best].current_locker = current_station  # in transit

        # --- Advance volunteer to next station ---
        next_idx = station_idx + 1
        if next_idx < len(volunteer.route):
            heapq.heappush(self._heap, Event(
                event.time + self._leg_time,
                "volunteer_at",
                (volunteer, next_idx),
            ))
