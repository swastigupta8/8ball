import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi import HTTPException
from shapely.geometry import mapping

from eightball.api import server
from eightball.core.contracts import SolveResult
from eightball.io import resplan
from eightball.optimize import pipeline
from tests.fixtures import synthetic as S

FIX = Path(__file__).parent / "fixtures" / "json"
HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists()


def _answer(name):
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


def test_health_reports_solver_state():
    h = server.health()
    assert h["ok"] and h["solver"] in ("ready", "not built")


def test_validate_fixture_answers():
    ok = server.validate(server.ValidateRequest(plan_id=900002, answer=_answer("answer_900002_valid")))
    assert ok["valid"] and ok["metrics"]["J"] == pytest.approx(40.22, abs=0.004)
    bad = server.validate(server.ValidateRequest(plan_id=900002, answer=_answer("answer_900002_broken_hub")))
    assert not bad["valid"] and {v["rule"] for v in bad["violations"]} == {"hub"}


def test_solve_returns_501_until_solver_exists():
    with pytest.raises(HTTPException) as err:
        server.solve(server.SolveRequest(plan_id=900001))
    assert err.value.status_code == 501 and "A4" in err.value.detail


def test_solve_wraps_solver_result(monkeypatch):
    answer = _answer("answer_900002_valid")
    branching = json.loads((FIX / "branching_900002.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(pipeline, "solve", lambda plan, nodes, solver="exact": SolveResult(answer, [], branching, 0.1))
    out = server.solve(server.SolveRequest(plan_id=900002))
    assert out["check"]["valid"] and out["answer"] is answer and out["branching"] is branching
    assert out["plan"]["plan_id"] == 900002 and len(out["plan"]["nodes"]) == 6


def test_plan_from_payload_wkt_and_geojson():
    plan = S.synth_1hub()
    payload = {"id": 7, "area": plan["area"], "inner": plan["inner"].wkt, "wall": mapping(plan["wall"]),
               "door": plan["door"].wkt, "living": plan["living"].wkt, "bedroom": mapping(plan["bedroom"]),
               "front_door": plan["front_door"].wkt, "window": plan["window"].wkt}
    out = server.plan_from_payload(payload)
    assert out["id"] == 7 and resplan.scale(out) == pytest.approx(1.0)
    assert [r[0] for r in resplan.room_parts(out)] == ["living_0", "bedroom_0"]
    result = server.validate(server.ValidateRequest(plan=payload, answer=_answer("answer_900001_valid"),
                                                    nodes=S.NODES[900001]))
    assert result["valid"], result["violations"]


def test_plan_from_payload_needs_inner_and_area():
    with pytest.raises(HTTPException):
        server.plan_from_payload({"area": 10})
    with pytest.raises(HTTPException):
        server.plan_from_payload({"inner": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"})


def test_unknown_plan_is_404():
    if not HAVE_DATA:
        pytest.skip("needs ResPlan data")
    with pytest.raises(HTTPException) as err:
        server.resolve_plan(99_999_999, None)
    assert err.value.status_code == 404


@pytest.mark.skipif(not HAVE_DATA, reason="needs ResPlan data")
def test_plans_and_plan_routes():
    assert server.plans("test", 0, 3)["total"] == 1632
    pj = server.plan(14433)
    assert pj["plan_id"] == 14433 and pj["nodes"]


def test_live_server_serves_viewer_and_api():
    import uvicorn

    config = uvicorn.Config(server.app, host="127.0.0.1", port=8765 + 13, log_level="error")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    try:
        base = "http://127.0.0.1:8778"
        for _ in range(100):
            try:
                with urllib.request.urlopen(base + "/api/health", timeout=1) as r:
                    health = json.loads(r.read())
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.05)
        assert health["ok"]
        with urllib.request.urlopen(base + "/", timeout=2) as r:
            assert b"8ball Viewer" in r.read()
    finally:
        srv.should_exit = True
        thread.join(timeout=5)
