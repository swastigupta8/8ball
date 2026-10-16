"""Files the web pages read must be strict JSON: browsers reject Infinity and NaN (it once blanked How it works)."""
import json
import math

import pytest

from eightball.bench import webjson


def test_non_finite_numbers_become_null_everywhere():
    doc = {"a": math.inf, "b": [1.5, -math.inf, {"c": math.nan}], "d": (2.0, math.inf), "e": "Infinity", "f": 3}
    out = json.loads(webjson.dumps(doc))
    assert out == {"a": None, "b": [1.5, None, {"c": None}], "d": [2.0, None], "e": "Infinity", "f": 3}


def test_output_is_strict_json():
    text = webjson.dumps({"cost": math.inf, "x": [math.nan]})
    assert "Infinity" not in text and "NaN" not in text
    json.loads(text, parse_constant=lambda c: pytest.fail(f"non-strict constant {c}"))


def test_finite_values_are_untouched():
    doc = {"n": 7, "x": 0.1, "s": "ok", "none": None, "flag": True, "nested": {"k": [1, 2, 3]}}
    assert json.loads(webjson.dumps(doc)) == doc


def test_the_input_is_not_modified():
    doc = {"a": math.inf, "b": [math.nan]}
    webjson.finite(doc)
    assert doc["a"] == math.inf and math.isnan(doc["b"][0])


@pytest.mark.parametrize("module", ["stitch", "report", "gallery"])
def test_the_bench_writers_use_the_strict_helper(module):
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "src" / "eightball" / "bench" / f"{module}.py").read_text(encoding="utf-8")
    assert "webjson" in src
