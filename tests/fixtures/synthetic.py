"""Hand-built plans in ResPlan's dict format, plus hand-checked answers (BUILD_SPLIT 3.1 item 7).

scale = 1 (inner.area == area), so drawing units are metres. Plan ids 900001+ never clash with ResPlan.

synth_1hub (900001): 8 x 4 m flat, living | bedroom, one door at x = 4, y 1.5-2.5.
synth_2hub (900002): 24 x 6 m row of 6 rooms (living, kitchen, bedroom, bedroom, storage, bedroom),
    doors at x = 4, 8, 12, 16, 20 (y 2.5-3.5). 138 m^2 and 6 nodes, so at least 2 hubs.
Walls are 0.2 m thick; outer walls sit outside `inner`; door gaps are already cut out of the walls.

Answers route along the door-centre line and return on a lane 3 cm below it (handoff: parallel runs on
different lines don't overlap). Their metrics were computed by hand; see the docstrings.
"""
from __future__ import annotations

import networkx as nx
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union

EMPTY = Polygon()
WALL_T = 0.2


def _plan(plan_id: int, inner: Polygon, rooms: dict, inner_walls: list, doors: list, windows: list,
          front_door: Polygon) -> dict:
    minx, miny, maxx, maxy = inner.bounds
    outer = box(minx - WALL_T, miny - WALL_T, maxx + WALL_T, maxy + WALL_T).difference(inner)
    plan = {k: EMPTY for k in ("living", "bedroom", "bathroom", "kitchen", "storage", "stair", "balcony",
                               "land", "garden", "pool", "parking", "neighbor")}
    for k, polys in rooms.items():
        plan[k] = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    plan.update({
        "id": plan_id,
        "inner": inner,
        "wall": unary_union([outer, *inner_walls]),
        "door": unary_union(doors),
        "window": unary_union(windows),
        "front_door": front_door,
        "area": inner.area,  # scale = sqrt(inner.area / area) = 1
        "net_area": 0.0,
        "wall_depth": WALL_T,
        "graph": nx.Graph(),
    })
    return plan


def synth_1hub() -> dict:
    return _plan(
        900001, box(0, 0, 8, 4),
        rooms={"living": [box(0, 0, 3.9, 4)], "bedroom": [box(4.1, 0, 8, 4)]},
        inner_walls=[box(3.9, 0, 4.1, 1.5), box(3.9, 2.5, 4.1, 4)],
        doors=[box(3.9, 1.5, 4.1, 2.5)],
        windows=[box(1, 4, 2, 4 + WALL_T)],
        front_door=box(0.5, -WALL_T, 1.5, 0),
    )


SLOTS_2HUB = [(0.0, 3.9), (4.1, 7.9), (8.1, 11.9), (12.1, 15.9), (16.1, 19.9), (20.1, 24.0)]
TYPES_2HUB = ["living", "kitchen", "bedroom", "bedroom", "storage", "bedroom"]
# Canonical room ids (resplan.room_parts order) of each slot, left to right:
IDS_2HUB = ["living_0", "kitchen_0", "bedroom_0", "bedroom_1", "storage_0", "bedroom_2"]


def synth_2hub() -> dict:
    rooms: dict[str, list] = {}
    for (x0, x1), t in zip(SLOTS_2HUB, TYPES_2HUB):
        rooms.setdefault(t, []).append(box(x0, 0, x1, 6))
    inner_walls, doors = [], []
    for k in range(1, 6):
        x = 4.0 * k
        inner_walls += [box(x - 0.1, 0, x + 0.1, 2.5), box(x - 0.1, 3.5, x + 0.1, 6)]
        doors.append(box(x - 0.1, 2.5, x + 0.1, 3.5))
    return _plan(900002, box(0, 0, 24, 6), rooms, inner_walls, doors,
                 windows=[box(1, 6, 2, 6 + WALL_T), box(9, 6, 10, 6 + WALL_T)],
                 front_door=box(0.5, -WALL_T, 1.5, 0))


PLANS = {900001: synth_1hub, 900002: synth_2hub}

NODES = {
    900001: [
        {"node_id": "N1", "room_id": "living_0", "point": [1.95, 2.0]},
        {"node_id": "N2", "room_id": "bedroom_0", "point": [6.05, 2.0]},
    ],
    900002: [
        {"node_id": "N1", "room_id": "living_0", "point": [1.95, 3.0]},
        {"node_id": "N2", "room_id": "bedroom_0", "point": [10.0, 3.0]},
        {"node_id": "N3", "room_id": "bedroom_1", "point": [14.0, 3.0]},
        {"node_id": "N4", "room_id": "bedroom_2", "point": [22.05, 3.0]},
        {"node_id": "N5", "room_id": "kitchen_0", "point": [6.0, 3.0]},
        {"node_id": "N6", "room_id": "storage_0", "point": [18.0, 3.0]},
    ],
}


