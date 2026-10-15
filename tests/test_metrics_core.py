import pytest

from tests.metric_cases import CASES, check_result, to_answer


@pytest.mark.xfail(reason="core metrics not built yet: Person A, step A3", raises=NotImplementedError, strict=False)
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_core_metrics(case):
    from eightball.core.metrics import score

    result = score(to_answer(case), 1.0)
    assert check_result(result, case) == []
