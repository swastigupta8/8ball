"""Read, write and structurally validate answer, heatmap and branching JSON (handoff 7.1, 7.5; BUILD_SPLIT 3.1).

This checks *shape* only: schema, legs following the sequence, polylines joining exactly at their
endpoints, axis-aligned segments. Whether a design obeys the hard rules is the checker's job.
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path

import jsonschema

from eightball import config
from eightball.core.contracts import ANSWER_SCHEMA_VERSION, BRANCHING_SCHEMA_VERSION, HEATMAP_SCHEMA_VERSION

JOIN_TOL_UNITS = 1e-6


class AnswerError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@lru_cache(maxsize=None)
def _schema(name: str) -> dict:
    text = resources.files("eightball.core.schema").joinpath(f"{name}.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def _schema_errors(doc: dict, name: str) -> list[str]:
    validator = jsonschema.Draft202012Validator(_schema(name))
    return [f"schema: {'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in validator.iter_errors(doc)]


def _same(p, q) -> bool:
    return abs(p[0] - q[0]) <= JOIN_TOL_UNITS and abs(p[1] - q[1]) <= JOIN_TOL_UNITS


def answer_errors(answer: dict) -> list[str]:
    errors = _schema_errors(answer, "answer")
    if errors:
        return errors
    tol = float(config.TOL_M) * float(answer["scale"])
    points = {n["node_id"]: n["point"] for n in answer["nodes"]}
    hub_ids = [h["hub_id"] for h in answer["hubs"]]
    if len(set(hub_ids)) != len(hub_ids):
        errors.append("duplicate hub_id")
    for hub in answer["hubs"]:
        hid = hub["hub_id"]
        pts = {**points, hid: hub["point"]}
        seq = hub["sequence"]
        if seq[0] != hid or seq[-1] != hid:
            errors.append(f"{hid}: sequence must start and end at the hub")
        for nid in hub["node_ids"]:
            if nid not in points:
                errors.append(f"{hid}: unknown node {nid}")
        if len(hub["legs"]) != len(seq) - 1:
            errors.append(f"{hid}: {len(hub['legs'])} legs for a sequence of {len(seq)} stops (missing return leg?)")
            continue
        for k, leg in enumerate(hub["legs"]):
            where = f"{hid} leg {k}"
            if leg["from"] != seq[k] or leg["to"] != seq[k + 1]:
                errors.append(f"{where}: goes {leg['from']}->{leg['to']}, sequence says {seq[k]}->{seq[k + 1]}")
                continue
            poly = leg["polyline"]
            if leg["from"] in pts and not _same(poly[0], pts[leg["from"]]):
                errors.append(f"{where}: polyline does not start at {leg['from']}")
            if leg["to"] in pts and not _same(poly[-1], pts[leg["to"]]):
                errors.append(f"{where}: polyline does not end at {leg['to']}")
            for a, b in zip(poly, poly[1:]):
                if abs(a[0] - b[0]) > tol and abs(a[1] - b[1]) > tol:
                    errors.append(f"{where}: segment {a}->{b} is not axis-aligned")
    return errors


def validate_answer(answer: dict) -> dict:
    errors = answer_errors(answer)
    if errors:
        raise AnswerError(errors)
    return answer


def write_answer(path: str | Path, answer: dict) -> Path:
    validate_answer(answer)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answer, indent=1), encoding="utf-8")
    return path


def read_answer(path: str | Path) -> dict:
    return validate_answer(json.loads(Path(path).read_text(encoding="utf-8")))


def heatmap_errors(doc: dict) -> list[str]:
    return _schema_errors(doc, "heatmap")


def branching_errors(doc: dict) -> list[str]:
    return _schema_errors(doc, "branching")


def make_heatmap(plan_id: int, hub_id: str, points: list[tuple[float, float, float]],
                 chosen: tuple[float, float], step_m: float | None = None) -> dict:
    return {"schema_version": HEATMAP_SCHEMA_VERSION, "plan_id": int(plan_id), "hub_id": hub_id,
            "step_m": float(config.HEATMAP_STEP_M if step_m is None else step_m),
            "points": [[float(x), float(y), float(v)] for x, y, v in points],
            "chosen": [float(chosen[0]), float(chosen[1])],
            "legend": "extra J for this zone's chosen loop"}


def make_branching(plan_id: int, hubs: list[dict]) -> dict:
    return {"schema_version": BRANCHING_SCHEMA_VERSION, "plan_id": int(plan_id), "hubs": hubs}


def _write(path: str | Path, doc: dict, errors: list[str]) -> Path:
    if errors:
        raise AnswerError(errors)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")
    return path


def write_heatmap(path: str | Path, doc: dict) -> Path:
    return _write(path, doc, heatmap_errors(doc))


def write_branching(path: str | Path, doc: dict) -> Path:
    return _write(path, doc, branching_errors(doc))


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = ["ANSWER_SCHEMA_VERSION", "AnswerError", "answer_errors", "validate_answer", "write_answer",
           "read_answer", "heatmap_errors", "branching_errors", "make_heatmap", "make_branching",
           "write_heatmap", "write_branching", "read_json"]
