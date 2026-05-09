"""Load CSV input files into model objects."""

from __future__ import annotations
import collections
import csv
from pathlib import Path
from .model import Station, Edge, TimetableEntry, ODEntry, Parcel

# (from_station, to_station) -> sorted list of (depart_min, arrive_min)
TimetableIndex = dict[tuple[str, str], list[tuple[int, int]]]


def _time_to_min(t: str) -> int:
    """Convert 'HH:MM' string to minutes since midnight."""
    h, m = t.strip().split(":")
    return int(h) * 60 + int(m)


def load_stations(path: Path) -> dict[str, Station]:
    stations: dict[str, Station] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            s = Station(station_id=row["station_id"].strip(), name=row["name"].strip())
            stations[s.station_id] = s
    return stations


def load_graph(path: Path) -> list[Edge]:
    edges: list[Edge] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            edges.append(Edge(
                from_station=row["from_station"].strip(),
                to_station=row["to_station"].strip(),
                travel_time_min=float(row["travel_time_min"]),
                line=row.get("line", "").strip(),
            ))
    return edges


def load_timetable(path: Path) -> list[TimetableEntry]:
    entries: list[TimetableEntry] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            entries.append(TimetableEntry(
                trip_id=row["trip_id"].strip(),
                station=row["station"].strip(),
                arrival_time=_time_to_min(row["arrival_time"]),
            ))
    return entries


def build_timetable_index(entries: list[TimetableEntry], n_days: int = 1) -> TimetableIndex:
    """Build edge-keyed lookup from trip entries: (from, to) -> sorted [(depart_min, arrive_min)].

    Repeats the single-day timetable for n_days days, shifting arrival times by
    d * 1440 for day d, so the index covers the full multi-day simulation window.
    """
    trips: dict[str, list[TimetableEntry]] = collections.defaultdict(list)
    for e in entries:
        trips[e.trip_id].append(e)

    # Build base (day-0) edge list
    base_edges: dict[tuple[str, str], list[tuple[int, int]]] = {}
    for stops in trips.values():
        stops.sort(key=lambda e: e.arrival_time)
        for i in range(len(stops) - 1):
            key = (stops[i].station, stops[i + 1].station)
            base_edges.setdefault(key, []).append(
                (stops[i].arrival_time, stops[i + 1].arrival_time)
            )

    # Repeat for each day
    index: TimetableIndex = {}
    for key, slots in base_edges.items():
        index[key] = []
        for day in range(n_days):
            offset = day * 24 * 60
            for depart, arrive in slots:
                index[key].append((depart + offset, arrive + offset))
        index[key].sort()
    return index


def next_arrival(
    timetable: TimetableIndex,
    from_station: str,
    to_station: str,
    not_before: int,
) -> int | None:
    """Arrival time at to_station on the next train from from_station departing >= not_before."""
    for depart, arrive in timetable.get((from_station, to_station), []):
        if depart >= not_before:
            return arrive
    return None


def load_od_matrices(path: Path) -> list[ODEntry]:
    entries: list[ODEntry] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            mean = float(row["mean_passengers"])
            variance = float(row["variance_passengers"]) if "variance_passengers" in row else 0.1 * mean
            entries.append(ODEntry(
                hour=int(row["hour"]),
                origin=row["origin"].strip(),
                destination=row["destination"].strip(),
                mean_passengers=mean,
                variance_passengers=variance,
            ))
    return entries


def od_daily_flows(entries: list[ODEntry]) -> dict[tuple[str, str], float]:
    """Aggregate OD entries into total daily mean passengers per directed pair."""
    flows: dict[tuple[str, str], float] = {}
    for e in entries:
        key = (e.origin, e.destination)
        flows[key] = flows.get(key, 0.0) + e.mean_passengers
    return flows


def load_parcels(path: Path) -> list[Parcel]:
    parcels: list[Parcel] = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            parcels.append(Parcel(
                parcel_id=row["parcel_id"].strip(),
                release_time=_time_to_min(row["release_time"]),
                origin=row["origin"].strip(),
                destination=row["destination"].strip(),
                current_locker=row["current_locker"].strip(),
            ))
    return parcels
