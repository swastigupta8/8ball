"""V3 feature: Why this answer? (optimize/explain.py, POST /api/explain)."""
import copy

import pytest

from eightball.api import server
from eightball.evaluate import checker
from eightball.optimize import explain, pipeline
from tests.fixtures import synthetic as S

PID = 900002
PLAN, NODES = S.PLANS[PID](), S.NODES[PID]


@pytest.fixture(scope="module")
def solved():
    return pipeline.solve(PLAN, NODES, "exact")


@pytest.fixture(scope="module")
def ex(solved):
    return explain.explain(PLAN, NODES, solved.answer)


def test_explain_does_not_touch_the_answer(solved):
    before = copy.deepcopy(solved.answer)
    explain.explain(PLAN, NODES, solved.answer)
    assert solved.answer == before


def test_hub_layer_matches_the_counting_bound(ex, solved):
    h = ex["hubs"]
    assert h["bound"] == solved.answer["meta"]["min_hubs_bound"] == 2
    assert h["hubs_used"] == solved.answer["metrics"]["H"] and h["meets_bound"]
    assert h["devices"] == len(NODES) and h["by_devices"] == 2 and h["by_area"] == 2
    assert h["fewest_splits"] >= 1 and "minimum" in h["summary"]


def test_groups_include_the_chosen_split_priced_the_same_way(ex, solved):
    g = ex["groups"]
    assert g["comparable"] and g["options"]
    chosen = [o for o in g["options"] if o["chosen"]]
    assert len(chosen) == 1 and chosen[0]["gap"] == 0
    used = {frozenset(h["room_ids"]) for h in solved.answer["hubs"]}
    assert {frozenset(z["room_ids"]) for z in chosen[0]["zones"]} == used
    assert all(o["gap"] >= -1e-6 for o in g["options"])        # nothing beats the chosen split by the search's own costs
    assert [o["rank"] for o in g["options"]] == list(range(1, len(g["options"]) + 1))


def test_every_alternative_grouping_comes_with_a_valid_answer(ex):
    with_answer = [o for o in ex["groups"]["options"] if "answer" in o]
    assert with_answer
    for o in with_answer:
        assert checker.check(PLAN, o["answer"], NODES)["valid"]
        assert o["answer"]["metrics"]["H"] == len(o["zones"])


def test_routes_list_the_chosen_loop_and_never_a_cheaper_one(ex, solved):
    assert [r["hub_id"] for r in ex["routes"]] == [h["hub_id"] for h in solved.answer["hubs"]]
    for r in ex["routes"]:
        if r["loops"]:
            assert sum(1 for l in r["loops"] if l["chosen"]) <= 1
            assert all(l["gap"] >= -1e-6 for l in r["loops"])
        if r["spots"]:
            assert r["spots"][0]["chosen"] and all(s["extra"] >= 0 for s in r["spots"])


def test_endpoint_checks_the_alternatives(solved):
    body = server.explain(server.ExplainRequest(plan_id=PID, answer=solved.answer))
    with_answer = [o for o in body["groups"]["options"] if "answer" in o]
    assert with_answer and all(o["valid"] for o in with_answer)
    assert body["hubs"]["bound"] == 2
