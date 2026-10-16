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


def test_every_solve_is_saved_to_disk_and_the_overlay_downloads(tmp_path, monkeypatch):
    from eightball import config

    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    body = json.loads((ROOT / "sample_input" / "sample_plan_769.json").read_text(encoding="utf-8"))
    res = server.solve(server.SolveRequest(**body))
    folder = Path(res["saved_to"])
    assert folder.name == "769" and (folder / "answer.json").exists() and (folder / "check.json").exists()
    on_disk = json.loads((folder / "answer.json").read_text(encoding="utf-8"))
    assert on_disk == res["answer"] and on_disk["schema_version"] == "8ball-answer/1"
    assert sorted(p.name for p in folder.glob("heatmap_*.json")) == ["heatmap_H1.json", "heatmap_H2.json"]
    for fmt, magic in (("svg", b"<?xml"), ("png", b"\x89PNG")):
        out = server.overlay(server.OverlayRequest(plan=body["plan"], nodes=body["nodes"], answer=res["answer"],
                                                   format=fmt))
        assert out.body.startswith(magic) and fmt in out.headers["content-disposition"]
    with pytest.raises(HTTPException) as err:
        server.overlay(server.OverlayRequest(plan=body["plan"], answer=res["answer"], format="pdf"))
    assert err.value.status_code == 422