def _hub(hub_id, point, room_id, room_ids, node_ids, legs, area_m2, length_m):
    seq = [hub_id, *node_ids, hub_id]
    return {"hub_id": hub_id, "point": point, "room_id": room_id, "room_ids": room_ids, "node_ids": node_ids,
            "sequence": seq,
            "legs": [{"from": seq[k], "to": seq[k + 1], "polyline": poly} for k, poly in enumerate(legs)],
            "area_m2": area_m2, "length_m": length_m}


def _answer(plan_id, hubs, metrics, solver="fixture"):
    return {"schema_version": "8ball-answer/1", "plan_id": plan_id, "scale": 1.0, "nodes": NODES[plan_id],
            "hubs": hubs, "metrics": metrics,
            "meta": {"solver": solver, "runtime_s": 0.0, "config_hash": "fixture", "seed": 0,
                     "best_additive_cost": None, "min_hubs_bound": None, "j_floor": None}}


def answer_1hub() -> dict:
    """L = 0.03 + 0.95 + 4.10 + 0.03 + 5.05 = 10.16; bends at (1,2), N2, (6.05,1.97), H1 = 4; J = 12.16."""
    hub = _hub("H1", [1.0, 1.97], "living_0", ["living_0", "bedroom_0"], ["N1", "N2"], [
        [[1.0, 1.97], [1.0, 2.0], [1.95, 2.0]],
        [[1.95, 2.0], [6.05, 2.0]],
        [[6.05, 2.0], [6.05, 1.97], [1.0, 1.97]],
    ], 31.2, 10.16)
    return _answer(900001, [hub], {"H": 1, "L": 10.16, "X": 0, "O": 0.0, "B": 4, "J": 12.16})


def _ring1(hub_point=(1.0, 2.97), return_leg=None):
    hx, hy = hub_point
    return _hub("H1", [hx, hy], "living_0", ["living_0", "kitchen_0", "bedroom_0"], ["N1", "N5", "N2"], [
        [[hx, hy], [hx, 3.0], [1.95, 3.0]],
        [[1.95, 3.0], [6.0, 3.0]],
        [[6.0, 3.0], [10.0, 3.0]],
        return_leg or [[10.0, 3.0], [10.0, 2.97], [hx, hy]],
    ], 69.0, 18.06)


def _ring2():
    return _hub("H2", [13.0, 2.97], "bedroom_1", ["bedroom_1", "storage_0", "bedroom_2"], ["N3", "N6", "N4"], [
        [[13.0, 2.97], [13.0, 3.0], [14.0, 3.0]],
        [[14.0, 3.0], [18.0, 3.0]],
        [[18.0, 3.0], [22.05, 3.0]],
        [[22.05, 3.0], [22.05, 2.97], [13.0, 2.97]],
    ], 69.0, 18.16)


def answer_2hub() -> dict:
    """Ring 1 L = 18.06, ring 2 L = 18.16, 4 bends each: L = 36.22, B = 8, J = 40.22."""
    return _answer(900002, [_ring1(), _ring2()], {"H": 2, "L": 36.22, "X": 0, "O": 0.0, "B": 8, "J": 40.22})


