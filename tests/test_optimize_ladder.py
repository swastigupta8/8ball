"""A11: search ladder, exhaustive zone solver, solve(exact) and zone_candidates (Person A)."""
from __future__ import annotations

import math

import pytest

from eightball import config
from eightball.core import metrics
from eightball.core.contracts import ZoneCandidate
from eightball.geometry import build_clean_plan
from eightball.io import answer_io, nodes as nodes_io, resplan
from eightball.optimize import ladder, pipeline
from eightball.optimize.hub import HubContext
from eightball.optimize.zones import enumerate_zones, zone_rooms
from eightball.routing.astar import HananRouter
from tests.fixtures import synthetic as syn
from tests.test_optimize_greedy import own_checks
from tests.test_optimize_loops import HALL_NODES, hall_plan

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def synth2():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    router = HananRouter(cp)
    return cp, router, HubContext(cp, router)


def test_covers_counts_the_two_hub_splits():
    cp, router, ctx = synth2()
    rooms = zone_rooms(cp)
    data = ladder.build_zone_data(cp, router, ctx, enumerate_zones(cp, rooms))
    hubs, splits, notes = ladder.fewest_hub_covers(rooms, data, 2, 1000)
    assert hubs == 2 and notes == []
    # a chain of 6 rooms into 2 runs, each of 2 to 4 rooms: sizes 2+4, 3+3, 4+2
    assert len(splits) == 3
    for split in splits:
        assert sorted(r for d in split for r in d.zone.room_ids) == sorted(rooms)


def test_exhaustive_zone_solver_matches_the_phase_0_fixture():
    fix = syn.zone_candidates_2hub()
    cands = [ZoneCandidate(c["zone_id"], frozenset(c["room_ids"]), c["area_m2"], c["n_nodes"], c["cost"])
             for c in fix["candidates"]]
    sel = ladder.ExhaustiveZoneSolver().select(fix["rooms"], cands, fix["min_hubs"], 10.0)
    assert (sorted(sel.zone_ids), sel.hubs, sel.cost, sel.optimal) == (fix["expected"]["zone_ids"], 2, 62.0, True)


def test_one_more_hub_is_used_and_explained_when_no_split_exists_at_the_bound():
    cp = build_clean_plan(hall_plan(), HALL_NODES)
    router = HananRouter(cp)
    ctx = HubContext(cp, router)
    rooms = zone_rooms(cp)
    data = ladder.build_zone_data(cp, router, ctx, enumerate_zones(cp, rooms))
    assert ladder.fewest_hub_covers(rooms, data, 1, 100)[0] == 1
    without_whole = [d for d in data if d.zone.n_nodes < 4]
    hubs, splits, notes = ladder.fewest_hub_covers(rooms, without_whole, 1, 100)
    assert hubs == 2 and splits and "no split into 1 zone" in notes[0]


def test_ladder_on_the_2hub_plan_finds_the_floor_and_beats_greedy():
    cp, router, ctx = synth2()
    import time
    sol, report = ladder.run_ladder(cp, router, ctx, time.perf_counter() + 20)
    assert sol is not None and sol.hubs == 2 and len(sol.cands) == 2
    assert report["best_additive_cost"] <= sol.J + 1e-6  # the additive floor never exceeds the real J
    assert report["min_hubs_bound"] == 2


def test_solve_exact_is_valid_and_never_worse_than_greedy():
    plan, nodes = syn.synth_2hub(), syn.NODES[900002]
    greedy = pipeline.solve(plan, nodes, "greedy")
    exact = pipeline.solve(plan, nodes, "exact")
    assert exact.answer["meta"]["solver"] == "exact"
    assert exact.answer["metrics"]["H"] == greedy.answer["metrics"]["H"] == 2
    assert exact.answer["metrics"]["J"] <= greedy.answer["metrics"]["J"] + 1e-9
    assert not [e for e in own_checks(plan, nodes, exact.answer) if "overlaps itself" not in e]
    meta = exact.answer["meta"]
    assert meta["min_hubs_bound"] == 2 and meta["best_additive_cost"] is not None
    assert meta["j_floor"] <= exact.answer["metrics"]["J"] + 1e-6
    assert len(exact.heatmaps) == 2 and all(answer_io.heatmap_errors(h) == [] for h in exact.heatmaps)
    assert {h["hub_id"] for h in exact.heatmaps} == {"H1", "H2"}


