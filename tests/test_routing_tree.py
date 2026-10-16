"""A13: branching tree (Person A)."""
from __future__ import annotations

import pytest
from shapely.geometry import LineString

from eightball.geometry import build_clean_plan
from eightball.io import answer_io, nodes as nodes_io, resplan
from eightball.optimize import pipeline
from eightball.routing.astar import HananRouter
from eightball.routing.hanan import build_tracks
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def test_tree_reaches_every_node_and_shares_prefixes():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    hub = (1.0, 2.97)
    router = HananRouter(cp, build_tracks(cp, extra_points=[hub], attach=False))
    zone = router.allowed_rooms_for({"living_0", "kitchen_0", "bedroom_0"})
    tree = router.branching_tree(zone, hub, ["N1", "N5", "N2"])
    assert set(tree) == {"N1", "N5", "N2"}
    for n, poly in tree.items():
        assert poly[0] == pytest.approx(hub) and poly[-1] == pytest.approx(cp.nodes[n].point)
        assert all(abs(p[0] - q[0]) < 1e-9 or abs(p[1] - q[1]) < 1e-9 for p, q in zip(poly, poly[1:]))
        assert cp.free.buffer(0.01).covers(LineString(poly))
    # every branch is a cheapest path (metres + 0.5 per interior bend, any headings) from the hub
    from eightball.routing import api
    from eightball.routing.crude import poly_cost
    for n, poly in tree.items():
        best = router.shortest(zone, api.free_point_id(*hub), n)[0]
        assert poly_cost(poly, 1.0) == pytest.approx(best, abs=1e-9)


def test_tree_needs_a_vertex_hub_and_respects_rooms():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    router = HananRouter(cp)
    with pytest.raises(KeyError):
        router.branching_tree(frozenset(cp.rooms), (1.0, 2.97), ["N1"])
    hub = (1.0, 2.97)
    router = HananRouter(cp, build_tracks(cp, extra_points=[hub], attach=False))
    only_living = router.allowed_rooms_for({"living_0"})
    tree = router.branching_tree(only_living, hub, ["N1", "N2"])
    assert set(tree) == {"N1"}  # N2 is in another room that isn't allowed


def test_solve_fills_the_branching_json_for_every_hub():
    plan, nodes = syn.synth_2hub(), syn.NODES[900002]
    for solver in ("greedy", "exact"):
        res = pipeline.solve(plan, nodes, solver)
        assert answer_io.branching_errors(res.branching) == []
        by_hub = {h["hub_id"]: h for h in res.branching["hubs"]}
        for hub in res.answer["hubs"]:
            assert set(by_hub[hub["hub_id"]]["paths"]) == set(hub["node_ids"])


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_real_plans_have_trees():
    for pid in resplan.split_ids("train")[:8]:
        plan = resplan.get_plan(pid)
        res = pipeline.solve(plan, nodes_io.make_nodes(plan, "center"), "exact")
        assert answer_io.branching_errors(res.branching) == []
        by_hub = {h["hub_id"]: h for h in res.branching["hubs"]}
        for hub in res.answer["hubs"]:
            assert set(by_hub[hub["hub_id"]]["paths"]) == set(hub["node_ids"]), pid
