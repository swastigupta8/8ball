"""A1: clean geometry, door/passage graph, free space (Person A)."""
from __future__ import annotations

import pytest
from shapely import affinity
from shapely.geometry import Point, box

from eightball import config
from eightball.geometry import build_clean_plan
from eightball.io import resplan
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def _real_flags(cp) -> list[str]:
    # synthetic plans have scale 1 (metres), which is correctly flagged as suspicious
    return [f for f in cp.flags if f != 'suspicious_scale']


def _gap_plan(gap_lo: float, gap_hi: float, door: bool = False, buried: bool = False) -> dict:
    """Two 3.9 x 4 rooms; the wall at x = 3.9..4.1 has an open gap (a passage if wide enough) or a door."""
    if door:
        walls = [box(3.9, 0, 4.1, 1.5), box(3.9, 2.5, 4.1, 4)]
        doors = [box(3.9, 1.5, 4.1, 2.5)]
    elif buried:
        walls, doors = [box(3.9, 0, 4.1, 4)], [box(3.9, 1.5, 4.1, 2.5)]
    else:
        walls = [box(3.9, 0, 4.1, gap_lo), box(3.9, gap_hi, 4.1, 4)]
        doors = []
    return syn._plan(910000, box(0, 0, 8, 4), {"living": [box(0, 0, 3.9, 4)], "bedroom": [box(4.1, 0, 8, 4)]},
                     walls, doors, [], box(0.5, -0.2, 1.5, 0))


def _scaled(plan: dict, k: float) -> dict:
    """The same plan with every coordinate multiplied by k (so scale = k)."""
    out = dict(plan)
    for key, value in plan.items():
        if hasattr(value, "geom_type"):
            out[key] = affinity.scale(value, k, k, origin=(0, 0))
    out["wall_depth"] = plan["wall_depth"] * k
    return out


def test_one_hub_plan():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    assert list(cp.rooms) == ["living_0", "bedroom_0"]
    assert all(r.eligible for r in cp.rooms.values())
    assert cp.rooms["living_0"].area_m2 == pytest.approx(15.6)
    assert len(cp.doors) == 1 and set(cp.doors["door_0"].rooms) == {"living_0", "bedroom_0"}
    assert cp.doors["door_0"].axis == "v"
    assert cp.passages == {}
    assert cp.links.has_edge("living_0", "bedroom_0")
    assert cp.rooms["living_0"].door_ids == ("door_0",)
    assert _real_flags(cp) == []


def test_two_hub_plan_is_a_chain_with_no_passages():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    assert len(cp.rooms) == 6 and len(cp.doors) == 5 and cp.passages == {}
    order = syn.IDS_2HUB
    assert {frozenset(e) for e in cp.links.edges} == {frozenset(order[i:i + 2]) for i in range(5)}
    assert _real_flags(cp) == []


def test_front_door_is_not_a_link():
    plan = syn.synth_1hub()
    plan["door"] = plan["door"].union(plan["front_door"])
    cp = build_clean_plan(plan, syn.NODES[900001])
    assert len(cp.doors) == 1


def test_wide_gap_is_a_passage_and_narrow_gap_is_not():
    wide = build_clean_plan(_gap_plan(1.4, 2.6))
    assert len(wide.passages) == 1 and wide.doors == {}
    assert set(wide.passages["passage_0"].rooms) == {"living_0", "bedroom_0"}
    assert wide.passages["passage_0"].seg.length == pytest.approx(1.2, abs=0.05)
    assert wide.links.has_edge("living_0", "bedroom_0")
    narrow = build_clean_plan(_gap_plan(1.8, 2.2))
    assert narrow.passages == {} and not narrow.links.has_edge("living_0", "bedroom_0")


def test_door_gap_is_not_also_a_passage():
    cp = build_clean_plan(_gap_plan(0, 0, door=True))
    assert len(cp.doors) == 1 and cp.passages == {}


def test_flood_check_agrees_on_clear_cases():
    assert len(build_clean_plan(_gap_plan(1.4, 2.6), flood_check=True).passages) == 1
    cp = build_clean_plan(_gap_plan(1.4, 2.6))
    assert not any(f.startswith("passage_rejected") for f in cp.flags)


