"""Crude router: A* on a 10 cm raster of the free space (handoff S1.2, BUILD_SPLIT A2).

Good enough for the greedy baseline and the first end-to-end run; the exact solver uses the Hanan-grid router
(A5/A6). Implements ``PathCost.cost`` and ``branching_tree``; it has no distance fields.

Search state is (cell, heading of the last move). Cost is metres plus 0.5 per 90-degree turn, never a reversal.
A path leaves ``a`` along ``heading_in`` and arrives at ``b`` along ``heading_out`` (turn costs at the two
ends are the ring scorer's job). The returned polyline starts and ends exactly on the endpoints: the first and
last runs are moved onto the endpoint's own line, then the result is cleaned and checked against the free
space (falling back to short stubs if the move would clip a wall). Cost is recomputed from the final polyline.
"""
from __future__ import annotations

import heapq
import math

import numpy as np
import shapely
from shapely.geometry import LineString
from shapely.prepared import prep

from eightball import config
from eightball.core.contracts import CleanPlan
from eightball.io import resplan
from eightball.routing import api
from eightball.routing.api import Point2, Polyline

DX = (1, 0, -1, 0)
DY = (0, 1, 0, -1)
INF = float("inf")
CROSS_PENALTY = 5.0  # J cost of one crossing (handoff 1.3)
NOT_FOUND: tuple[float, Polyline] = (INF, [])


def _heading_of(p: Point2, q: Point2) -> int:
    if abs(q[0] - p[0]) >= abs(q[1] - p[1]):
        return api.EAST if q[0] > p[0] else api.WEST
    return api.NORTH if q[1] > p[1] else api.SOUTH


def poly_cost(poly: Polyline, scale: float) -> float:
    """Metres plus 0.5 per bend at interior vertices (the turns at the two ends are not counted)."""
    length = sum(abs(b[0] - a[0]) + abs(b[1] - a[1]) for a, b in zip(poly, poly[1:])) / scale
    bends = 0
    for p, q, r in zip(poly, poly[1:], poly[2:]):
        d1, d2 = (q[0] - p[0], q[1] - p[1]), (r[0] - q[0], r[1] - q[1])
        if not (abs(d1[0] * d2[1] - d1[1] * d2[0]) < 1e-9 * scale * scale and d1[0] * d2[0] + d1[1] * d2[1] > 0):
            bends += 1
    return length + 0.5 * bends


def clean_polyline(pts: list[Point2], tol: float) -> Polyline:
    """Drop duplicate points, straight-through middle vertices and tiny reversals (a spur that doubles back)."""
    out: list[Point2] = []
    for p in pts:
        if not out or abs(p[0] - out[-1][0]) > tol or abs(p[1] - out[-1][1]) > tol:
            out.append(p)
    changed = True
    while changed and len(out) > 2:
        changed = False
        for i in range(1, len(out) - 1):
            p, q, r = out[i - 1], out[i], out[i + 1]
            d1, d2 = (q[0] - p[0], q[1] - p[1]), (r[0] - q[0], r[1] - q[1])
            if abs(d1[0] * d2[1] - d1[1] * d2[0]) <= tol * (abs(d1[0]) + abs(d1[1]) + abs(d2[0]) + abs(d2[1])):
                del out[i]  # straight through, or a reversal along the same line
                changed = True
                break
    return out


