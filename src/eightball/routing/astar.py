"""Per-zone shortest paths on the Hanan grid (handoff 6 step 3, BUILD_SPLIT A6). Implements ``PathCost``.

State is (vertex, heading of the last move). A move costs its length in metres, plus 0.5 for a 90-degree turn;
reversals are never allowed. A path leaves ``a`` along ``heading_in`` and arrives at ``b`` along ``heading_out``,
so the turns at the two ends are not counted here (the ring scorer adds them). Only edges lying in the allowed
rooms are used, so a zone's cable never wanders into another hub's rooms.

For each (allowed room set, source node) one Dijkstra per start heading fills the costs to every vertex and
heading, so all 4 x 4 heading combinations of every node pair come out of the same four runs; they are cached by
(allowed_rooms, source).
"""
from __future__ import annotations

import heapq
from collections import OrderedDict

import numpy as np

from eightball.core.contracts import CleanPlan
from eightball.routing import api
from eightball.routing.api import HEADINGS, Point2, Polyline
from eightball.routing.hanan import NO, TrackGrid, build_tracks

INF = float("inf")
NOT_FOUND: tuple[float, Polyline] = (INF, [])
TURN = 0.5


class _Run:
    """Dijkstra result from one source with one forced first heading."""
    __slots__ = ("dist", "prev")

    def __init__(self, dist: dict[int, float], prev: dict[int, int]):
        self.dist, self.prev = dist, prev


