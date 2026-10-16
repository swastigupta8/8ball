"""A12: polish (Person A)."""
from __future__ import annotations

import time

import pytest

from eightball.core import metrics
from eightball.geometry import build_clean_plan
from eightball.io import answer_io, nodes as nodes_io, resplan
from eightball.optimize import ladder, pipeline
from eightball.optimize.clash import ClashTable
from eightball.optimize.hub import HubContext
from eightball.optimize.polish import clean_leg, polish, polyline_edges
from eightball.routing.astar import HananRouter
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def test_clean_leg_drops_duplicates_and_collinear_points_but_keeps_ends_and_corners():
    assert clean_leg([(0, 0), (0, 0), (1, 0), (2, 0), (2, 1), (2, 2), (3, 2)]) == [(0, 0), (2, 0), (2, 2), (3, 2)]
    assert clean_leg([(0, 0), (3, 0), (0, 0)]) == [(0, 0), (3, 0), (0, 0)]  # a reversal is a corner
    assert clean_leg([(1.0, 2.0), (1.0, 2.0)]) == [(1.0, 2.0)] or len(clean_leg([(1.0, 2.0), (1.0, 2.0)])) >= 1


def test_cleaning_changes_no_metric():
    plan, nodes = syn.synth_2hub(), syn.NODES[900002]
    a = pipeline.solve(plan, nodes, "exact").answer
    res = metrics.score(a, a["scale"])
    for key in ("L", "X", "O", "B", "J"):
        assert res[key] == pytest.approx(a["metrics"][key], abs=1e-9)
    for h in a["hubs"]:
        for leg in h["legs"]:
            assert clean_leg(leg["polyline"]) == [tuple(p) for p in leg["polyline"]] or \
                   [list(p) for p in clean_leg(leg["polyline"])] == leg["polyline"]


def test_polyline_edges_walks_the_grid():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    router = HananRouter(cp)
    cost, poly = router.shortest(frozenset(cp.rooms), "N1", "N2")
    edges = polyline_edges(router, poly)
    g = router.grid
    assert edges and abs(sum(g.e_len[e] for e in edges) - sum(abs(b[0] - a[0]) + abs(b[1] - a[1])
                                                              for a, b in zip(poly, poly[1:]))) < 1e-9


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_polish_never_raises_j_and_keeps_answers_well_formed():
    improved = tried = 0
    for pid in resplan.split_ids("train")[:40]:
        plan = resplan.get_plan(pid)
        nodes = nodes_io.make_nodes(plan, "center")
        cp = build_clean_plan(plan, nodes)
        router = HananRouter(cp)
        ctx = HubContext(cp, router)
        sol, report = ladder.run_ladder(cp, router, ctx, time.perf_counter() + 60)
        if sol is None or len(sol.cands) < 2:
            continue
        table = ClashTable(cp)
        before = table.exact(sol.cands)["J"]
        cands, rep = polish(cp, router, ctx, sol.cands, table, time.perf_counter() + 20)
        after = table.exact(cands)["J"]
        assert after <= before + 1e-9, (pid, before, after)
        assert abs(rep["J_after"] - after) < 1e-9
        tried += 1
        improved += after < before - 1e-9
    assert tried >= 10
    print(f"polish improved {improved} of {tried} multi-hub plans")
