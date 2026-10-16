"""Hanan track grid (handoff 6 step 2, BUILD_SPLIT A5).

Lines run through the corners of the shrunk free space, the middle of every door and passage with parallel lanes
LANE_SPACING_M either side, every node, and any extra points (hub candidates). Lines closer than MERGE_LINES_M
are merged; node lines are never moved or dropped; lane lines are kept unless within 2 mm of another kept line. Vertices are the line
crossings inside the free space; an edge joins neighbouring vertices along a line when it stays in the free space.
Every edge carries the rooms it lies in (a bit mask over ``room_ids``, so "allowed rooms" is one AND) and its
primary room (the smallest one).

Coordinates are in drawing units, like the CleanPlan.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shapely

from eightball import config
from eightball.core.contracts import CleanPlan
from eightball.io import resplan
from eightball.routing.api import EAST, NORTH, SOUTH, WEST

NO = -1
MAX_ROOMS = 63  # edge room masks are int64 bit masks


@dataclass
class TrackGrid:
    xs: np.ndarray            # vertical line positions (x), ascending
    ys: np.ndarray            # horizontal line positions (y), ascending
    vid: np.ndarray           # (len(xs), len(ys)) vertex id, -1 where the crossing is outside the free space
    vx: np.ndarray            # vertex coordinates
    vy: np.ndarray
    nbr: np.ndarray           # (4, n_vertices): neighbour vertex in heading h (EAST, NORTH, WEST, SOUTH), -1 if none
    nbr_edge: np.ndarray      # (4, n_vertices): the edge to that neighbour
    e_a: np.ndarray           # edge endpoints (vertex ids)
    e_b: np.ndarray
    e_len: np.ndarray         # length in drawing units
    e_axis: np.ndarray        # 0 = horizontal (runs along x), 1 = vertical
    e_rooms: np.ndarray       # int64 bit mask of the rooms the edge lies in (0 = none, e.g. a door gap)
    e_room: np.ndarray        # index of the primary room (smallest), -1 if none
    room_ids: list[str]
    node_vertex: dict[str, int] = field(default_factory=dict)
    scale: float = 1.0

    @property
    def n_vertices(self) -> int:
        return len(self.vx)

    @property
    def n_edges(self) -> int:
        return len(self.e_a)

    def room_mask(self, rooms) -> int:
        """Bit mask of a set of room ids."""
        index = {r: k for k, r in enumerate(self.room_ids)}
        mask = 0
        for r in rooms:
            mask |= 1 << index[r]
        return mask

    def allowed_edges(self, allowed_rooms) -> np.ndarray:
        """Boolean per edge: every room the edge lies in is allowed (edges in no room are always allowed)."""
        forbidden = ((1 << len(self.room_ids)) - 1) & ~self.room_mask(allowed_rooms)
        return (self.e_rooms & np.int64(forbidden)) == 0

    def edge_room(self, e: int) -> str | None:
        k = int(self.e_room[e])
        return self.room_ids[k] if k >= 0 else None

    def vertex_at(self, point, tol: float | None = None) -> int | None:
        """The vertex at a point (within tol, default 1 mm), or None."""
        tol = 0.001 * self.scale if tol is None else tol
        i = int(np.argmin(np.abs(self.xs - point[0])))
        j = int(np.argmin(np.abs(self.ys - point[1])))
        if abs(self.xs[i] - point[0]) <= tol and abs(self.ys[j] - point[1]) <= tol and self.vid[i, j] >= 0:
            return int(self.vid[i, j])
        return None


def _merge(others: list[float], lanes: list[float], protected: list[float], tol: float, tight: float) -> np.ndarray:
    """Merge lines. Node lines are never moved or dropped. Door/passage/node lane lines are kept unless they sit
    within ``tight`` (about 2 mm) of a kept line, where they would count as the same line. Other lines within
    ``tol`` (1 cm) of a kept line, or of each other, are dropped."""
    kept: list[float] = []
    for v in sorted(protected):  # node lines: only values within 0.1 mm collapse into one line
        if not kept or v - kept[-1] > tight / 20:
            kept.append(v)
    for v in sorted(lanes):
        if all(abs(v - k) > tight for k in kept):
            kept.append(v)
    kept.sort()
    add: list[float] = []
    for v in sorted(others):
        if all(abs(v - k) > tol for k in kept) and all(abs(v - k) > tol for k in add):
            add.append(v)
    return np.array(sorted(kept + add))


def build_tracks(cp: CleanPlan, extra_points=(), attach: bool = True, node_lanes: bool = True) -> TrackGrid:
    s = cp.scale
    tol = float(config.MERGE_LINES_M) * s
    lane = float(config.LANE_SPACING_M) * s

    px = [n.point[0] for n in cp.nodes.values()]
    py = [n.point[1] for n in cp.nodes.values()]
    lane_x: list[float] = []
    lane_y: list[float] = []
    if node_lanes:  # spare parallel lines beside every node line, for cable that has to pass a node's row/column again
        for x in px:
            lane_x += [x - lane, x + lane]
        for y in py:
            lane_y += [y - lane, y + lane]
    other_x: list[float] = [p[0] for p in extra_points]   # hub candidates: lines through them, but they never
    other_y: list[float] = [p[1] for p in extra_points]   # crowd out a node or lane line
    for door in cp.doors.values():
        cx, cy = door.center
        if door.axis == "h":  # wall runs along x, so the cable crosses it along y
            lane_x += [cx - lane, cx, cx + lane]
        else:
            lane_y += [cy - lane, cy, cy + lane]
    for passage in cp.passages.values():
        (x0, y0), (x1, y1) = passage.seg.coords[0], passage.seg.coords[-1]
        if abs(y1 - y0) <= abs(x1 - x0):  # runs along x: the boundary is a horizontal line, cross it vertically
            lane_x += [(x0 + x1) / 2 - lane, (x0 + x1) / 2, (x0 + x1) / 2 + lane]
            other_y += [(y0 + y1) / 2]
            other_x += [x0, x1]
        else:
            lane_y += [(y0 + y1) / 2 - lane, (y0 + y1) / 2, (y0 + y1) / 2 + lane]
            other_x += [(x0 + x1) / 2]
            other_y += [y0, y1]
    for poly in resplan.parts(cp.free):
        for ring in (poly.exterior, *poly.interiors):
            c = np.asarray(ring.coords)
            other_x += c[:, 0].tolist()
            other_y += c[:, 1].tolist()

    tight = 0.002 * s
    xs = _merge(other_x, lane_x, px, tol, tight)
    ys = _merge(other_y, lane_y, py, tol, tight)

    slack = 0.5 * tol  # edges may sit up to half a merge distance outside the shrunk free space (still > 3 cm from walls)
    cover = shapely.buffer(cp.free, slack, join_style="mitre", mitre_limit=2.0)
    shapely.prepare(cover)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    inside = shapely.covers(cover, shapely.points(gx, gy))
    vid = np.full(inside.shape, NO, dtype=np.int32)
    vid[inside] = np.arange(int(inside.sum()), dtype=np.int32)
    vx, vy = gx[inside], gy[inside]

    # candidate edges between neighbouring lines; keep those whose midpoint (and so, between lines, the whole
    # segment) lies in the free space
    ea, eb, axis, mx, my = [], [], [], [], []
    both = inside[:-1, :] & inside[1:, :]
    ii, jj = np.nonzero(both)
    midx, midy = (xs[ii] + xs[ii + 1]) / 2, ys[jj]
    ok = shapely.covers(cover, shapely.points(midx, midy))
    ii, jj, midx, midy = ii[ok], jj[ok], midx[ok], midy[ok]
    ea.append(vid[ii, jj]); eb.append(vid[ii + 1, jj]); axis.append(np.zeros(len(ii), dtype=np.int8))
    mx.append(midx); my.append(midy)
    h_edges = (ii, jj)
    both = inside[:, :-1] & inside[:, 1:]
    ii2, jj2 = np.nonzero(both)
    midx, midy = xs[ii2], (ys[jj2] + ys[jj2 + 1]) / 2
    ok = shapely.covers(cover, shapely.points(midx, midy))
    ii2, jj2, midx, midy = ii2[ok], jj2[ok], midx[ok], midy[ok]
    ea.append(vid[ii2, jj2]); eb.append(vid[ii2, jj2 + 1]); axis.append(np.ones(len(ii2), dtype=np.int8))
    mx.append(midx); my.append(midy)
    e_a, e_b = np.concatenate(ea), np.concatenate(eb)
    e_axis = np.concatenate(axis)
    mx, my = np.concatenate(mx), np.concatenate(my)
    e_len = np.abs(vx[e_b] - vx[e_a]) + np.abs(vy[e_b] - vy[e_a])

    # rooms of every edge
    room_ids = list(cp.rooms)
    if len(room_ids) > MAX_ROOMS:  # the room bit mask is an int64; solve() falls back to greedy on this error
        raise ValueError(f"{len(room_ids)} rooms: the track grid's room mask holds at most {MAX_ROOMS}")
    e_rooms = np.zeros(len(e_a), dtype=np.int64)
    primary = np.full(len(e_a), -1, dtype=np.int32)
    primary_area = np.full(len(e_a), np.inf)
    pts = shapely.points(mx, my)
    for k, rid in enumerate(room_ids):
        poly = cp.rooms[rid].poly
        hit = shapely.covers(poly, pts)
        e_rooms[hit] |= np.int64(1) << np.int64(k)
        better = hit & (poly.area < primary_area)
        primary[better] = k
        primary_area[better] = poly.area

    nv = len(vx)
    nbr = np.full((4, nv), NO, dtype=np.int32)
    nbr_edge = np.full((4, nv), NO, dtype=np.int32)
    ids = np.arange(len(e_a), dtype=np.int32)
    nbr[EAST, e_a[e_axis == 0]] = e_b[e_axis == 0]
    nbr_edge[EAST, e_a[e_axis == 0]] = ids[e_axis == 0]
    nbr[WEST, e_b[e_axis == 0]] = e_a[e_axis == 0]
    nbr_edge[WEST, e_b[e_axis == 0]] = ids[e_axis == 0]
    nbr[NORTH, e_a[e_axis == 1]] = e_b[e_axis == 1]
    nbr_edge[NORTH, e_a[e_axis == 1]] = ids[e_axis == 1]
    nbr[SOUTH, e_b[e_axis == 1]] = e_a[e_axis == 1]
    nbr_edge[SOUTH, e_b[e_axis == 1]] = ids[e_axis == 1]

    grid = TrackGrid(xs=xs, ys=ys, vid=vid, vx=vx, vy=vy, nbr=nbr, nbr_edge=nbr_edge, e_a=e_a, e_b=e_b,
                     e_len=e_len, e_axis=e_axis, e_rooms=e_rooms, e_room=primary, room_ids=room_ids, scale=s)
    for n in cp.nodes.values():
        v = grid.vertex_at(n.point, 0.0002 * s)
        if v is not None:
            grid.node_vertex[n.id] = v
    if attach:
        cp.tracks = grid
    return grid
