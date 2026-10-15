"""Node points: practice generation (handoff 8.3) and node files. Shared input layer (BUILD_SPLIT P0.7).

A node list is ``[{"node_id": "N1", "room_id": "bedroom_0", "point": [x, y]}, ...]`` in drawing units,
one per eligible room, numbered N1..Nn in room-ID order (the order of ``resplan.eligible_rooms``).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from shapely.geometry import Point, Polygon
from shapely.ops import polylabel

from eightball import config
from eightball.io import resplan

MODES = ("center", "random")


def _largest(geom) -> Polygon | None:
    polys = resplan.parts(geom)
    return max(polys, key=lambda p: p.area) if polys else None


def _center_point(room: Polygon, s: float) -> tuple[tuple[float, float], str | None]:
    shrunk = _largest(room.buffer(-float(config.NODE_CLEARANCE_M) * s))
    if shrunk is None:
        p = polylabel(room, tolerance=0.01 * s)
        return (p.x, p.y), "node_clearance_fallback"
    p = polylabel(shrunk, tolerance=0.01 * s)
    return (p.x, p.y), None


def _random_point(room: Polygon, s: float, rng: random.Random) -> tuple[tuple[float, float], str | None]:
    shrunk = _largest(room.buffer(-float(config.NODE_CLEARANCE_M) * s))
    target, flag = (shrunk, None) if shrunk is not None else (room, "node_clearance_fallback")
    minx, miny, maxx, maxy = target.bounds
    for _ in range(10_000):
        x, y = rng.uniform(minx, maxx), rng.uniform(miny, maxy)
        if target.contains(Point(x, y)):
            return (x, y), flag
    p = target.representative_point()
    return (p.x, p.y), "node_random_fallback"


def make_nodes(plan: dict, mode: str = "center", seed: int | None = None) -> list[dict]:
    """One practice node per eligible room. Entries may carry a "flag" key when a fallback was used."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    s = resplan.scale(plan)
    rng = random.Random((int(config.SEED) if seed is None else seed) * 1_000_003 + int(plan["id"]))
    nodes = []
    for k, (room_id, _type, poly) in enumerate(resplan.eligible_rooms(plan), start=1):
        point, flag = _center_point(poly, s) if mode == "center" else _random_point(poly, s, rng)
        node = {"node_id": f"N{k}", "room_id": room_id, "point": [float(point[0]), float(point[1])]}
        if flag:
            node["flag"] = flag
        nodes.append(node)
    return nodes


def nodes_path(plan_id: int, mode: str) -> Path:
    return Path(str(config.DATA_DIR)) / "nodes" / mode / f"{int(plan_id)}.json"


def save_nodes(plan_id: int, nodes: list[dict], mode: str) -> Path:
    path = nodes_path(plan_id, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"plan_id": int(plan_id), "mode": mode, "nodes": nodes}, indent=1), encoding="utf-8")
    return path


def read_nodes_file(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["nodes"] if isinstance(data, dict) else data


def get_nodes(plan: dict, mode: str = "center") -> list[dict]:
    """Cached practice nodes for a plan: read from data/nodes/{mode}/ or generate and save."""
    path = nodes_path(plan["id"], mode)
    if path.exists():
        return read_nodes_file(path)
    nodes = make_nodes(plan, mode)
    save_nodes(plan["id"], nodes, mode)
    return nodes


def read_organiser_nodes(path: str | Path, plan: dict) -> list[dict]:
    """Adapter for the organisers' node format, once they publish it (open question 3)."""
    raise NotImplementedError("organiser node format not known yet; see docs/OPEN_QUESTIONS.md")
