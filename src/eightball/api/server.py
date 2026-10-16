"""8ball API (Person B, step B11 / handoff S3.7).

    python -m eightball serve [--host 127.0.0.1] [--port 8000]

Routes (JSON):
  GET  /api/health                 -> {"ok": true, "solver": "ready" | "not built"}
  GET  /api/plans?split=&offset=&limit=   -> plan ids of a split
  GET  /api/plan/{id}?nodes=center  -> viewer plan.json for a ResPlan plan
  POST /api/solve     {plan_id | plan, nodes?, nodes_mode?, solver?}
                      -> {plan, answer, check, heatmaps, branching, runtime_s}
  POST /api/overlay   {plan_id | plan, answer, nodes?, format: svg|png} -> the submission overlay image
  POST /api/validate  {plan_id | plan, answer, nodes?} -> checker result
Every solve is also written to data/out/api/<plan id>/ (answer.json, check.json, branching.json, heatmaps).
The viewer (web/) is served at "/", and calls the API when it's there.

A request may send its own plan instead of a plan_id (the live unseen plan): see `plan_from_payload`.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import tempfile
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from shapely import wkt
from shapely.geometry import shape

from eightball import config
from eightball.evaluate import checker
from eightball.io import nodes as nodes_io, resplan
from eightball.viz.export import plan_json

WEB_DIR = Path(__file__).resolve().parents[3] / "web"
GEOM_KEYS = ("living", "bedroom", "bathroom", "kitchen", "storage", "stair", "balcony", "door", "window", "wall",
             "front_door", "inner", "land", "garden", "pool", "parking", "neighbor")


class SolveRequest(BaseModel):
    plan_id: int | None = None
    plan: dict | None = None
    nodes: list[dict] | None = None
    nodes_mode: str = "center"
    solver: str = "exact"


class OverlayRequest(BaseModel):
    plan_id: int | None = None
    plan: dict | None = None
    answer: dict
    nodes: list[dict] | None = None
    nodes_mode: str = "center"
    format: str = "svg"


class ValidateRequest(BaseModel):
    plan_id: int | None = None
    plan: dict | None = None
    answer: dict
    nodes: list[dict] | None = None
    nodes_mode: str = "center"


def plan_from_payload(payload: dict) -> dict:
    """Organiser-input adapter: a plan sent as JSON instead of a ResPlan id.

    Accepted until the organisers publish their format (open question 3): an object with "id",
    "area" (m^2, used for the scale) and each geometry key as WKT text or a GeoJSON geometry. Missing
    keys become empty geometries.
    """
    from shapely.geometry import Polygon

    plan: dict = {}
    for key in GEOM_KEYS:
        raw = payload.get(key)
        if raw is None:
            plan[key] = Polygon()
        elif isinstance(raw, str):
            plan[key] = wkt.loads(raw)
        else:
            plan[key] = shape(raw)
    if plan["inner"].is_empty:
        raise HTTPException(422, "plan needs an 'inner' geometry")
    if "area" not in payload:
        raise HTTPException(422, "plan needs 'area' in m^2 (used to convert drawing units to metres)")
    plan.update({"id": int(payload.get("id", 0)), "area": float(payload["area"]),
                 "wall_depth": payload.get("wall_depth"), "net_area": payload.get("net_area", 0.0), "graph": None})
    return resplan.normalize_keys(plan)


def _fixture_plan(plan_id: int) -> dict | None:
    try:
        from tests.fixtures import synthetic
    except ImportError:
        return None
    maker = synthetic.PLANS.get(plan_id)
    return maker() if maker else None


def resolve_plan(plan_id: int | None, plan: dict | None) -> dict:
    if plan is not None:
        return plan_from_payload(plan)
    if plan_id is None:
        raise HTTPException(422, "send plan_id or plan")
    fixture = _fixture_plan(plan_id)
    if fixture is not None:
        return fixture
    try:
        return resplan.get_plan(plan_id)
    except FileNotFoundError:
        raise HTTPException(503, "ResPlan data isn't on this machine (data/raw/ResPlan.pkl)")
    except KeyError:
        raise HTTPException(404, f"no plan with id {plan_id}")


def resolve_nodes(plan: dict, nodes: list[dict] | None, mode: str) -> list[dict]:
    if nodes:
        return nodes
    if int(plan["id"]) in (900001, 900002):
        from tests.fixtures import synthetic

        return synthetic.NODES[int(plan["id"])]
    if mode not in nodes_io.MODES:
        raise HTTPException(422, f"nodes_mode must be one of {nodes_io.MODES}")
    return nodes_io.make_nodes(plan, mode)


def solver_status() -> str:
    from eightball.optimize import pipeline

    try:
        pipeline.solve({}, [], solver="greedy")
    except NotImplementedError:
        return "not built"
    except Exception:
        return "ready"
    return "ready"


_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)


def save_outputs(plan: dict, answer: dict, check: dict, heatmaps: list[dict], branching: dict) -> str | None:
    """Keep every solve on disk: data/out/api/<plan id>/answer.json (the deliverable) plus its check, heatmaps and
    branching. Returns the folder, or None if it could not be written (the response is sent either way)."""
    try:
        folder = Path(str(config.DATA_DIR)) / "out" / "api" / str(plan["id"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "answer.json").write_text(json.dumps(answer, indent=1), encoding="utf-8")
        (folder / "check.json").write_text(json.dumps(check, indent=1), encoding="utf-8")
        (folder / "branching.json").write_text(json.dumps(branching, indent=1), encoding="utf-8")
        for hm in heatmaps:
            (folder / f"heatmap_{hm['hub_id']}.json").write_text(json.dumps(hm, indent=1), encoding="utf-8")
        return folder.as_posix()
    except OSError:
        return None


def run_solve(plan: dict, nodes: list[dict], solver: str) -> dict:
    from eightball.optimize import pipeline

    t0 = time.perf_counter()
    future = _POOL.submit(pipeline.solve, plan, nodes, solver)
    limit = 1.5 * float(config.TIME_BUDGET_S) + 5.0
    try:
        result = future.result(timeout=limit)
    except NotImplementedError as exc:
        raise HTTPException(501, f"the solver isn't built yet ({exc})")
    except concurrent.futures.TimeoutError:
        raise HTTPException(504, f"solver gave no answer within {limit:.0f} s")
    answer = result.answer
    check = checker.check(plan, answer, nodes)
    return {
        "plan": plan_json(plan, nodes),
        "answer": answer,
        "check": check,
        "heatmaps": result.heatmaps,
        "branching": result.branching,
        "runtime_s": round(time.perf_counter() - t0, 3),
        "saved_to": save_outputs(plan, answer, check, result.heatmaps, result.branching),
    }


app = FastAPI(title="8ball", version="0.1.0")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "solver": solver_status(), "time_budget_s": float(config.TIME_BUDGET_S),
            "config_hash": config.config_hash()}


@app.get("/api/plans")
def plans(split: str = "test", offset: int = 0, limit: int = 100) -> dict:
    try:
        ids = resplan.split_ids(split)
    except FileNotFoundError:
        raise HTTPException(503, "ResPlan data isn't on this machine (data/raw/split.json)")
    except KeyError:
        raise HTTPException(404, f"no split '{split}'")
    return {"split": split, "total": len(ids), "plan_ids": ids[offset:offset + limit]}


@app.get("/api/plan/{plan_id}")
def plan(plan_id: int, nodes: str = "center") -> dict:
    raw = resolve_plan(plan_id, None)
    return plan_json(raw, resolve_nodes(raw, None, nodes))


@app.post("/api/solve")
def solve(req: SolveRequest) -> dict:
    raw = resolve_plan(req.plan_id, req.plan)
    nodes = resolve_nodes(raw, req.nodes, req.nodes_mode)
    return run_solve(raw, nodes, req.solver)


@app.post("/api/overlay")
def overlay(req: OverlayRequest) -> Response:
    """The submission overlay (zones, hubs, rings, scorecard) of an answer, as SVG or PNG for download."""
    from eightball.viz import overlay as overlay_mod

    fmt = req.format.lower()
    if fmt not in ("svg", "png"):
        raise HTTPException(422, "format must be svg or png")
    raw = resolve_plan(req.plan_id, req.plan)
    nodes = resolve_nodes(raw, req.nodes, req.nodes_mode)
    with tempfile.TemporaryDirectory() as tmp:
        path = overlay_mod.render(raw, req.answer, Path(tmp) / f"overlay.{fmt}", nodes, fmt=fmt)
        data = path.read_bytes()
    media = "image/svg+xml" if fmt == "svg" else "image/png"
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="overlay_{raw["id"]}.{fmt}"'})


@app.post("/api/validate")
def validate(req: ValidateRequest) -> dict:
    raw = resolve_plan(req.plan_id, req.plan)
    nodes = resolve_nodes(raw, req.nodes, req.nodes_mode)
    return checker.check(raw, req.answer, nodes)


@app.exception_handler(ValueError)
def value_error(_request, exc: ValueError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")


def cli_main(args: argparse.Namespace) -> int:
    import uvicorn

    print(f"8ball API + viewer on http://{args.host}:{args.port}  (solver: {solver_status()})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    return 0
