"""Loading ResPlan plans, splits and scale; the one place room IDs are made (BUILD_SPLIT P0.7)."""
from __future__ import annotations

import json
import pickle
from functools import lru_cache
from pathlib import Path

import shapely
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from eightball import config

ELIGIBLE = ("living", "bedroom", "kitchen", "storage")
EXCLUDED = ("bathroom", "balcony", "stair", "garden", "pool", "parking", "land")
ROOM_TYPES = ELIGIBLE + EXCLUDED


def raw_dir() -> Path:
    return Path(str(config.DATA_DIR)) / "raw"


def normalize_keys(plan: dict) -> dict:
    if "balacony" in plan and "balcony" not in plan:
        plan["balcony"] = plan.pop("balacony")
    return plan


@lru_cache(maxsize=2)
def _load(path: str) -> tuple[dict, ...]:
    with open(path, "rb") as fh:
        plans = pickle.load(fh)
    return tuple(normalize_keys(p) for p in plans)


def load_plans(path: str | Path | None = None) -> tuple[dict, ...]:
    """All plans as dicts. Cached per process; the pickle is ~287 MB."""
    return _load(str(path or raw_dir() / "ResPlan.pkl"))


@lru_cache(maxsize=2)
def _index(path: str) -> dict[int, dict]:
    return {int(p["id"]): p for p in _load(path)}


def get_plan(plan_id: int, path: str | Path | None = None) -> dict:
    return _index(str(path or raw_dir() / "ResPlan.pkl"))[int(plan_id)]


@lru_cache(maxsize=2)
def _splits(path: str) -> dict[str, list[int]]:
    with open(path, encoding="utf-8") as fh:
        return {k: [int(i) for i in v] for k, v in json.load(fh).items()}


def split_ids(name: str, path: str | Path | None = None) -> list[int]:
    """Plan ids of a split: 'train', 'val', 'test' or 'augmented'."""
    return _splits(str(path or raw_dir() / "split.json"))[name]


def scale(plan: dict) -> float:
    """Drawing units per metre (handoff 1.4). Never use net_area."""
    return float((plan["inner"].area / plan["area"]) ** 0.5)


def scale_is_suspicious(s: float) -> bool:
    return s < 8 or s > 40


def parts(geom: BaseGeometry | None) -> list[Polygon]:
    """Single, multi or collection geometry -> list of non-empty polygons."""
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    out: list[Polygon] = []
    for g in getattr(geom, "geoms", []):
        out.extend(parts(g))
    return out


def room_parts(plan: dict) -> list[tuple[str, str, Polygon]]:
    """Every room of the plan as (room_id, type, repaired polygon), in the canonical order.

    Shared by the solver and the checker so their room IDs always match:
      1. types in order living, bedroom, kitchen, storage, then the excluded types;
      2. make_valid, then split into polygon parts;
      3. drop parts below MIN_ROOM_PART_M2;
      4. sort each type's parts by the rounded (minx, miny) of their bounds, then (maxx, maxy), then area;
      5. number them "{type}_{k}" from 0.
    Capacity area is always computed from these repaired polygons.
    """
    s = scale(plan)
    min_units2 = float(config.MIN_ROOM_PART_M2) * s * s
    out: list[tuple[str, str, Polygon]] = []
    for room_type in ROOM_TYPES:
        geom = plan.get(room_type)
        if geom is None or geom.is_empty:
            continue
        polys = [p for p in parts(shapely.make_valid(geom)) if p.area >= min_units2]
        polys.sort(key=lambda p: (round(p.bounds[0]), round(p.bounds[1]), round(p.bounds[2]), round(p.bounds[3]), -p.area))
        out.extend((f"{room_type}_{k}", room_type, p) for k, p in enumerate(polys))
    return out


def dropped_room_parts(plan: dict) -> list[tuple[str, float]]:
    """(type, area_m2) of polygon parts dropped by room_parts, for logging."""
    s = scale(plan)
    min_units2 = float(config.MIN_ROOM_PART_M2) * s * s
    dropped = []
    for room_type in ROOM_TYPES:
        geom = plan.get(room_type)
        if geom is None or geom.is_empty:
            continue
        dropped.extend((room_type, p.area / (s * s)) for p in parts(shapely.make_valid(geom)) if p.area < min_units2)
    return dropped


def eligible_rooms(plan: dict) -> list[tuple[str, str, Polygon]]:
    return [r for r in room_parts(plan) if r[1] in ELIGIBLE]
