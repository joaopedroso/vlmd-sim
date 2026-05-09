"""Graph representation and shortest-path queries."""

from __future__ import annotations
import collections
import heapq
from .model import Edge

_UNREACHABLE = 999


class Network:
    def __init__(self, edges: list[Edge]) -> None:
        self._adj: dict[str, list[tuple[str, float]]] = {}
        # line for each directed edge (a→b); both directions get the same line
        self._edge_line: dict[tuple[str, str], str] = {}
        for e in edges:
            self._adj.setdefault(e.from_station, []).append((e.to_station, e.travel_time_min))
            self._adj.setdefault(e.to_station, []).append((e.from_station, e.travel_time_min))
            self._edge_line[(e.from_station, e.to_station)] = e.line
            self._edge_line[(e.to_station, e.from_station)] = e.line

        # Precompute all-pairs hop distances (BFS, unweighted)
        self._hops: dict[str, dict[str, int]] = {
            s: self._bfs_hops(s) for s in self._adj
        }

    def _bfs_hops(self, origin: str) -> dict[str, int]:
        dist: dict[str, int] = {origin: 0}
        queue: collections.deque[str] = collections.deque([origin])
        while queue:
            u = queue.popleft()
            for v, _ in self._adj.get(u, []):
                if v not in dist:
                    dist[v] = dist[u] + 1
                    queue.append(v)
        return dist

    def hop_distance(self, origin: str, destination: str) -> int:
        """Number of hops (edges) on the shortest unweighted path. Returns 999 if unreachable."""
        return self._hops.get(origin, {}).get(destination, _UNREACHABLE)

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

    def transfer_stations(self, route: list[str]) -> set[str]:
        """Stations on route where the metro line changes between consecutive edges."""
        transfers: set[str] = set()
        for i in range(1, len(route) - 1):
            line_in  = self._edge_line.get((route[i - 1], route[i]), "")
            line_out = self._edge_line.get((route[i], route[i + 1]), "")
            if line_in and line_out and line_in != line_out:
                transfers.add(route[i])
        return transfers

    def valid_stations(self, route: list[str]) -> frozenset:
        """Origin, destination, and all transfer stations on route."""
        if not route:
            return frozenset()
        return frozenset({route[0], route[-1]} | self.transfer_stations(route))

    def stations_after(self, path: list[str], current: str) -> list[str]:
        """Return all stations on path that come after current (exclusive)."""
        try:
            idx = path.index(current)
            return path[idx + 1:]
        except ValueError:
            return []

    # ------------------------------------------------------------------
    # Flow-weighted distances (must call precompute_flow_distances first)
    # ------------------------------------------------------------------

    def precompute_flow_distances(
        self, od_flows: dict[tuple[str, str], float]
    ) -> None:
        """Precompute all-pairs weighted shortest-path distances.

        Arc weight for A→B = 1 / total_daily_OD_flow(A→B).
        Lower distance means more volunteer coverage on that route.
        Call this once per OD matrix before using flow_distance().
        """
        self._flow_dist: dict[str, dict[str, float]] = {
            s: self._dijkstra_flow(s, od_flows) for s in self._adj
        }

    def _dijkstra_flow(
        self,
        origin: str,
        od_flows: dict[tuple[str, str], float],
    ) -> dict[str, float]:
        INF = float("inf")
        dist: dict[str, float] = {origin: 0.0}
        heap: list[tuple[float, str]] = [(0.0, origin)]
        while heap:
            d, u = heapq.heappop(heap)
            if d > dist.get(u, INF):
                continue
            for v, _ in self._adj.get(u, []):
                flow = od_flows.get((u, v), 0.0)
                w = 1.0 / flow if flow > 0.0 else INF
                nd = d + w
                if nd < dist.get(v, INF):
                    dist[v] = nd
                    heapq.heappush(heap, (nd, v))
        return dist

    def flow_distance(self, origin: str, destination: str) -> float:
        """Weighted shortest-path distance (lower = more volunteer flow).

        Raises RuntimeError if precompute_flow_distances() has not been called.
        """
        if not hasattr(self, "_flow_dist"):
            raise RuntimeError(
                "Call precompute_flow_distances() before using flow_distance()."
            )
        return self._flow_dist.get(origin, {}).get(destination, float("inf"))
