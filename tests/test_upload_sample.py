"""The sample inputs in sample_input/ and web/samples/ solve through the API's uploaded-plan path (Person A)."""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from eightball.api import server

ROOT = Path(__file__).resolve().parents[1]


def _body(path: Path) -> server.SolveRequest:
    return server.SolveRequest(**json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("name", ["sample_plan_769.json", "sample_plan_224.json"])
def test_sample_file_solves_valid_through_the_upload_path(name):
    res = server.solve(_body(ROOT / "sample_input" / name))
    assert res["check"]["valid"] is True
    assert res["answer"]["meta"]["solver"] == "exact"
    assert res["answer"]["metrics"]["H"] == 2
    assert len(res["heatmaps"]) == 2 and len(res["branching"]["hubs"]) == 2


def test_the_viewer_sample_is_the_same_file():
    for name in ("sample_plan_769.json", "sample_plan_224.json"):
        assert (ROOT / "web" / "samples" / name).read_bytes() == (ROOT / "sample_input" / name).read_bytes()


def test_a_plan_without_nodes_gets_practice_nodes():
    body = json.loads((ROOT / "sample_input" / "sample_plan_769.json").read_text(encoding="utf-8"))
    body.pop("nodes")
    res = server.solve(server.SolveRequest(**body))
    assert res["check"]["valid"] is True and len(res["answer"]["nodes"]) == 4


@pytest.mark.parametrize("bad", [{"plan": {"id": 1}}, {}])
def test_bad_uploads_get_a_clear_error(bad):
    with pytest.raises(HTTPException) as err:
        server.solve(server.SolveRequest(**bad))
    assert err.value.status_code == 422 and isinstance(err.value.detail, str)
