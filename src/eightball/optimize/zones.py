"""Zone enumeration (handoff 6 step 4, BUILD_SPLIT A7).

A zone is a set of eligible rooms (each with its node) that
  * has at most MAX_NODES_PER_HUB rooms and at most MAX_AREA_M2 of room area, and
  * is connected through door / passage links between rooms of the set only
    (a path through a bathroom or stair does not count: ZONE_VIA_EXCLUDED_ROOMS is off).
Every such set is listed once, by the ESU subgraph enumeration over bit masks.
"""
from __future__ import annotations

from dataclasses import dataclass

from eightball import config
from eightball.core.contracts import CleanPlan


@dataclass(frozen=True)
class Zone:
    zone_id: str
    room_ids: tuple[str, ...]   # sorted
    area_m2: float
    n_nodes: int
    mask: int                   # bit k = rooms[k] of the plan's zone room list


def zone_rooms(cp: CleanPlan) -> list[str]:
    """Eligible rooms that carry a node, in canonical (room id) order: the rooms a zone partition must cover."""
    with_node = {n.room_id for n in cp.nodes.values()}
    return [rid for rid, r in cp.rooms.items() if r.eligible and rid in with_node]


def link_graph(cp: CleanPlan, rooms: list[str]) -> list[int]:
    """Adjacency bit masks over ``rooms`` using door / passage links between those rooms only."""
    index = {rid: k for k, rid in enumerate(rooms)}
    adj = [0] * len(rooms)
    for a, b in cp.links.edges:
        if a in index and b in index:
            adj[index[a]] |= 1 << index[b]
            adj[index[b]] |= 1 << index[a]
    if config.ZONE_VIA_EXCLUDED_ROOMS:  # switch: let a path through excluded rooms (bathroom, stair) connect rooms
        eligible = set(rooms)
        reach: dict[str, set[str]] = {}
        for rid in rooms:
            seen, stack = set(), [rid]
            while stack:
                cur = stack.pop()
                for nb in cp.links[cur]:
                    if nb in seen or nb == rid:
                        continue
                    if nb in eligible:
                        reach.setdefault(rid, set()).add(nb)
                    elif not cp.rooms[nb].eligible:
                        seen.add(nb)
                        stack.append(nb)
        for a, others in reach.items():
            for b in others:
                adj[index[a]] |= 1 << index[b]
                adj[index[b]] |= 1 << index[a]
    return adj


def enumerate_zones(cp: CleanPlan, rooms: list[str] | None = None) -> list[Zone]:
    rooms = zone_rooms(cp) if rooms is None else rooms
    n = len(rooms)
    adj = link_graph(cp, rooms)
    area = [cp.rooms[r].area_m2 for r in rooms]
    max_rooms = int(config.MAX_NODES_PER_HUB)
    max_area = float(config.MAX_AREA_M2) + 1e-9
    masks: list[int] = []

    def neighbours(mask: int) -> int:
        out = 0
        m = mask
        while m:
            low = m & -m
            out |= adj[low.bit_length() - 1]
            m ^= low
        return out

    def extend(sub: int, ext: int, root: int, size: int, total: float) -> None:
        masks.append(sub)
        if size == max_rooms:
            return
        reach = sub | neighbours(sub)
        while ext:
            low = ext & -ext
            ext ^= low
            w = low.bit_length() - 1
            if total + area[w] > max_area:
                continue
            fresh = adj[w] & ~reach & ~((1 << (root + 1)) - 1)  # only rooms after the root, not yet adjacent to sub
            extend(sub | low, ext | fresh, root, size + 1, total + area[w])

    for v in range(n):
        if area[v] <= max_area:
            extend(1 << v, adj[v] & ~((1 << (v + 1)) - 1), v, 1, area[v])

    zones = []
    for mask in masks:
        ids = tuple(rooms[k] for k in range(n) if mask >> k & 1)
        zones.append(Zone(zone_id="", room_ids=ids, area_m2=sum(cp.rooms[r].area_m2 for r in ids),
                          n_nodes=len(ids), mask=mask))
    zones.sort(key=lambda z: (z.n_nodes, z.room_ids))
    return [Zone(f"Z{k}", z.room_ids, z.area_m2, z.n_nodes, z.mask) for k, z in enumerate(zones)]
