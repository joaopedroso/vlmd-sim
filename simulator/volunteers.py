"""Generate volunteers from OD matrices."""

from __future__ import annotations
import math
import random
from .model import ODEntry, Volunteer
from .network import Network
from .loader import TimetableIndex


def _poisson(rng: random.Random, lam: float) -> int:
    """Sample from Poisson(lam). Knuth's algorithm for lam ≤ 30, Normal approx above."""
    if lam <= 0:
        return 0
    if lam > 30:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    L = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        k += 1
        p *= rng.random()
        if p <= L:
            return k - 1


def generate_volunteers(
    od_entries: list[ODEntry],
    network: Network,
    volunteer_fraction: float,
    rng: random.Random,
    timetable: TimetableIndex | None = None,
    n_days: int = 1,
) -> list[Volunteer]:
    """
    For each OD entry and each simulation day, sample commuters (Normal
    approximation), take volunteer_fraction of them, and assign departures.
    Day d shifts all board times by d * 1440 minutes.
    """
    volunteers: list[Volunteer] = []
    vid = 0

    for entry in od_entries:
        if entry.mean_passengers <= 0:
            continue
        mean = entry.mean_passengers

        route = network.shortest_path(entry.origin, entry.destination)
        if len(route) < 2:
            continue  # unreachable or same station

        valid = network.valid_stations(route)

        for day in range(n_days):
            # Independent draw per day: each day is a fresh Poisson trial so
            # sparse OD pairs have n_days independent chances to generate a
            # volunteer rather than one draw repeated for the whole week.
            count = _poisson(rng, mean)
            n_volunteers = round(count * volunteer_fraction)
            if n_volunteers == 0:
                continue

            day_offset = day * 24 * 60
            hour_start = entry.hour * 60 + day_offset

            # Timetable departures from origin toward first hop within this hour
            timetable_departures: list[int] = []
            if timetable:
                timetable_departures = [
                    depart for depart, _ in timetable.get((entry.origin, route[1]), [])
                    if hour_start <= depart < hour_start + 60
                ]

            for _ in range(n_volunteers):
                if timetable_departures:
                    board_time = rng.choice(timetable_departures)
                else:
                    board_time = hour_start + rng.randint(0, 59)
                volunteers.append(Volunteer(
                    volunteer_id=f"V{vid:06d}",
                    route=route,
                    board_time=board_time,
                    valid_stations=valid,
                ))
                vid += 1

    return volunteers