class CrudeRouter:
    def __init__(self, cp: CleanPlan, cell_m: float = 0.10):
        self.cp = cp
        self.scale = cp.scale
        self.cell = cell_m * self.scale
        self.step_m = cell_m
        minx, miny, maxx, maxy = cp.inner.bounds
        self.x0, self.y0 = minx, miny
        self.nx = int(math.ceil((maxx - minx) / self.cell))
        self.ny = int(math.ceil((maxy - miny) / self.cell))
        xs = self.x0 + (np.arange(self.nx) + 0.5) * self.cell
        ys = self.y0 + (np.arange(self.ny) + 0.5) * self.cell
        gx, gy = np.meshgrid(xs, ys)
        self.open = shapely.contains_xy(cp.free, gx, gy)
        self.room_ids = list(cp.rooms)
        room_idx = np.full(gx.shape, -1, dtype=np.int32)
        # Room polygons can overlap (a storage alcove cut into a living room): the smaller room owns the cells.
        for k in sorted(range(len(self.room_ids)), key=lambda k: -cp.rooms[self.room_ids[k]].poly.area):
            room_idx[shapely.contains_xy(cp.rooms[self.room_ids[k]].poly, gx, gy)] = k
        self.room_idx = room_idx
        self._free_cover = prep(cp.free.buffer(1e-6 * self.scale))
        self._ok_cache: dict[frozenset[str], list[bool]] = {}
        self._cache: dict[tuple, tuple[float, Polyline]] = {}

    # ---- helpers -------------------------------------------------------------------------------

    def allowed_rooms_for(self, zone_room_ids) -> frozenset[str]:
        """Rooms a zone's cable may use: its own, plus rooms without a node, or everything if the switch is on."""
        if config.ALLOW_THROUGH_OTHER_ZONES:
            return frozenset(self.cp.rooms)
        noded = {n.room_id for n in self.cp.nodes.values()}
        allowed = set(zone_room_ids)
        for rid, room in self.cp.rooms.items():
            if rid not in noded and (config.ALLOW_THROUGH_EXCLUDED or room.eligible):
                allowed.add(rid)
        return frozenset(allowed)

    def point_of(self, pid: str) -> Point2:
        if pid in self.cp.nodes:
            return self.cp.nodes[pid].point
        p = api.parse_point_id(pid)
        if p is None:
            raise KeyError(f"unknown endpoint {pid!r}")
        return p

    def _ok(self, allowed: frozenset[str]) -> list[bool]:
        ok = self._ok_cache.get(allowed)
        if ok is None:
            idx = np.array([k for k, rid in enumerate(self.room_ids) if rid in allowed], dtype=np.int32)
            ok = (self.open & ((self.room_idx < 0) | np.isin(self.room_idx, idx))).ravel().tolist()
            self._ok_cache[allowed] = ok
        return ok

    def _cell_of(self, p: Point2, ok: list[bool]) -> int | None:
        """Index of the open cell nearest to p (searching a small neighbourhood)."""
        ix = min(max(int((p[0] - self.x0) / self.cell), 0), self.nx - 1)
        iy = min(max(int((p[1] - self.y0) / self.cell), 0), self.ny - 1)
        for r in range(0, 6):
            best, best_d = None, INF
            for jy in range(max(iy - r, 0), min(iy + r, self.ny - 1) + 1):
                for jx in range(max(ix - r, 0), min(ix + r, self.nx - 1) + 1):
                    if ok[jy * self.nx + jx]:
                        d = (jx - ix) ** 2 + (jy - iy) ** 2
                        if d < best_d:
                            best, best_d = jy * self.nx + jx, d
            if best is not None:
                return best
        return None

    def _center(self, cell: int) -> Point2:
        iy, ix = divmod(cell, self.nx)
        return (self.x0 + (ix + 0.5) * self.cell, self.y0 + (iy + 0.5) * self.cell)

    # ---- search --------------------------------------------------------------------------------

    def _search(self, ok: list[bool], src: int, dst: int | None, start_headings: tuple[int, ...],
                end_headings: tuple[int, ...], all_targets: set[int] | None = None,
                block: dict[int, int] | None = None):
        """A* (or Dijkstra when dst is None) over (cell, heading). Returns (g, prev, hit_state(s)).

        ``block`` maps cells used by earlier cable to a bit mask (1 = a horizontal run, 2 = a vertical run). A path
        may enter such a cell only by crossing a straight run at right angles, going straight through, and pays
        CROSS_PENALTY (the crossing cost X) for it; it never runs along earlier cable.
        """
        nx, ny, step = self.nx, self.ny, self.step_m
        tx, ty = (dst % nx, dst // nx) if dst is not None else (0, 0)
        use_h = dst is not None
        best: dict[int, float] = {}
        prev: dict[int, int] = {}
        heap: list[tuple[float, float, int]] = []
        sx, sy = src % nx, src // nx
        for hd in start_headings:
            jx, jy = sx + DX[hd], sy + DY[hd]
            if 0 <= jx < nx and 0 <= jy < ny and ok[jy * nx + jx]:
                extra = 0.0
                if block:
                    m = block.get(jy * nx + jx)
                    if m is not None:
                        if m != (2 if hd in (0, 2) else 1):
                            continue
                        extra = CROSS_PENALTY
                st = (jy * nx + jx) * 4 + hd
                best[st] = step + extra
                prev[st] = -1
                hval = (abs(jx - tx) + abs(jy - ty)) * step if use_h else 0.0
                heapq.heappush(heap, (step + extra + hval, step + extra, st))
        remaining = set(all_targets) if all_targets else None
        reached: dict[int, int] = {}  # cell -> state, first arrival (cheapest) when collecting a tree
        while heap:
            _, g, st = heapq.heappop(heap)
            if g > best.get(st, INF):
                continue
            cell, hd = divmod(st, 4)
            if dst is not None and cell == dst and hd in end_headings:
                return best, prev, st
            if remaining is not None and cell in remaining:
                reached[cell] = st
                remaining.discard(cell)
                if not remaining:
                    return best, prev, reached
            cx, cy = cell % nx, cell // nx
            here_blocked = bool(block) and cell in block
            for h2, extra in ((hd, 0.0), ((hd + 1) % 4, 0.5), ((hd + 3) % 4, 0.5)):
                if here_blocked and h2 != hd:
                    continue  # no turning on top of earlier cable
                jx, jy = cx + DX[h2], cy + DY[h2]
                if 0 <= jx < nx and 0 <= jy < ny and ok[jy * nx + jx]:
                    if block:
                        m = block.get(jy * nx + jx)
                        if m is not None:
                            if m != (2 if h2 in (0, 2) else 1):
                                continue
                            extra += CROSS_PENALTY
                    ng = g + step + extra
                    ns = (jy * nx + jx) * 4 + h2
                    if ng < best.get(ns, INF):
                        best[ns] = ng
                        prev[ns] = st
                        hval = (abs(jx - tx) + abs(jy - ty)) * step if use_h else 0.0
                        heapq.heappush(heap, (ng + hval, ng, ns))
        return best, prev, (reached if remaining is not None else None)

    @staticmethod
    def _trace(prev: dict[int, int], state: int) -> list[int]:
        cells = []
        while state != -1:
            cells.append(state // 4)
            state = prev[state]
        return cells[::-1]

    # ---- polyline ------------------------------------------------------------------------------

    def _build(self, cells: list[int], a: Point2, b: Point2, src_cell: int, dst_cell: int,
               start_ok: tuple[int, ...] = api.HEADINGS, end_ok: tuple[int, ...] = api.HEADINGS) -> Polyline | None:
        """Polyline from the exact point a to b along the cell path. Prefers a candidate whose first and last
        segments head in start_ok / end_ok (the moved-runs version first, then short stubs); any valid one if none."""
        tol = 1e-6 * self.scale
        centers = [self._center(c) for c in [src_cell, *cells]]
        if cells and cells[-1] != dst_cell:
            centers.append(self._center(dst_cell))
        runs: list[list] = []  # [axis, coordinate]; axis 0 = horizontal (y fixed), 1 = vertical (x fixed)
        for p, q in zip(centers, centers[1:]):
            axis = 0 if abs(q[1] - p[1]) < tol else 1
            if not runs or runs[-1][0] != axis:
                runs.append([axis, p[1] if axis == 0 else p[0]])

        candidates: list[Polyline] = []
        if runs:
            lines = [list(r) for r in runs]
            lines[0][1] = a[1] if lines[0][0] == 0 else a[0]
            lines[-1][1] = b[1] if lines[-1][0] == 0 else b[0]
            if len(lines) == 1:
                if lines[0][0] == 0:
                    mid = (a[0] + b[0]) / 2
                    shifted = [a, (mid, a[1]), (mid, b[1]), b]
                else:
                    mid = (a[1] + b[1]) / 2
                    shifted = [a, (a[0], mid), (b[0], mid), b]
                if (abs(a[1] - b[1]) < tol and lines[0][0] == 0) or (abs(a[0] - b[0]) < tol and lines[0][0] == 1):
                    shifted = [a, b]
            else:
                shifted = [a]
                for l1, l2 in zip(lines, lines[1:]):
                    shifted.append((l2[1], l1[1]) if l1[0] == 0 else (l1[1], l2[1]))
                shifted.append(b)
            candidates.append(clean_polyline(shifted, tol))
        c0, c1 = centers[0], centers[-1]
        for first_h in (True, False):
            for last_h in (True, False):
                head = [a, (c0[0], a[1]) if first_h else (a[0], c0[1]), c0]
                tail = [c1, (c1[0], b[1]) if last_h else (b[0], c1[1]), b]
                candidates.append(clean_polyline([*head, *centers[1:-1], *tail], tol))
        fallback = None
        for poly in candidates:
            if len(poly) < 2 or not all(abs(p[0] - q[0]) < tol or abs(p[1] - q[1]) < tol for p, q in zip(poly, poly[1:]))                     or not self._free_cover.covers(LineString(poly)):
                continue
            fallback = fallback or poly
            if _heading_of(poly[0], poly[1]) in start_ok and _heading_of(poly[-2], poly[-1]) in end_ok:
                return poly
        return fallback

    # ---- PathCost ------------------------------------------------------------------------------

    def shortest(self, allowed: frozenset[str], a: str, b: str, heading_in: int | None = None,
                 heading_out: int | None = None) -> tuple[float, Polyline]:
        """Cheapest path a -> b; headings None = any."""
        key = (allowed, a, b, heading_in, heading_out)
        if key in self._cache:
            return self._cache[key]
        pa, pb = self.point_of(a), self.point_of(b)
        ok = self._ok(allowed)
        ca, cb = self._cell_of(pa, ok), self._cell_of(pb, ok)
        result = NOT_FOUND
        if ca is not None and cb is not None:
            hs = api.HEADINGS if heading_in is None else (heading_in,)
            he = api.HEADINGS if heading_out is None else (heading_out,)
            if ca == cb:
                poly = self._build([], pa, pb, ca, cb)
            else:
                _, prev, hit = self._search(ok, ca, cb, hs, he)
                poly = self._build(self._trace(prev, hit), pa, pb, ca, cb) if isinstance(hit, int) else None
            if poly is not None:
                result = (poly_cost(poly, self.scale), poly)
        self._cache[key] = result
        return result

    def cells_of(self, poly: Polyline) -> dict[int, int]:
        """Raster cells a polyline passes through -> bit mask (1 horizontal run, 2 vertical run)."""
        cells: dict[int, int] = {}
        for p, q in zip(poly, poly[1:]):
            bit = 1 if abs(q[1] - p[1]) < abs(q[0] - p[0]) else 2
            n = max(1, int(math.ceil(max(abs(q[0] - p[0]), abs(q[1] - p[1])) / (self.cell / 2))))
            for k in range(n + 1):
                x = p[0] + (q[0] - p[0]) * k / n
                y = p[1] + (q[1] - p[1]) * k / n
                ix = min(max(int((x - self.x0) / self.cell), 0), self.nx - 1)
                iy = min(max(int((y - self.y0) / self.cell), 0), self.ny - 1)
                c = iy * self.nx + ix
                cells[c] = cells.get(c, 0) | bit
        return cells

    def route(self, allowed: frozenset[str], a: str, b: str, avoid: dict[int, int] | None = None,
              start_headings: tuple[int, ...] = api.HEADINGS, end_headings: tuple[int, ...] = api.HEADINGS
              ) -> tuple[float, Polyline]:
        """Cheapest path a -> b leaving a along one of start_headings and arriving along one of end_headings.

        ``avoid`` is ``cells_of`` of the earlier legs of the ring (the endpoints' own cells stay usable): the path
        never runs along them, so a ring doesn't overlap itself, but it may cross them at right angles, at a cost.
        """
        pa, pb = self.point_of(a), self.point_of(b)
        base = self._ok(allowed)
        ca, cb = self._cell_of(pa, base), self._cell_of(pb, base)
        if ca is None or cb is None or ca == cb:
            return self.shortest(allowed, a, b)
        block = None
        if avoid:
            block = {c: m for c, m in avoid.items() if c != ca and c != cb}
        _, prev, hit = self._search(base, ca, cb, tuple(start_headings), tuple(end_headings), block=block)
        poly = None
        if isinstance(hit, int):
            poly = self._build(self._trace(prev, hit), pa, pb, ca, cb, tuple(start_headings), tuple(end_headings))
        return (poly_cost(poly, self.scale), poly) if poly is not None else NOT_FOUND

    def cost(self, allowed_rooms: frozenset[str], a: str, heading_in: int, b: str, heading_out: int
             ) -> tuple[float, Polyline]:
        return self.shortest(frozenset(allowed_rooms), a, b, heading_in, heading_out)

    def distance_field(self, allowed_rooms, node, heading, reverse=False):
        raise NotImplementedError("the crude router has no distance fields; see routing/fields.py (step A9)")

    def branching_tree(self, allowed_rooms: frozenset[str], hub: Point2, nodes: list[str]) -> dict[str, Polyline]:
        """Shortest-path tree from the hub to every node: node_id -> polyline starting at the hub."""
        allowed = frozenset(allowed_rooms)
        ok = self._ok(allowed)
        ch = self._cell_of(hub, ok)
        out: dict[str, Polyline] = {}
        if ch is None:
            return out
        node_cells = {n: self._cell_of(self.point_of(n), ok) for n in nodes}
        targets = {c for c in node_cells.values() if c is not None and c != ch}
        _, prev, reached = self._search(ok, ch, None, api.HEADINGS, api.HEADINGS, all_targets=targets) \
            if targets else ({}, {}, {})
        for n, c in node_cells.items():
            if c is None:
                continue
            pn = self.point_of(n)
            if c == ch:
                poly = self._build([], hub, pn, ch, c)
            elif c in reached:
                poly = self._build(self._trace(prev, reached[c]), hub, pn, ch, c)
            else:
                poly = None
            if poly is not None:
                out[n] = poly
        return out
