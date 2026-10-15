import pytest

from tests.metric_cases import CASES, check_result, to_answer


@pytest.mark.xfail(reason="checker metrics not built yet: Person B, step B2", raises=NotImplementedError, strict=False)
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_checker_metrics(case):
    from eightball.evaluate.metrics_indep import score

    result = score(to_answer(case), 1.0)
    assert check_result(result, case) == []