def broken_2hub() -> dict[str, dict]:
    """One answer per hard rule. Each passes answer_io's shape checks; the checker must flag `rule`.

    Some also break other rules as a side effect (noted); tests only require the named rule to appear.
    """
    out = {}

    # 1 coverage: storage_0 / N6 is in no hub. (Side effects: zone, free space.)
    h2 = _hub("H2", [13.0, 2.97], "bedroom_1", ["bedroom_1", "bedroom_2"], ["N3", "N4"], [
        [[13.0, 2.97], [13.0, 3.0], [14.0, 3.0]],
        [[14.0, 3.0], [22.05, 3.0]],
        [[22.05, 3.0], [22.05, 2.97], [13.0, 2.97]],
    ], 46.2, 18.16)
    out["coverage"] = _answer(900002, [_ring1(), h2], {}, "broken")

    # 2 capacity: one hub serves all 6 rooms (138 m^2, 6 nodes).
    h1 = _hub("H1", [1.0, 2.97], "living_0", IDS_2HUB, ["N1", "N5", "N2", "N3", "N6", "N4"], [
        [[1.0, 2.97], [1.0, 3.0], [1.95, 3.0]],
        [[1.95, 3.0], [6.0, 3.0]],
        [[6.0, 3.0], [10.0, 3.0]],
        [[10.0, 3.0], [14.0, 3.0]],
        [[14.0, 3.0], [18.0, 3.0]],
        [[18.0, 3.0], [22.05, 3.0]],
        [[22.05, 3.0], [22.05, 2.97], [1.0, 2.97]],
    ], 138.0, 42.22)
    out["capacity"] = _answer(900002, [h1], {}, "broken")

    # 3 zone: H1 takes living, kitchen and bedroom_1, skipping bedroom_0 (in H2).
    # (Side effects: both rings cross the other zone's rooms; rings cross.)
    h1 = _hub("H1", [1.0, 2.97], "living_0", ["living_0", "kitchen_0", "bedroom_1"], ["N1", "N5", "N3"], [
        [[1.0, 2.97], [1.0, 3.0], [1.95, 3.0]],
        [[1.95, 3.0], [6.0, 3.0]],
        [[6.0, 3.0], [14.0, 3.0]],
        [[14.0, 3.0], [14.0, 2.97], [1.0, 2.97]],
    ], 69.0, 26.06)
    h2 = _hub("H2", [9.0, 3.09], "bedroom_0", ["bedroom_0", "storage_0", "bedroom_2"], ["N2", "N6", "N4"], [
        [[9.0, 3.09], [10.0, 3.09], [10.0, 3.0]],
        [[10.0, 3.0], [10.0, 3.06], [18.0, 3.06], [18.0, 3.0]],
        [[18.0, 3.0], [22.05, 3.0]],
        [[22.05, 3.0], [22.05, 3.09], [9.0, 3.09]],
    ], 69.0, 0.0)
    out["zone"] = _answer(900002, [h1, h2], {}, "broken")

    # 4 ring: H1 visits N5 twice.
    h1 = _hub("H1", [1.0, 2.97], "living_0", ["living_0", "kitchen_0", "bedroom_0"], ["N1", "N5", "N2"], [], 69.0, 0.0)
    h1["sequence"] = ["H1", "N1", "N5", "N2", "N5", "H1"]
    polys = [
        [[1.0, 2.97], [1.0, 3.0], [1.95, 3.0]],
        [[1.95, 3.0], [6.0, 3.0]],
        [[6.0, 3.0], [10.0, 3.0]],
        [[10.0, 3.0], [10.0, 3.03], [6.0, 3.03], [6.0, 3.0]],
        [[6.0, 3.0], [6.0, 2.97], [1.0, 2.97]],
    ]
    h1["legs"] = [{"from": h1["sequence"][k], "to": h1["sequence"][k + 1], "polyline": p} for k, p in enumerate(polys)]
    out["ring"] = _answer(900002, [h1, _ring2()], {}, "broken")

    # 5 free space: H1's return leg goes through the walls at x = 4 and x = 8 (y = 1, no door there).
    out["free_space"] = _answer(900002, [
        _ring1(return_leg=[[10.0, 3.0], [10.0, 1.0], [1.0, 1.0], [1.0, 2.97]]), _ring2()], {}, "broken")

    # 6 hub: H1 sits 0.3 m from the outer wall.
    out["hub"] = _answer(900002, [_ring1(hub_point=(0.3, 2.97)), _ring2()], {}, "broken")
    return out


def zone_candidates_2hub() -> dict:
    """Every legal zone of synth_2hub (contiguous runs of 1-4 rooms; 5 rooms exceed 100 m^2) with a
    synthetic additive cost 3 * n^2 + 4. The unique 2-hub optimum is rooms 0-2 + rooms 3-5, cost 62."""
    areas = [23.4, 22.8, 22.8, 22.8, 22.8, 23.4]
    cands = []
    for i in range(6):
        for n in range(1, 5):
            if i + n > 6:
                continue
            area = round(sum(areas[i:i + n]), 6)
            cands.append({"zone_id": f"Z{i}_{n}", "room_ids": sorted(IDS_2HUB[i:i + n]), "area_m2": area,
                          "n_nodes": n, "cost": float(3 * n * n + 4)})
    return {"plan_id": 900002, "rooms": IDS_2HUB, "min_hubs": 2, "candidates": cands,
            "expected": {"zone_ids": ["Z0_3", "Z3_3"], "hubs": 2, "cost": 62.0}}


def heatmap_2hub_h1() -> dict:
    """Synthetic heatmap for H1 of synth_2hub: zero on the ring's straight runs, rising away from them."""
    points = []
    for xs in ([1.0, 2.0, 3.0], [5.0, 6.0, 7.0], [9.0, 10.0, 11.0]):
        for x in xs:
            for y in (1.0, 2.0, 2.97, 4.0, 5.0):
                points.append([x, y, 0.0 if y == 2.97 else round(2 * abs(y - 2.97) + 0.5, 3)])
    return {"schema_version": "8ball-heatmap/1", "plan_id": 900002, "hub_id": "H1", "step_m": 1.0,
            "points": points, "chosen": [1.0, 2.97], "legend": "extra J for this zone's chosen loop"}


def branching_2hub() -> dict:
    return {"schema_version": "8ball-branching/1", "plan_id": 900002, "hubs": [
        {"hub_id": "H1", "point": [1.0, 2.97], "paths": {
            "N1": [[1.0, 2.97], [1.0, 3.0], [1.95, 3.0]],
            "N5": [[1.0, 2.97], [1.0, 3.0], [6.0, 3.0]],
            "N2": [[1.0, 2.97], [1.0, 3.0], [10.0, 3.0]]}},
        {"hub_id": "H2", "point": [13.0, 2.97], "paths": {
            "N3": [[13.0, 2.97], [13.0, 3.0], [14.0, 3.0]],
            "N6": [[13.0, 2.97], [13.0, 3.0], [18.0, 3.0]],
            "N4": [[13.0, 2.97], [13.0, 3.0], [22.05, 3.0]]}},
    ]}
