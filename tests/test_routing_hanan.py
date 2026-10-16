"""A5: Hanan track grid (Person A)."""
from __future__ import annotations

import statistics
import time

import numpy as np
import pytest
from shapely.geometry import LineString

from eightball import config
from eightball.geometry import build_clean_plan
from eightball.io import resplan
from eightball.routing import api
from eightball.routing.hanan import build_tracks
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def door_lane_edges(cp, grid, door) -> int:
    """How many of the door's centre / +lane / -lane lines have an edge that runs through the door gap."""
    lane = config.LANE_SPACING_M * cp.scale
    cx, cy = door.center
    found = 0
    for off in (-lane, 0.0, lane):
        for e in range(grid.n_edges):
            a, b = grid.e_a[e], grid.e_b[e]
            if door.axis == "h" and grid.e_axis[e] == 1 and abs(grid.vx[a] - (cx + off)) < 0.0021 * cp.scale and \
                    min(grid.vy[a], grid.vy[b]) <= cy <= max(grid.vy[a], grid.vy[b]):
                found += 1
                break
            if door.axis == "v" and grid.e_axis[e] == 0 and abs(grid.vy[a] - (cy + off)) < 0.0021 * cp.scale and \
                    min(grid.vx[a], grid.vx[b]) <= cx <= max(grid.vx[a], grid.vx[b]):
                found += 1
                break
    return found


def check_grid(cp, grid):
    s = cp.scale
    assert grid.n_edges > 0
    # every edge is axis-aligned, inside (nearly) the free space and clear of the walls
    cover = cp.free.buffer(0.01 * config.MERGE_LINES_M * s + 0.5 * config.MERGE_LINES_M * s)
    sample = np.linspace(0, grid.n_edges - 1, min(grid.n_edges, 400)).astype(int)
    for e in sample:
        a, b = grid.e_a[e], grid.e_b[e]
        pa, pb = (grid.vx[a], grid.vy[a]), (grid.vx[b], grid.vy[b])
        assert pa[0] == pb[0] or pa[1] == pb[1]
        line = LineString([pa, pb])
        assert cover.covers(line)
        assert line.distance(cp.walls) >= 0.03 * s - 1e-9
    # adjacency matches the edge list
    for h in api.HEADINGS:
        has = grid.nbr[h] >= 0
        assert (grid.nbr_edge[h][has] >= 0).all()
    nodes_in_free = {n.id for n in cp.nodes.values() if not any(f.endswith(n.id) for f in cp.flags
                                                                 if f.startswith("node_not_in_free"))}
    assert nodes_in_free <= set(grid.node_vertex)
    for nid, v in grid.node_vertex.items():
        assert (grid.vx[v], grid.vy[v]) == pytest.approx(cp.nodes[nid].point, abs=1e-9 * max(s, 1.0))


def test_synthetic_plans():
    for plan, nodes in ((syn.synth_1hub(), syn.NODES[900001]), (syn.synth_2hub(), syn.NODES[900002])):
        cp = build_clean_plan(plan, nodes)
        grid = build_tracks(cp)
        assert cp.tracks is grid
        check_grid(cp, grid)
        for door in cp.doors.values():
            assert door_lane_edges(cp, grid, door) == 3


def test_room_tags_and_allowed_rooms():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    grid = build_tracks(cp)
    kitchen = grid.room_ids.index("kitchen_0")
    n5 = grid.node_vertex["N5"]
    # an edge leaving the kitchen node runs in the kitchen
    e = int(next(grid.nbr_edge[h][n5] for h in api.HEADINGS if grid.nbr_edge[h][n5] >= 0))
    assert grid.edge_room(e) == "kitchen_0" and grid.e_rooms[e] == 1 << kitchen
    only_kitchen = grid.allowed_edges({"kitchen_0"})
    assert only_kitchen[e]
    # with only the kitchen allowed the living room's node is cut off
    n1 = grid.node_vertex["N1"]
    around = [int(grid.nbr_edge[h][n1]) for h in api.HEADINGS if grid.nbr_edge[h][n1] >= 0]
    assert around and not any(only_kitchen[x] for x in around)
    assert grid.allowed_edges(set(cp.rooms)).all()


def test_vertex_lookup():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    grid = build_tracks(cp)
    assert grid.vertex_at(cp.nodes["N1"].point) == grid.node_vertex["N1"]
    assert grid.vertex_at((4.0, 0.5)) is None  # inside the wall


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_fifty_train_plans():
    times = []
    for pid in resplan.split_ids("train")[:50]:
        cp = build_clean_plan(resplan.get_plan(pid))
        t0 = time.perf_counter()
        grid = build_tracks(cp)
        times.append(time.perf_counter() - t0)
        check_grid(cp, grid)
        for door in cp.doors.values():
            # a door to a balcony leads out of the inner boundary, where no cable may go
            inside = all(cp.rooms[r].poly.intersection(cp.inner).area >= 0.5 * cp.rooms[r].poly.area
                         for r in door.rooms)
            if inside:
                assert door_lane_edges(cp, grid, door) == 3, f"plan {pid} {door.id}"
    assert statistics.median(times) < 0.5, f"median build {statistics.median(times):.3f} s"


def test_more_rooms_than_the_mask_holds_is_refused_and_solve_falls_back_to_greedy():
    from eightball.optimize import pipeline
    from eightball.routing import hanan

    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    room = cp.rooms["living_0"]
    for k in range(hanan.MAX_ROOMS + 1):
        cp.rooms[f"extra_{k}"] = room
    with pytest.raises(ValueError, match="room mask"):
        build_tracks(cp)
    # a plan with that many rooms still gets an answer: the exact search fails cleanly, greedy stands
    import eightball.routing.hanan as h
    old = h.MAX_ROOMS
    h.MAX_ROOMS = 1
    try:
        res = pipeline.solve(syn.synth_2hub(), syn.NODES[900002], "exact")
    finally:
        h.MAX_ROOMS = old
    assert res.answer["meta"]["solver"] == "greedy"
    assert any("exact solver failed" in w for w in res.answer["meta"]["warnings"])
