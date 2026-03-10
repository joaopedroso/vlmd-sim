"""Graph representation and shortest-path queries."""

from __future__ import annotations
import heapq
from .model import Edge


class Network:
    def __init__(self, edges: list[Edge]) -> None:
        self._adj: dict[str, list[tuple[str, float]]] = {}
        for e in edges:
            self._adj.setdefault(e.from_station, []).append((e.to_station, e.travel_time_min))
            self._adj.setdefault(e.to_station, []).append((e.from_station, e.travel_time_min))

    @property
    def stations(self) -> set[str]:
        return set(self._adj.keys())

    def shortest_path(self, origin: str, destination: str) -> list[str]:
        """Return ordered list of station ids (Dijkstra). Empty list if unreachable."""
        if origin == destination:
            return [origin]
        dist: dict[str, float] = {origin: 0.0}
        prev: dict[str, str] = {}
        heap: list[tuple[float, str]] = [(0.0, origin)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, float("inf")):
                continue
            if u == destination:
                path = []
                cur = destination
                while cur in prev:
                    path.append(cur)
                    cur = prev[cur]
                path.append(origin)
                path.reverse()
                return path
            for v, w in self._adj.get(u, []):
                nd = d + w
                if nd < dist.get(v, float("inf")):
                    dist[v] = nd
                    prev[v] = u
                    heapq.heappush(heap, (nd, v))
        return []

    def path_contains(self, path: list[str], station: str) -> bool:
        return station in path

    def stations_after(self, path: list[str], current: str) -> list[str]:
        """Return all stations on path that come after current (exclusive)."""
        try:
            idx = path.index(current)
            return path[idx + 1:]
        except ValueError:
            return []
