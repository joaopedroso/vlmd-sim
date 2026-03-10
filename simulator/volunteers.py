"""Generate volunteers from OD matrices."""

from __future__ import annotations
import math
import random
from .model import ODEntry, Volunteer
from .network import Network


def generate_volunteers(
    od_entries: list[ODEntry],
    network: Network,
    volunteer_fraction: float,
    rng: random.Random,
) -> list[Volunteer]:
    """
    For each OD entry sample a number of commuters (Normal approximation,
    variance = 0.1 * mean), take volunteer_fraction of them, assign a shortest-
    path route, and spread departures uniformly across the hour.
    """
    volunteers: list[Volunteer] = []
    vid = 0

    for entry in od_entries:
        if entry.mean_passengers <= 0:
            continue
        mean = entry.mean_passengers
        std = math.sqrt(0.1 * mean)
        count = max(0, round(rng.gauss(mean, std)))
        n_volunteers = round(count * volunteer_fraction)

        route = network.shortest_path(entry.origin, entry.destination)
        if len(route) < 2:
            continue  # unreachable or same station

        hour_start = entry.hour * 60  # minutes since midnight
        for _ in range(n_volunteers):
            board_time = hour_start + rng.randint(0, 59)
            volunteers.append(Volunteer(
                volunteer_id=f"V{vid:06d}",
                route=route,
                board_time=board_time,
            ))
            vid += 1

    return volunteers
