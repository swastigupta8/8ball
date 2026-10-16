"""Export a plan for the web viewer (Person B, step B3).

    python -m eightball export-plan --plan-id 14433 --out web/data/plans/14433 [--answer a.json] [--nodes center]

Writes `plan.json` (drawing units, the plan's own frame). With --answer it also writes `answer.json`
and `check.json` (the checker's verdict), so the folder is everything the viewer needs.

plan.json ("8ball-plan/1"): polygons are lists of rings, each ring a list of [x, y]; the first ring is
the exterior, the rest are holes. Built from the raw plan with the checker's geometry (walls with doors
cut out, outdoor areas left out), never from Person A's cleaning.
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from eightball.evaluate import checker, geom_indep
from eightball.io import answer_io, nodes as nodes_io, resplan

PLAN_SCHEMA_VERSION = "8ball-plan/1"


def _round(v: float) -> float:
    return round(float(v), 4)


def _rings(poly: Polygon) -> list[list[list[float]]]:
    return [[[_round(x), _round(y)] for x, y in ring.coords]
            for ring in [poly.exterior, *poly.interiors]]


def _polys(geom: BaseGeometry | None) -> list:
    return [_rings(p) for p in resplan.parts(geom)]


def plan_json(plan: dict, nodes: list[dict] | None = None) -> dict:
    g = geom_indep.build(plan)
    minx, miny, maxx, maxy = unary_union([g.inner, g.walls, *g.rooms.values()]).bounds
    pad = 0.5 * g.scale
    rooms = [{"room_id": rid, "type": g.room_type[rid], "eligible": rid in g.eligible,
              "area_m2": round(g.area_m2[rid], 3), "polygon": _rings(poly),
              "label_point": [_round(c) for c in poly.representative_point().coords[0]]}
             for rid, poly in g.rooms.items()]
    links = [{"a": a, "b": b, "kind": d["kind"]} for a, b, d in g.links.edges(data=True)]
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "plan_id": int(plan["id"]),
        "scale": g.scale,
        "bounds": [_round(minx - pad), _round(miny - pad), _round(maxx + pad), _round(maxy + pad)],
        "inner": _polys(g.inner),
        "walls": _polys(g.walls),
        "windows": _polys(g.windows),
        "doors": [_rings(d) for d in g.doors],
        "front_door": _polys(plan.get("front_door")),
        "passages": _polys(unary_union(g.passages)) if g.passages else [],
        "rooms": rooms,
        "links": links,
        "nodes": nodes or [],
    }


def heatmap_check(heatmap: dict, scale: float) -> dict:
    """Is the chosen hub the cheapest heatmap spot? (handoff S3.5 / solver step 6: same function)

    The chosen point itself is always among the points; it passes when no point is cheaper."""
    pts = heatmap["points"]
    if not pts:
        return {"ok": False, "min": None, "chosen_value": None}
    best = min(pts, key=lambda p: p[2])
    cx, cy = heatmap["chosen"]
    at_chosen = [p[2] for p in pts if abs(p[0] - cx) <= 1e-6 * scale and abs(p[1] - cy) <= 1e-6 * scale]
    if at_chosen:
        ok = at_chosen[0] <= best[2] + 1e-9
    else:
        ok = ((best[0] - cx) ** 2 + (best[1] - cy) ** 2) ** 0.5 <= heatmap["step_m"] * scale + 1e-9
    return {"ok": ok, "min": best, "chosen_value": at_chosen[0] if at_chosen else None}


def export_bundle(plan: dict, out_dir: str | Path, answer: dict | None = None,
                  nodes: list[dict] | None = None, branching: dict | None = None,
                  heatmaps: list[dict] | None = None) -> dict[str, Path]:
    """Write a viewer bundle. Optional extras: branching.json (break-the-cable comparison) and
    heatmaps.json (one heatmap per hub), both straight from the solver's SolveResult."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    nodes = nodes if nodes is not None else (answer["nodes"] if answer else None)
    paths = {"plan": out / "plan.json"}
    paths["plan"].write_text(json.dumps(plan_json(plan, nodes)), encoding="utf-8")
    if answer is not None:
        paths["answer"] = out / "answer.json"
        paths["answer"].write_text(json.dumps(answer, indent=1), encoding="utf-8")
        paths["check"] = out / "check.json"
        paths["check"].write_text(json.dumps(checker.check(plan, answer, nodes), indent=1), encoding="utf-8")
    if branching:
        errors = answer_io.branching_errors(branching)
        if errors:
            raise answer_io.AnswerError(errors)
        paths["branching"] = out / "branching.json"
        paths["branching"].write_text(json.dumps(branching, indent=1), encoding="utf-8")
    if heatmaps:
        errors = [e for h in heatmaps for e in answer_io.heatmap_errors(h)]
        if errors:
            raise answer_io.AnswerError(errors)
        paths["heatmaps"] = out / "heatmaps.json"
        paths["heatmaps"].write_text(json.dumps(heatmaps, indent=1), encoding="utf-8")
    return paths


def load_plan_arg(args) -> dict:
    if getattr(args, "plan_file", None):
        with open(args.plan_file, "rb") as fh:
            return resplan.normalize_keys(pickle.load(fh))
    return resplan.get_plan(args.plan_id)


def cli_main(args: argparse.Namespace) -> int:
    own = argparse.ArgumentParser(prog="eightball export-plan")
    own.add_argument("--answer")
    own.add_argument("--nodes", default=None, help="center | random | file")
    own.add_argument("--nodes-file")
    extra = own.parse_args(getattr(args, "extra", []))
    plan = load_plan_arg(args)
    answer = answer_io.read_json(extra.answer) if extra.answer else None
    nodes = None
    if extra.nodes == "file":
        nodes = nodes_io.read_nodes_file(extra.nodes_file)
    elif extra.nodes in nodes_io.MODES:
        nodes = nodes_io.get_nodes(plan, extra.nodes)
    out = args.out or f"web/data/plans/{plan['id']}"
    paths = export_bundle(plan, out, answer, nodes)
    print("wrote " + ", ".join(str(p) for p in paths.values()))
    return 0
