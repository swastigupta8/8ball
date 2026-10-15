"""PathCost protocol: routing -> optimiser (handoff 7.3). Shared contract; Person A implements it."""
from __future__ import annotations

from typing import Protocol

EAST, NORTH, WEST, SOUTH = 0, 1, 2, 3  # headings: 0=+x, 1=+y, 2=-x, 3=-y
HEADINGS = (EAST, NORTH, WEST, SOUTH)
STEP = {EAST: (1, 0), NORTH: (0, 1), WEST: (-1, 0), SOUTH: (0, -1)}

Point2 = tuple[float, float]
Polyline = list[Point2]


def opposite(heading: int) -> int:
    return (heading + 2) % 4


def turns(h_from: int, h_to: int) -> int:
    """Bends between two headings: 0 straight, 1 for a 90-degree turn or a 180-degree reversal."""
    return 0 if h_from == h_to else 1


def free_point_id(x: float, y: float) -> str:
    """Endpoint id for a free point (e.g. a hub candidate) instead of a node id."""
    return f"P:{x!r},{y!r}"


def parse_point_id(pid: str) -> Point2 | None:
    if not pid.startswith("P:"):
        return None
    x, y = pid[2:].split(",")
    return float(x), float(y)


class Field(Protocol):
    """Direction-aware distance field: cost to reach (point, heading) from the source (or to the target if reversed)."""

    def value(self, point: Point2, heading: int) -> float: ...


class PathCost(Protocol):
    def cost(self, allowed_rooms: frozenset[str], a: str, heading_in: int, b: str, heading_out: int
             ) -> tuple[float, Polyline]:
        """Cheapest axis-aligned path a -> b, leaving a with heading_in and arriving at b with heading_out.

        cost = metres + 0.5 * bends strictly between a and b. The turn at a node is added by the ring
        scorer from the headings, never here, so it isn't counted twice. 'a'/'b' are node ids or
        free_point_id(x, y). Returns (inf, []) when no path exists.
        """
        ...

    def distance_field(self, allowed_rooms: frozenset[str], node: str, heading: int, reverse: bool = False) -> Field:
        """Field from node leaving with heading; reverse=True gives the field *into* node arriving with heading."""
        ...

    def branching_tree(self, allowed_rooms: frozenset[str], hub: Point2, nodes: list[str]) -> dict[str, Polyline]:
        """node_id -> polyline from the hub: the shortest-path tree used for the branching comparison."""
        ...
