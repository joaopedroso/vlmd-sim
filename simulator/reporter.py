"""Collect simulation results and compute statistics."""

from __future__ import annotations
import csv
import statistics
from pathlib import Path
from .model import Parcel, Movement


def compute_stats(parcels: list[Parcel]) -> dict:
    spans = [
        p.delivery_time - p.release_time
        for p in parcels
        if p.delivered and p.delivery_time is not None
    ]
    n_delivered  = len(spans)
    n_total      = len(parcels)
    # Undelivered parcels: distinguish those moved at least once from those
    # that never left their origin locker.
    n_in_transit = sum(
        1 for p in parcels
        if not p.delivered and p.current_locker != p.origin
    )
    n_at_origin  = n_total - n_delivered - n_in_transit
    # Same-day: delivered before midnight of the day the parcel was released.
    n_same_day = sum(
        1 for p in parcels
        if p.delivered and p.delivery_time is not None
        and p.delivery_time < (p.release_time // 1440 + 1) * 1440
    )
    return {
        "n_total":        n_total,
        "n_delivered":    n_delivered,
        "n_in_transit":   n_in_transit,   # moved ≥1 hop, not yet at destination
        "n_at_origin":    n_at_origin,    # never picked up
        "n_same_day":     n_same_day,     # delivered before midnight on release day
        "delivery_rate":  n_delivered / n_total if n_total else 0.0,
        "same_day_rate":  n_same_day   / n_total if n_total else 0.0,
        "mean_span_min":   statistics.mean(spans)   if spans           else None,
        "median_span_min": statistics.median(spans) if spans           else None,
        "stdev_span_min":  statistics.stdev(spans)  if len(spans) > 1  else None,
        "min_span_min":    min(spans)                if spans           else None,
        "max_span_min":    max(spans)                if spans           else None,
    }


def save_movements(movements: list[Movement], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["parcel_id", "volunteer_id", "from_station", "to_station", "timestamp_min"])
        for m in movements:
            writer.writerow([m.parcel_id, m.volunteer_id, m.from_station, m.to_station, m.timestamp])


def save_parcel_summary(parcels: list[Parcel], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["parcel_id", "origin", "destination", "release_time_min",
                         "delivery_time_min", "span_min", "delivered"])
        for p in parcels:
            span = (p.delivery_time - p.release_time) if p.delivered else ""
            writer.writerow([p.parcel_id, p.origin, p.destination,
                             p.release_time, p.delivery_time or "", span, p.delivered])
