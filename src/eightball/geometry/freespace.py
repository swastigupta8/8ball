"""Free space: where a cable may run (handoff section 6 step 2, BUILD_SPLIT A1).

All geometry is in the plan's drawing units; metres are converted with ``scale`` only for config values.
"""
from __future__ import annotations

import shapely
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from eightball import config
from eightball.io import resplan


def compute_free(inner: BaseGeometry, walls: BaseGeometry, windows: BaseGeometry, front_door: BaseGeometry,
                 scale: float) -> Polygon | MultiPolygon:
    """inner - walls - windows - front door, shrunk by WALL_CLEARANCE_M so cables never touch a wall.

    Walls already have the door shapes subtracted, so door gaps stay open. The shrink uses mitre joins to keep
    the corners of rectilinear rooms square.
    """
    space = inner.difference(walls).difference(windows).difference(front_door)
    shrunk = shapely.buffer(space, -float(config.WALL_CLEARANCE_M) * scale, join_style="mitre", mitre_limit=2.0)
    polys = [p for p in resplan.parts(shrunk) if p.area > 0]
    merged = unary_union(polys) if polys else Polygon()
    return merged
