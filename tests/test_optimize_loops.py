"""A8: loop enumeration (Person A)."""
from __future__ import annotations

import math

import pytest
from shapely.geometry import box

from eightball.core import metrics
from eightball.geometry import build_clean_plan
from eightball.io import resplan
from eightball.optimize.loops import cycles, enumerate_loops, leg_overlap
from eightball.routing.astar import HananRouter
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def hall_plan() -> dict:
    """A 12 x 2 m hall (living) with three bedrooms above it, each with one door onto the hall."""
    return syn._plan(
        920000, box(0, 0, 12, 6),
        rooms={"living": [box(0, 0, 12, 2.0)],
               "bedroom": [box(0, 2.2, 3.9, 6), box(4.1, 2.2, 7.9, 6), box(8.1, 2.2, 12, 6)]},
        inner_walls=[box(0, 2, 1.5, 2.2), box(2.5, 2, 5.5, 2.2), box(6.5, 2, 9.5, 2.2), box(10.5, 2, 12, 2.2),
                     box(3.9, 2.2, 4.1, 6), box(7.9, 2.2, 8.1, 6)],
        doors=[box(1.5, 2, 2.5, 2.2), box(5.5, 2, 6.5, 2.2), box(9.5, 2, 10.5, 2.2)],
        windows=[], front_door=box(0.5, -0.2, 1.5, 0))


HALL_NODES = [
    {"node_id": "N1", "room_id": "living_0", "point": [1.0, 1.0]},
    {"node_id": "N2", "room_id": "bedroom_0", "point": [2.0, 4.0]},
    {"node_id": "N3", "room_id": "bedroom_1", "point": [6.0, 4.0]},
    {"node_id": "N4", "room_id": "bedroom_2", "point": [10.0, 4.0]},
]


def test_cycle_counts():
    assert len(cycles(["N1"])) == 1 and len(cycles(["N1", "N2"])) == 1
    assert len(cycles(["N1", "N2", "N3"])) == 1
    assert len(cycles(["N1", "N2", "N3", "N4"])) == 3
    assert len(cycles([f"N{i}" for i in range(1, 6)])) == 12  # (5 - 1)! / 2
    assert len({frozenset(frozenset(p) for p in zip(c, c[1:] + c[:1])) for c in cycles(list("ABCDE"))}) == 12


def test_single_node_and_pair():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    router = HananRouter(cp)
    one = enumerate_loops(cp, router, ["living_0"])
    assert len(one) == 1 and one[0].n == 1 and one[0].J == 0 and one[0].clean
    two = enumerate_loops(cp, router, ["living_0", "bedroom_0"])
    assert len(two) == 1 and two[0].n == 2 and two[0].clean
    lp = two[0]
    assert lp.L > 2 * 4.0 and lp.O == pytest.approx(0.0, abs=0.002) or "N2" in lp.retrace


def test_corridor_with_three_bedrooms_picks_the_left_to_right_order():
    cp = build_clean_plan(hall_plan(), HALL_NODES)
    router = HananRouter(cp)
    loops = enumerate_loops(cp, router, ["living_0", "bedroom_0", "bedroom_1", "bedroom_2"])
    assert len(loops) == 3
    best = loops[0]
    assert best.order in (("N1", "N2", "N3", "N4"), ("N1", "N4", "N3", "N2")) and best.clean
    assert best.J < loops[1].J and best.J < loops[2].J
    # recompute the numbers from the legs with the core metrics
    pts = [p for leg in best.legs for p in leg]
    special = {metrics.snap_point(cp.nodes[n].point, 1.0) for n in best.order}
    sc = metrics.score_rings([metrics.normalise(pts, special, 1.0)])
    assert (sc["L"], sc["X"], sc["O"], sc["B"], sc["J"]) == pytest.approx((best.L, best.X, best.O, best.B, best.J))
    # legs join the nodes exactly, axis-aligned
    for k, leg in enumerate(best.legs):
        assert leg[0] == pytest.approx(cp.nodes[best.order[k]].point)
        assert leg[-1] == pytest.approx(cp.nodes[best.order[(k + 1) % 4]].point)
        assert all(abs(p[0] - q[0]) < 1e-9 or abs(p[1] - q[1]) < 1e-9 for p, q in zip(leg, leg[1:]))


def test_dead_end_rooms_retrace_or_use_lanes_never_overlap_elsewhere():
    cp = build_clean_plan(hall_plan(), HALL_NODES)
    router = HananRouter(cp)
    for lp in enumerate_loops(cp, router, ["living_0", "bedroom_0", "bedroom_1", "bedroom_2"]):
        n = lp.n
        for j in range(n):
            for k in range(j + 1, n):
                ov = leg_overlap(lp.legs[j], lp.legs[k], 1.0)
                consecutive_at_retrace = ((k - j) % n == 1 and lp.order[k] in lp.retrace) or \
                                         ((j - k) % n == 1 and lp.order[j] in lp.retrace)
                assert ov < 0.002 or consecutive_at_retrace, (lp.order, j, k, ov)


def test_loop_j_is_at_least_the_additive_lower_bound():
    cp = build_clean_plan(hall_plan(), HALL_NODES)
    router = HananRouter(cp)
    allowed = router.allowed_rooms_for(["living_0", "bedroom_0", "bedroom_1", "bedroom_2"])
    lp = enumerate_loops(cp, router, ["living_0", "bedroom_0", "bedroom_1", "bedroom_2"])[0]
    cheapest_legs = sum(min(min(row) for row in router.cost_table(allowed, lp.order[k], lp.order[(k + 1) % 4]))
                        for k in range(4))
    assert lp.J >= cheapest_legs - 1e-9
    assert math.isfinite(lp.J)


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_real_plans_produce_clean_loops():
    from eightball.optimize.zones import enumerate_zones

    checked = 0
    for pid in resplan.split_ids("train")[:15]:
        cp = build_clean_plan(resplan.get_plan(pid))
        router = HananRouter(cp)
        for z in enumerate_zones(cp):
            if z.n_nodes > 3:
                continue
            loops = enumerate_loops(cp, router, z.room_ids)
            for lp in loops:
                assert lp.clean and math.isfinite(lp.J)
                assert lp.O < 0.002 or lp.retrace, (pid, z.room_ids, lp.order, lp.O)
            checked += len(loops)
    assert checked > 50
