"""Graph representation and shortest-path queries."""

from __future__ import annotations
import collections
import heapq
from .model import Edge

_UNREACHABLE = 999

# Express-service suffixes that share the same physical line as their base.
# Bx is the Porto Metro express variant of line B; treat as the same line
# for transfer-detection purposes.
_LINE_ALIASES: dict[str, str] = {"Bx": "B"}


def _canonical_line(line: str) -> str:
    return _LINE_ALIASES.get(line, line)


class Network:
    def __init__(self, edges: list[Edge]) -> None:
        self._adj: dict[str, list[tuple[str, float]]] = {}
        # full set of canonical lines serving each directed edge (a→b)
        self._edge_lines: dict[tuple[str, str], set[str]] = {}
        # lines serving each station (used to identify network-level transfer stations)
        self._station_lines: dict[str, set[str]] = {}
        for e in edges:
            canon = _canonical_line(e.line)
            self._adj.setdefault(e.from_station, []).append((e.to_station, e.travel_time_min))
            self._adj.setdefault(e.to_station, []).append((e.from_station, e.travel_time_min))
            self._edge_lines.setdefault((e.from_station, e.to_station), set()).add(canon)
            self._edge_lines.setdefault((e.to_station, e.from_station), set()).add(canon)
            self._station_lines.setdefault(e.from_station, set()).add(canon)
            self._station_lines.setdefault(e.to_station,   set()).add(canon)

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

    def _bfs_path(self, origin: str, destination: str) -> list[str]:
        """Return one BFS shortest path from origin to destination."""
        if origin == destination:
            return [origin]
        prev: dict[str, str] = {}
        queue: collections.deque[str] = collections.deque([origin])
        visited: set[str] = {origin}
        while queue:
            u = queue.popleft()
            for v, _ in self._adj.get(u, []):
                if v not in visited:
                    visited.add(v)
                    prev[v] = u
                    if v == destination:
                        path, cur = [], destination
                        while cur != origin:
                            path.append(cur)
                            cur = prev[cur]
                        path.append(origin)
                        path.reverse()
                        return path
                    queue.append(v)
        return []  # unreachable

    def is_transfer_station(self, station: str) -> bool:
        """True if this station is served by more than one metro line."""
        return len(self._station_lines.get(station, set())) > 1

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
        """Stations on route where no single line runs continuously through both
        adjacent edges — i.e. the commuter must change trains."""
        transfers: set[str] = set()
        for i in range(1, len(route) - 1):
            lines_in  = self._edge_lines.get((route[i - 1], route[i]), set())
            lines_out = self._edge_lines.get((route[i], route[i + 1]), set())
            if lines_in and lines_out and lines_in.isdisjoint(lines_out):
                transfers.add(route[i])
        return transfers

    def valid_stations(self, route: list[str]) -> frozenset:
        """Origin, destination, and all inter-line interchange stations on route.

        An interchange station is one served by more than one distinct metro line.
        These are the stations where a commuter's train physically stops at a hub
        where they could realistically interact with a locker.
        """
        if not route:
            return frozenset()
        interchanges = {s for s in route[1:-1] if self.is_transfer_station(s)}
        return frozenset({route[0], route[-1]} | interchanges)

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

    def precompute_station_flows(
        self, od_flows: dict[tuple[str, str], float]
    ) -> None:
        """Precompute total daily flow (in + out) per station.

        Used by the Phase-2 fallback heuristic to identify busier relay hubs.
        Call this once per OD matrix before using station_flow().
        """
        totals: dict[str, float] = {}
        for (a, b), flow in od_flows.items():
            totals[a] = totals.get(a, 0.0) + flow
            totals[b] = totals.get(b, 0.0) + flow
        self._station_flows = totals

    def station_flow(self, station: str) -> float:
        """Total daily OD flow through a station (in + out).

        Raises RuntimeError if precompute_station_flows() has not been called.
        """
        if not hasattr(self, "_station_flows"):
            raise RuntimeError(
                "Call precompute_station_flows() before using station_flow()."
            )
        return self._station_flows.get(station, 0.0)

    def precompute_transit_flows(
        self, od_flows: dict[tuple[str, str], float]
    ) -> None:
        """Precompute transit flow per station: total OD flow passing through as intermediate.

        For each OD pair (A, B), all interior stations on the BFS shortest path from A to B
        receive the pair's daily flow contribution. Endpoint stations (A, B) are excluded.
        Call this once per OD matrix before using transit_flow().
        """
        totals: dict[str, float] = {}
        for (a, b), flow in od_flows.items():
            for s in self._bfs_path(a, b)[1:-1]:
                totals[s] = totals.get(s, 0.0) + flow
        self._transit_flows = totals

    def transit_flow(self, station: str) -> float:
        """OD flow that passes through this station as an intermediate hop.

        Raises RuntimeError if precompute_transit_flows() has not been called.
        """
        if not hasattr(self, "_transit_flows"):
            raise RuntimeError(
                "Call precompute_transit_flows() before using transit_flow()."
            )
        return self._transit_flows.get(station, 0.0)

    def combined_station_flow(self, station: str) -> float:
        """OD flow (trips starting/ending here) + transit flow (trips passing through).

        Raises RuntimeError if precompute_station_flows() or precompute_transit_flows()
        has not been called.
        """
        return self.station_flow(station) + self.transit_flow(station)

    def precompute_flow_distances(
        self, od_flows: dict[tuple[str, str], float]
    ) -> None:
        """Precompute all-pairs weighted shortest-path distances.

        Arc weight for A→B = 1 / total_daily_OD_flow(A→B).
        Lower distance means more volunteer coverage on that route.
        Call this once per OD matrix before using flow_distance().
        Also computes station flows and transit flows as a side effect.
        """
        self.precompute_station_flows(od_flows)
        self.precompute_transit_flows(od_flows)
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
