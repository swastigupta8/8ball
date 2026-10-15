"""Frozen contracts (handoff 7, BUILD_SPLIT 3.1 item 7). Changing anything here needs a contract PR."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import networkx as nx
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

ANSWER_SCHEMA_VERSION = "8ball-answer/1"
HEATMAP_SCHEMA_VERSION = "8ball-heatmap/1"
BRANCHING_SCHEMA_VERSION = "8ball-branching/1"

Point2 = tuple[float, float]


# ---- CleanPlan (geometry -> everyone), handoff 7.2 ----

@dataclass(frozen=True)
class Room:
    id: str
    type: str
    poly: Polygon
    area_m2: float
    eligible: bool
    door_ids: tuple[str, ...]


@dataclass(frozen=True)
class Door:
    id: str
    poly: Polygon
    rooms: tuple[str, str]
    center: Point2
    axis: str  # 'h' | 'v': orientation of the wall the door sits in


@dataclass(frozen=True)
class Passage:
    id: str
    seg: LineString
    rooms: tuple[str, str]


@dataclass(frozen=True)
class Node:
    id: str
    room_id: str
    point: Point2


@dataclass
class CleanPlan:
    plan_id: int
    scale: float
    inner: Polygon
    walls: Polygon | MultiPolygon
    windows: BaseGeometry
    front_door: BaseGeometry
    rooms: dict[str, Room]
    doors: dict[str, Door]
    passages: dict[str, Passage]
    links: nx.Graph  # rooms as graph nodes; edges = door/passage links (front door excluded)
    free: Polygon | MultiPolygon  # inner - walls - windows, shrunk by WALL_CLEARANCE_M
    nodes: dict[str, Node]
    tracks: Any = None  # routing.hanan TrackGrid; every edge tagged with room_id
    flags: list[str] = field(default_factory=list)


# ---- Zone solvers (A: exhaustive, B: CP-SAT), BUILD_SPLIT 3.1 item 7 ----

@dataclass(frozen=True)
class ZoneCandidate:
    zone_id: str
    room_ids: frozenset[str]
    area_m2: float
    n_nodes: int
    cost: float  # best loop J + hub cost, additive (clashes between loops not included)


@dataclass
class ZoneSelection:
    zone_ids: list[str]
    hubs: int
    cost: float
    bound: float | None
    optimal: bool


class ZoneSolver(Protocol):
    def select(self, rooms: list[str], candidates: list[ZoneCandidate],
               min_hubs: int, time_limit_s: float) -> ZoneSelection: ...


# ---- Solver facade (A implements optimize/pipeline.py), BUILD_SPLIT 3.1 item 7 ----

@dataclass
class SolveResult:
    answer: dict          # answer JSON, handoff 7.1
    heatmaps: list[dict]  # one heatmap JSON per hub, handoff 7.5
    branching: dict       # branching JSON
    runtime_s: float


def zone_candidate_to_json(z: ZoneCandidate) -> dict:
    return {"zone_id": z.zone_id, "room_ids": sorted(z.room_ids), "area_m2": z.area_m2,
            "n_nodes": z.n_nodes, "cost": z.cost}


def zone_candidate_from_json(d: dict) -> ZoneCandidate:
    return ZoneCandidate(zone_id=d["zone_id"], room_ids=frozenset(d["room_ids"]), area_m2=float(d["area_m2"]),
                         n_nodes=int(d["n_nodes"]), cost=float(d["cost"]))