def test_a_tiny_budget_still_returns_an_answer():
    plan, nodes = syn.synth_2hub(), syn.NODES[900002]
    old = config.override(TIME_BUDGET_S=0.01)
    try:
        result = pipeline.solve(plan, nodes, "exact")
    finally:
        config.override(**old)
    assert result.answer["metrics"]["H"] >= 2 and math.isfinite(result.answer["metrics"]["J"])
    assert answer_io.answer_errors(result.answer) == []


def test_beam_search_and_backup_fallbacks(monkeypatch):
    cp, router, ctx = synth2()
    import time
    old = config.override(MAX_MIXES=1, MAX_SPLITS=1)
    try:
        monkeypatch.setattr(ladder, "load_backup_solver", lambda: None)
        sol, report = ladder.run_ladder(cp, router, ctx, time.perf_counter() + 20)
    finally:
        config.override(**old)
    assert sol is not None and sol.hubs == 2
    assert any("backup solver unavailable" in n for n in report["notes"])


def test_zone_candidates_facade():
    rooms, cands = pipeline.zone_candidates(syn.synth_2hub(), syn.NODES[900002])
    assert sorted(rooms) == sorted(syn.IDS_2HUB)
    assert len(cands) == 18 and all(c.cost > 0 and c.n_nodes == len(c.room_ids) for c in cands)
    assert all(round(c.cost, 3) == c.cost for c in cands)
    # a bigger zone never costs less than the cheapest sub-zone alone? (not required) but costs are finite
    assert all(math.isfinite(c.cost) for c in cands)


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_real_plans_exact_beats_or_equals_greedy_and_is_well_formed():
    better = equal = 0
    for pid in resplan.split_ids("train")[:25]:
        plan = resplan.get_plan(pid)
        nodes = nodes_io.make_nodes(plan, "center")
        g = pipeline.solve(plan, nodes, "greedy").answer
        e = pipeline.solve(plan, nodes, "exact").answer
        assert answer_io.answer_errors(e) == [], pid
        assert (e["metrics"]["H"], e["metrics"]["J"]) <= (g["metrics"]["H"], g["metrics"]["J"] + 1e-9), pid
        res = metrics.score(e, e["scale"])
        assert abs(res["J"] - e["metrics"]["J"]) < 1e-9
        if e["meta"]["solver"] == "exact":
            problems = [x for x in own_checks(plan, nodes, e) if "overlaps itself" not in x]
            assert problems == [], (pid, problems)
            better += e["metrics"]["J"] < g["metrics"]["J"] - 1e-9
            equal += abs(e["metrics"]["J"] - g["metrics"]["J"]) <= 1e-9
    assert better >= 10


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_additive_best_in_meta_equals_the_solver_over_every_zone():
    """Pricing only the zones of fewest-hub splits must give the same best additive cost as pricing every zone."""
    checked = 0
    for pid in resplan.split_ids("train")[:20]:
        plan = resplan.get_plan(pid)
        nodes = nodes_io.make_nodes(plan, "center")
        rooms, cands = pipeline.zone_candidates(plan, nodes)
        sel = ladder.ExhaustiveZoneSolver().select(rooms, cands, 1, 60.0)
        meta = pipeline.solve(plan, nodes, "exact").answer["meta"]
        if meta["best_additive_cost"] is not None and sel.zone_ids:
            assert meta["best_additive_cost"] == pytest.approx(sel.cost, abs=1e-6), pid
            checked += 1
    assert checked >= 10
