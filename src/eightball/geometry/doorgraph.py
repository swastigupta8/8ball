"""Our own door / open-passage graph (handoff 8.4). The stored ResPlan graph is not trusted.

Idea A finds passages from room boundaries and walls. Idea C flood-fills the free space and is used to
cross-check A; where they disagree the link is not a passage (UNSURE_GAP_IS_WALL).
"""
from __future__ import annotations

from collections import deque

import numpy as np
import shapely
from shapely.geometry import LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

from eightball import config
from eightball.core.contracts import Door, Passage, Room
from eightball.io import resplan

# Rooms outside the building: no cable, no links.
OUTDOOR = ("land", "garden", "pool", "parking")
CONTACT_KEEP = 0.25  # drop rooms with less than 25% of the best contact length


def door_polygons(doors: BaseGeometry, front_door: BaseGeometry) -> list[Polygon]:
    """Each door as one polygon, in a deterministic order; the front door is excluded."""
    out = []
    for d in resplan.parts(doors):
        if d.area <= 0:
            continue
        if not front_door.is_empty and d.intersection(front_door).area > 0.5 * d.area:
            continue
        out.append(d)
    out.sort(key=lambda p: (round(p.bounds[0]), round(p.bounds[1]), round(p.bounds[2]), round(p.bounds[3])))
    return out


def wall_depth_units(plan: dict, doors: list[Polygon], scale: float) -> tuple[float, bool]:
    """Wall thickness in drawing units. Falls back to the doors' own thickness if the stored value is odd."""
    wd = plan.get("wall_depth")
    try:
        wd = float(wd)
    except (TypeError, ValueError):
        wd = 0.0
    if 0.03 * scale <= wd <= 0.6 * scale:
        return wd, False
    thick = [min(d.bounds[2] - d.bounds[0], d.bounds[3] - d.bounds[1]) for d in doors]
    if thick:
        return float(np.median(thick)), True
    return 0.2 * scale, True


def link_door(door: Polygon, rooms: dict[str, Room], depth: float) -> tuple[str, str] | None:
    """The two rooms a door joins: the ones with the largest contact with the door buffered by 0.6 * depth."""
    buf = door.buffer(0.6 * depth)
    contacts: list[tuple[float, str]] = []
    for rid, room in rooms.items():
        if room.type in OUTDOOR or not room.poly.intersects(buf):
            continue
        contact = room.poly.boundary.intersection(buf).length
        if contact <= 0:
            contact = room.poly.intersection(buf).area / max(depth, 1e-9)
        if contact > 0:
            contacts.append((contact, rid))
    if len(contacts) < 2:
        return None
    contacts.sort(key=lambda c: (-c[0], c[1]))
    best = contacts[0][0]
    kept = [rid for c, rid in contacts if c >= CONTACT_KEEP * best][:2]
    return (kept[0], kept[1]) if len(kept) == 2 else None


def make_doors(door_polys: list[Polygon], rooms: dict[str, Room], depth: float
               ) -> tuple[dict[str, Door], list[str]]:
    doors: dict[str, Door] = {}
    flags: list[str] = []
    for k, poly in enumerate(door_polys):
        did = f"door_{k}"
        pair = link_door(poly, rooms, depth)
        if pair is None:
            flags.append(f"door_unlinked:{did}")
            continue
        minx, miny, maxx, maxy = poly.bounds
        c = poly.centroid
        axis = "h" if (maxx - minx) >= (maxy - miny) else "v"
        doors[did] = Door(id=did, poly=poly, rooms=pair, center=(c.x, c.y), axis=axis)
    return doors, flags


def find_passages(rooms: dict[str, Room], walls: BaseGeometry, windows: BaseGeometry, front_door: BaseGeometry,
                  door_polys: list[Polygon], depth: float, scale: float) -> list[tuple[str, str, LineString]]:
    """Idea A: wall-free stretches of shared room boundary that are at least PASSAGE_MIN_WIDTH_M long."""
    one_cm = 0.01 * scale
    blockers = unary_union([walls.buffer(one_cm), windows.buffer(one_cm), front_door.buffer(one_cm),
                            *[d.buffer(one_cm) for d in door_polys]])
    min_len = float(config.PASSAGE_MIN_WIDTH_M) * scale
    ids = [rid for rid, r in rooms.items() if r.type not in OUTDOOR]
    found: list[tuple[str, str, LineString]] = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ra, rb = rooms[a].poly, rooms[b].poly
            if ra.distance(rb) > 1.5 * depth:
                continue
            stretch = ra.boundary.intersection(rb.buffer(1.5 * depth))
            stretch = stretch.difference(blockers)
            lines = [g for g in getattr(stretch, "geoms", [stretch]) if isinstance(g, LineString) and not g.is_empty]
            if not lines:
                continue
            merged = linemerge(lines)
            for seg in getattr(merged, "geoms", [merged]):
                if seg.length >= min_len:
                    found.append((a, b, seg))
    return found


def flood_connected(a: Polygon, b: Polygon, blockers: BaseGeometry, reach: float, cell: float) -> bool:
    """Idea C: can a flood fill from room a reach room b without crossing a wall, window or door?"""
    region = unary_union([a.buffer(reach), b.buffer(reach)])
    minx, miny, maxx, maxy = region.bounds
    xs = np.arange(minx + cell / 2, maxx, cell)
    ys = np.arange(miny + cell / 2, maxy, cell)
    if len(xs) == 0 or len(ys) == 0:
        return False
    gx, gy = np.meshgrid(xs, ys)
    free = shapely.contains_xy(region, gx, gy) & ~shapely.contains_xy(blockers, gx, gy)
    in_a = free & shapely.contains_xy(a, gx, gy)
    in_b = free & shapely.contains_xy(b, gx, gy)
    if not in_a.any() or not in_b.any():
        return False
    start = tuple(np.argwhere(in_a)[0])
    seen = np.zeros_like(free)
    seen[start] = True
    queue = deque([start])
    ny, nx = free.shape
    while queue:
        y, x = queue.popleft()
        if in_b[y, x]:
            return True
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < ny and 0 <= xx < nx and free[yy, xx] and not seen[yy, xx]:
                seen[yy, xx] = True
                queue.append((yy, xx))
    return False


def confirm_passages(candidates: list[tuple[str, str, LineString]], rooms: dict[str, Room], walls: BaseGeometry,
                     windows: BaseGeometry, front_door: BaseGeometry, door_polys: list[Polygon], depth: float,
                     scale: float, cell_m: float = 0.025) -> tuple[list[tuple[str, str, LineString]], list[str]]:
    """Keep only passages that the flood fill also finds. Disagreements become flags (unsure gap = wall)."""
    blockers = unary_union([walls, windows, front_door, *door_polys])
    kept, flags = [], []
    for a, b, seg in candidates:
        if flood_connected(rooms[a].poly, rooms[b].poly, blockers, 1.5 * depth, cell_m * scale):
            kept.append((a, b, seg))
        else:
            flags.append(f"passage_rejected_by_flood:{a},{b}")
    return kept, flags
