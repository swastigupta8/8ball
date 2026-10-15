import pytest

from tests.metric_cases import CASES, check_result, to_answer


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_core_metrics(case):
    from eightball.core.metrics import score

    result = score(to_answer(case), 1.0)
    assert check_result(result, case) == []



def _fixture_answers():
    from tests.fixtures import synthetic as syn
    return [syn.answer_1hub(), syn.answer_2hub()]


@pytest.mark.parametrize("answer", _fixture_answers(), ids=["1hub", "2hub"])
def test_fixture_answers_match_hand_computed_metrics(answer):
    from eightball.core.metrics import score

    result = score(answer, answer["scale"])
    exp = answer["metrics"]
    assert result["L"] == pytest.approx(exp["L"], abs=0.002)
    assert (result["X"], result["B"]) == (exp["X"], exp["B"])
    assert result["O"] == pytest.approx(exp["O"], abs=0.002)
    assert result["J"] == pytest.approx(exp["J"], abs=0.004)
    assert set(result["per_hub"]) == {h["hub_id"] for h in answer["hubs"]}


@pytest.mark.parametrize("case_id", ["03_slide7_plus_crossing", "05_slide7_shared_2m", "08_t_touch",
                                     "09_three_legs_one_stretch", "12_through_other_node"])
def test_clash_is_the_exact_extra_of_a_second_ring(case_id):
    from eightball.core.metrics import clash, score_rings, hub_ring

    case = next(c for c in CASES if c["id"] == case_id)
    answer = to_answer(case)
    nodes = {n["node_id"]: n for n in answer["nodes"]}
    a, b = (hub_ring(h, nodes, 1.0) for h in answer["hubs"])
    together, alone_a, alone_b = score_rings([a, b]), score_rings([a]), score_rings([b])
    pts = lambda r: [list(p) for p in (x for x in (r.points + r.points[:1]))]
    scaled = lambda r: [[v * 0.001 for v in p] for p in pts(r)]
    sp = lambda r: [[v * 0.001 for v in p] for p in r.special]
    x, o = clash(scaled(a), scaled(b), 1.0, sp(a), sp(b))
    assert x == together["X"] - alone_a["X"] - alone_b["X"]
    assert o == pytest.approx(together["O"] - alone_a["O"] - alone_b["O"], abs=1e-9)
