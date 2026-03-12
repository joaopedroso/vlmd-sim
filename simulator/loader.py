"""Load CSV input files into model objects."""

from __future__ import annotations
import csv
from pathlib import Path
from .model import Station, Edge, TimetableEntry, ODEntry, Parcel


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