def test_buried_door_is_carved_out_of_the_wall():
    cp = build_clean_plan(_gap_plan(0, 0, buried=True))
    assert not cp.walls.intersects(Point(4.0, 2.0))
    assert cp.free.contains(Point(4.0, 2.0))
    assert len(cp.doors) == 1


def test_free_space_keeps_clear_of_walls_and_windows():
    for plan in (syn.synth_1hub(), syn.synth_2hub()):
        cp = build_clean_plan(plan)
        clearance = float(config.WALL_CLEARANCE_M) * cp.scale
        assert not cp.free.is_empty
        assert cp.free.distance(cp.walls) >= clearance - 1e-9
        assert cp.free.distance(cp.windows) >= clearance - 1e-9
        assert not cp.free.intersects(cp.front_door)
    cp = build_clean_plan(syn.synth_1hub())
    assert cp.free.contains(Point(4.0, 2.0))  # through the door gap
    assert not cp.free.contains(Point(4.0, 0.5))  # inside the wall


def test_scale_is_applied_once():
    base = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    big = _scaled(syn.synth_1hub(), 2.0)
    assert resplan.scale(big) == pytest.approx(2.0)
    nodes = [{"node_id": n["node_id"], "room_id": n["room_id"], "point": [n["point"][0] * 2, n["point"][1] * 2]}
             for n in syn.NODES[900001]]
    cp = build_clean_plan(big, nodes)
    assert cp.scale == pytest.approx(2.0)
    assert cp.rooms["living_0"].area_m2 == pytest.approx(base.rooms["living_0"].area_m2)
    assert cp.free.distance(cp.walls) >= float(config.WALL_CLEARANCE_M) * 2.0 - 1e-9
    assert _real_flags(cp) == []


def test_nodes_are_generated_and_clear_of_walls():
    for plan in (syn.synth_1hub(), syn.synth_2hub()):
        cp = build_clean_plan(plan)
        assert len(cp.nodes) == sum(r.eligible for r in cp.rooms.values())
        for node in cp.nodes.values():
            room = cp.rooms[node.room_id]
            assert room.poly.exterior.distance(Point(node.point)) >= config.NODE_CLEARANCE_M * cp.scale - 1e-6
        assert _real_flags(cp) == []


def test_bad_node_is_flagged():
    nodes = [{"node_id": "N1", "room_id": "living_0", "point": [0.1, 0.1]},
             {"node_id": "N2", "room_id": "bedroom_0", "point": [6.05, 2.0]}]
    cp = build_clean_plan(syn.synth_1hub(), nodes)
    assert "node_clearance:N1" in cp.flags


def test_inward_simplify_stays_inside():
    import math
    from shapely.geometry import Polygon
    from eightball.geometry.clean import simplify_inward
    ring = Polygon([(math.cos(t / 40 * 2 * math.pi) * 5 + 5, math.sin(t / 40 * 2 * math.pi) * 5 + 5)
                    for t in range(40)])
    simple = simplify_inward(ring, 0.05)
    assert ring.buffer(1e-9).contains(simple)
    assert len(simple.exterior.coords) <= len(ring.exterior.coords)


def test_debug_png(tmp_path):
    from eightball.viz.debug import plot_clean_plan
    out = plot_clean_plan(build_clean_plan(syn.synth_2hub()), tmp_path / "p.png")
    assert out.exists() and out.stat().st_size > 1000


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_real_plans_build():
    ids = resplan.split_ids("train")[:10] + [14433, 1448]
    for pid in ids:
        cp = build_clean_plan(resplan.get_plan(pid))
        assert len(cp.rooms) >= 1 and not cp.free.is_empty
        assert not cp.free.intersects(cp.walls)
        for node in cp.nodes.values():
            assert cp.rooms[node.room_id].poly.exterior.distance(Point(node.point)) >= \
                config.NODE_CLEARANCE_M * cp.scale - 1e-6 or any(f.endswith(node.id) for f in cp.flags)




