"""Core dataclasses for the simulator."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Station:
    station_id: str
    name: str


@dataclass
class Edge:
    from_station: str
    to_station: str
    travel_time_min: float  # minutes


@dataclass
class TimetableEntry:
    trip_id: str
    station: str
    arrival_time: int  # minutes since midnight


@dataclass
class ODEntry:
    hour: int           # 0-23
    origin: str
    destination: str
    mean_passengers: float


@dataclass
class Parcel:
    parcel_id: str
    release_time: int   # minutes since midnight
    origin: str
    destination: str
    current_locker: str
    delivered: bool = False
    delivery_time: Optional[int] = None


@dataclass(order=True)
class Event:
    time: int
    kind: str = field(compare=False)
    payload: object = field(compare=False, default=None)


@dataclass
class Volunteer:
    volunteer_id: str
    route: list[str]        # ordered list of station ids
    board_time: int         # minutes since midnight at origin
    carrying: Optional[str] = None   # parcel_id being carried


@dataclass
class Movement:
    parcel_id: str
    volunteer_id: str
    from_station: str
    to_station: str
    timestamp: int          # minutes since midnight when parcel arrived at to_station