class HananRouter:
    def __init__(self, cp: CleanPlan, grid: TrackGrid | None = None, cache_size: int = 4096):
        self.cp = cp
        self.grid = grid or cp.tracks or build_tracks(cp)
        self.scale = cp.scale
        g = self.grid
        self._len_m = (g.e_len / self.scale).tolist()
        self._nbr = [g.nbr[h].tolist() for h in HEADINGS]
        self._nbr_edge = [g.nbr_edge[h].tolist() for h in HEADINGS]
        self._vx, self._vy = g.vx.tolist(), g.vy.tolist()
        self._allowed_cache: dict[frozenset[str], list[bool]] = {}
        self._runs: OrderedDict[tuple[frozenset[str], int, int], _Run] = OrderedDict()
        self._cache_size = cache_size

    # ---- helpers -------------------------------------------------------------------------------

    def allowed_rooms_for(self, zone_room_ids) -> frozenset[str]:
        """Rooms a zone's cable may use (same rule as the crude router)."""
        from eightball import config
        if config.ALLOW_THROUGH_OTHER_ZONES:
            return frozenset(self.cp.rooms)
        noded = {n.room_id for n in self.cp.nodes.values()}
        allowed = set(zone_room_ids)
        for rid, room in self.cp.rooms.items():
            if rid not in noded and (config.ALLOW_THROUGH_EXCLUDED or room.eligible):
                allowed.add(rid)
        return frozenset(allowed)

    def vertex_of(self, pid: str) -> int:
        if pid in self.grid.node_vertex:
            return self.grid.node_vertex[pid]
        p = api.parse_point_id(pid)
        if p is not None:
            v = self.grid.vertex_at(p)
            if v is not None:
                return v
            raise KeyError(f"{pid} is not a track vertex (build the tracks with it as an extra point)")
        raise KeyError(f"unknown endpoint {pid!r}")

    def _edge_ok(self, allowed: frozenset[str]) -> list[bool]:
        ok = self._allowed_cache.get(allowed)
        if ok is None:
            ok = self.grid.allowed_edges(allowed).tolist()
            self._allowed_cache[allowed] = ok
        return ok

    # ---- search --------------------------------------------------------------------------------

    def _run(self, allowed: frozenset[str], src: int, hs: int) -> _Run:
        key = (allowed, src, hs)
        run = self._runs.get(key)
        if run is not None:
            self._runs.move_to_end(key)
            return run
        edge_ok, nbr, nbr_edge, length = self._edge_ok(allowed), self._nbr, self._nbr_edge, self._len_m
        dist: dict[int, float] = {}
        prev: dict[int, int] = {}
        heap: list[tuple[float, int]] = []
        v = nbr[hs][src]
        if v != NO and edge_ok[nbr_edge[hs][src]]:
            s = v * 4 + hs
            dist[s] = length[nbr_edge[hs][src]]
            prev[s] = -1
            heap.append((dist[s], s))
        done: set[int] = set()
        while heap:
            g, s = heapq.heappop(heap)
            if s in done:
                continue
            done.add(s)
            v, h = divmod(s, 4)
            for h2 in (h, (h + 1) & 3, (h + 3) & 3):
                w = nbr[h2][v]
                if w == NO:
                    continue
                e = nbr_edge[h2][v]
                if not edge_ok[e]:
                    continue
                ng = g + length[e] + (0.0 if h2 == h else TURN)
                t = w * 4 + h2
                if ng < dist.get(t, INF):
                    dist[t] = ng
                    prev[t] = s
                    heapq.heappush(heap, (ng, t))
        run = _Run(dist, prev)
        self._runs[key] = run
        if len(self._runs) > self._cache_size:
            self._runs.popitem(last=False)
        return run

    def _polyline(self, run: _Run, a: int, state: int, pa: Point2, pb: Point2) -> Polyline:
        states = []
        while state != -1:
            states.append(state)
            state = run.prev[state]
        pts = [(self._vx[a], self._vy[a])] + [(self._vx[s // 4], self._vy[s // 4]) for s in reversed(states)]
        out = [pts[0]]
        for k in range(1, len(pts) - 1):
            d1 = (pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1])
            d2 = (pts[k + 1][0] - pts[k][0], pts[k + 1][1] - pts[k][1])
            if d1[0] * d2[1] - d1[1] * d2[0] != 0:  # keep corners only
                out.append(pts[k])
        out.append(pts[-1])
        out[0], out[-1] = pa, pb  # exact node coordinates
        return out

    # ---- PathCost ------------------------------------------------------------------------------

    def cost(self, allowed_rooms: frozenset[str], a: str, heading_in: int, b: str, heading_out: int
             ) -> tuple[float, Polyline]:
        allowed = frozenset(allowed_rooms)
        va, vb = self.vertex_of(a), self.vertex_of(b)
        if va == vb:
            return NOT_FOUND
        run = self._run(allowed, va, heading_in)
        state = vb * 4 + heading_out
        d = run.dist.get(state)
        if d is None:
            return NOT_FOUND
        pa = (self._vx[va], self._vy[va])
        pb = (self._vx[vb], self._vy[vb])
        return d, self._polyline(run, va, state, pa, pb)

    def cost_table(self, allowed_rooms: frozenset[str], a: str, b: str) -> list[list[float]]:
        """costs[ho][hi]: leave a along ho, arrive at b along hi (inf where impossible), without building paths."""
        allowed = frozenset(allowed_rooms)
        va, vb = self.vertex_of(a), self.vertex_of(b)
        table = [[INF] * 4 for _ in HEADINGS]
        if va == vb:
            return table
        for ho in HEADINGS:
            dist = self._run(allowed, va, ho).dist
            for hi in HEADINGS:
                table[ho][hi] = dist.get(vb * 4 + hi, INF)
        return table

    def route(self, allowed_rooms: frozenset[str], a: str, b: str, start_headings=HEADINGS, end_headings=HEADINGS,
              forbid: set[int] | frozenset[int] | None = None) -> tuple[float, Polyline, list[int]]:
        """Cheapest path a -> b over the given start/end headings that uses none of the edges in ``forbid``.

        Returns (cost, polyline, edge ids); (inf, [], []) if there is none. Not cached (``forbid`` changes).
        """
        allowed = frozenset(allowed_rooms)
        va, vb = self.vertex_of(a), self.vertex_of(b)
        if va == vb:
            return INF, [], []
        forbid = forbid or ()
        edge_ok, nbr, nbr_edge, length = self._edge_ok(allowed), self._nbr, self._nbr_edge, self._len_m
        dist: dict[int, float] = {}
        prev: dict[int, int] = {}
        heap: list[tuple[float, int]] = []
        for hs in start_headings:
            v = nbr[hs][va]
            e = nbr_edge[hs][va]
            if v != NO and edge_ok[e] and e not in forbid:
                s = v * 4 + hs
                if length[e] < dist.get(s, INF):
                    dist[s] = length[e]
                    prev[s] = -1
                    heapq.heappush(heap, (dist[s], s))
        targets = {vb * 4 + h for h in end_headings}
        done: set[int] = set()
        hit = -1
        while heap:
            g, s = heapq.heappop(heap)
            if s in done:
                continue
            done.add(s)
            if s in targets:
                hit = s
                break
            v, h = divmod(s, 4)
            for h2 in (h, (h + 1) & 3, (h + 3) & 3):
                w = nbr[h2][v]
                if w == NO:
                    continue
                e = nbr_edge[h2][v]
                if not edge_ok[e] or e in forbid:
                    continue
                ng = g + length[e] + (0.0 if h2 == h else TURN)
                t = w * 4 + h2
                if ng < dist.get(t, INF):
                    dist[t] = ng
                    prev[t] = s
                    heapq.heappush(heap, (ng, t))
        if hit < 0:
            return INF, [], []
        run = _Run(dist, prev)
        pa, pb = (self._vx[va], self._vy[va]), (self._vx[vb], self._vy[vb])
        states, st = [], hit
        while st != -1:
            states.append(st)
            st = prev[st]
        states.reverse()
        edges, last = [], va
        for st in states:
            v, h = divmod(st, 4)
            edges.append(nbr_edge[(h + 2) & 3][v])  # the edge we just crossed, seen from the new vertex
            last = v
        return dist[hit], self._polyline(run, va, hit, pa, pb), edges

    def shortest(self, allowed_rooms: frozenset[str], a: str, b: str) -> tuple[float, Polyline]:
        """Cheapest path over all 16 heading combinations."""
        best = NOT_FOUND
        for hi in HEADINGS:
            for ho in HEADINGS:
                c = self.cost(allowed_rooms, a, hi, b, ho)
                if c[0] < best[0]:
                    best = c
        return best

    def distance_field(self, allowed_rooms: frozenset[str], node: str, heading: int, reverse: bool = False):
        """Direction-aware field (see routing/fields.py): forward = cost to arrive at (point, heading) leaving
        ``node`` along ``heading``; reverse = cost to leave (point, heading) and arrive at ``node`` along ``heading``."""
        from eightball.routing import fields
        return fields.reverse_field(self, allowed_rooms, node, heading) if reverse             else fields.forward_field(self, allowed_rooms, node, heading)

    def branching_tree(self, allowed_rooms, hub, nodes):
        raise NotImplementedError("branching tree: Person A, step A13 (routing/tree.py)")
