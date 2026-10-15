import json
import pickle
from pathlib import Path

from eightball import cli
from eightball.viz.export import PLAN_SCHEMA_VERSION, export_bundle, plan_json
from eightball.viz.overlay import render
from tests.fixtures import synthetic as S

FIX = Path(__file__).parent / "fixtures" / "json"


def _answer(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def test_plan_json_shape():
    pj = plan_json(S.synth_2hub(), S.NODES[900002])
    assert pj["schema_version"] == PLAN_SCHEMA_VERSION and pj["plan_id"] == 900002
    assert [r["room_id"] for r in pj["rooms"] if r["eligible"]] == \
        ["living_0", "bedroom_0", "bedroom_1", "bedroom_2", "kitchen_0", "storage_0"]
    assert len(pj["doors"]) == 5 and pj["walls"] and pj["windows"]
    assert len(pj["links"]) == 5 and len(pj["nodes"]) == 6
    minx, miny, maxx, maxy = pj["bounds"]
    assert minx < -0.2 and maxx > 24.2  # outer walls fit inside the bounds
    ring = pj["rooms"][0]["polygon"][0]
    assert ring[0] == ring[-1] and len(ring[0]) == 2


def test_export_bundle_writes_answer_and_check(tmp_path):
    paths = export_bundle(S.synth_2hub(), tmp_path, _answer("answer_900002_broken_hub"), S.NODES[900002])
    assert set(paths) == {"plan", "answer", "check"}
    check = json.loads(paths["check"].read_text())
    assert check["valid"] is False and {v["rule"] for v in check["violations"]} == {"hub"}


def test_overlay_svg_shows_ids_and_violations(tmp_path):
    out = render(S.synth_2hub(), _answer("answer_900002_broken_hub"), tmp_path / "o.svg", S.NODES[900002])
    svg = out.read_text(encoding="utf-8")
    for text in ("H1", "H2", "N6", "INVALID", "Violations"):
        assert text in svg
    out = render(S.synth_1hub(), _answer("answer_900001_valid"), tmp_path / "o.png", S.NODES[900001])
    assert out.read_bytes()[:4] == b"\x89PNG"


def test_overlay_without_answer(tmp_path):
    out = render(S.synth_1hub(), None, tmp_path / "plan.svg", S.NODES[900001])
    assert "No answer loaded" in out.read_text(encoding="utf-8")


def test_export_and_overlay_cli(tmp_path):
    plan_file = tmp_path / "plan.pkl"
    plan_file.write_bytes(pickle.dumps(S.synth_2hub()))
    answer = str(FIX / "answer_900002_valid.json")
    nodes = str(FIX / "nodes_900002.json")
    assert cli.main(["export-plan", "--plan-file", str(plan_file), "--out", str(tmp_path / "b"),
                     "--answer", answer, "--nodes", "file", "--nodes-file", nodes]) == 0
    assert json.loads((tmp_path / "b" / "check.json").read_text())["valid"] is True
    assert cli.main(["overlay", "--plan-file", str(plan_file), "--answer", answer, "--nodes", "file",
                     "--nodes-file", nodes, "--out", str(tmp_path / "o.svg")]) == 0
    assert (tmp_path / "o.svg").exists()


def test_committed_fixture_bundles_are_current():
    index = json.loads(Path("web/data/plans/index.json").read_text(encoding="utf-8"))
    assert len(index["plans"]) == 4
    for entry in index["plans"]:
        folder = Path("web") / entry["path"]
        assert (folder / "plan.json").exists() and (folder / "answer.json").exists()
        check = json.loads((folder / "check.json").read_text(encoding="utf-8"))
        assert check["valid"] is ("broken" not in entry["id"])


def test_bundle_with_branching_and_heatmaps(tmp_path):
    branching = json.loads((FIX / "branching_900002.json").read_text(encoding="utf-8"))
    heatmap = json.loads((FIX / "heatmap_900002_H1.json").read_text(encoding="utf-8"))
    paths = export_bundle(S.synth_2hub(), tmp_path, _answer("answer_900002_valid"), S.NODES[900002],
                          branching, [heatmap])
    assert json.loads(paths["branching"].read_text())["hubs"][0]["hub_id"] == "H1"
    assert json.loads(paths["heatmaps"].read_text())[0]["chosen"] == [1.0, 2.97]


def test_bundle_rejects_bad_branching(tmp_path):
    import pytest
    from eightball.io.answer_io import AnswerError

    with pytest.raises(AnswerError):
        export_bundle(S.synth_2hub(), tmp_path, None, None, {"schema_version": "8ball-branching/1", "hubs": []})


def test_fixture_bundles_ship_branching():
    index = json.loads(Path("web/data/plans/index.json").read_text(encoding="utf-8"))
    with_tree = [e for e in index["plans"] if e["has_branching"]]
    assert {e["id"] for e in with_tree} == {"fixture_900001", "fixture_900002"}
    for e in with_tree:
        assert (Path("web") / e["path"] / "branching.json").exists()
