"""Debug PNGs of a CleanPlan: rooms, doors, links, free space, nodes (handoff S1.1).

Owner: Person A, step A1 (docs/BUILD_SPLIT.md).
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from eightball import config  # noqa: E402
from eightball.core.contracts import CleanPlan  # noqa: E402
from eightball.geometry.clean import build_clean_plan  # noqa: E402
from eightball.io import resplan  # noqa: E402

COLORS = {"living": "#f6d7a7", "bedroom": "#bcd7f5", "kitchen": "#c8e6b0", "storage": "#e1c7ef",
          "bathroom": "#d9d9d9", "balcony": "#f0f0c0", "stair": "#cfcfcf", "garden": "#e8f5e0",
          "pool": "#c5ecf5", "parking": "#e6e6e6", "land": "#f7f7f7"}


def _draw_geom(ax, geom, **kw) -> None:
    for poly in resplan.parts(geom):
        x, y = poly.exterior.xy
        ax.fill(x, y, **kw)
        for ring in poly.interiors:
            hx, hy = ring.xy
            ax.fill(hx, hy, color="white", zorder=kw.get("zorder", 1) + 0.1)


def plot_clean_plan(cp: CleanPlan, path: str | Path) -> Path:
    fig, ax = plt.subplots(figsize=(10, 10))
    for room in cp.rooms.values():
        if room.type == "land":
            continue
        _draw_geom(ax, room.poly, facecolor=COLORS.get(room.type, "#eee"), edgecolor="#888", linewidth=0.8, zorder=1)
        c = room.poly.representative_point()
        ax.text(c.x, c.y, f"{room.id}\n{room.area_m2:.1f} m²", ha="center", va="center", fontsize=7, zorder=6)
    _draw_geom(ax, cp.walls, facecolor="#555", edgecolor="none", zorder=2)
    _draw_geom(ax, cp.windows, facecolor="#4aa3e0", edgecolor="none", zorder=3)
    _draw_geom(ax, cp.front_door, facecolor="#c0392b", edgecolor="none", zorder=3)
    for poly in resplan.parts(cp.free):
        ax.plot(*poly.exterior.xy, color="#2a9d8f", linewidth=0.6, linestyle=":", zorder=4)
        for ring in poly.interiors:
            ax.plot(*ring.xy, color="#2a9d8f", linewidth=0.6, linestyle=":", zorder=4)
    for door in cp.doors.values():
        _draw_geom(ax, door.poly, facecolor="#f39c12", edgecolor="none", zorder=3)
    for p in cp.passages.values():
        ax.plot(*p.seg.xy, color="#27ae60", linewidth=3, zorder=5)
    for a, b, data in cp.links.edges(data=True):
        pa, pb = cp.rooms[a].poly.representative_point(), cp.rooms[b].poly.representative_point()
        ax.plot([pa.x, pb.x], [pa.y, pb.y], color="#8e44ad", linewidth=1, linestyle="--", zorder=5)
    for node in cp.nodes.values():
        ax.plot(*node.point, "o", color="#e63946", markersize=6, zorder=7)
        ax.text(node.point[0], node.point[1], node.id, fontsize=7, color="#e63946", zorder=7, va="bottom")
    ax.set_aspect("equal")
    ax.invert_yaxis()
    title = f"plan {cp.plan_id}  scale {cp.scale:.2f}  doors {len(cp.doors)}  passages {len(cp.passages)}"
    if cp.flags:
        title += f"\nflags: {', '.join(cp.flags[:6])}"
    ax.set_title(title, fontsize=9)
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out


def _synthetic(plan_id: int) -> dict | None:
    try:
        from tests.fixtures import synthetic
    except ImportError:
        return None
    return synthetic.PLANS[plan_id]() if plan_id in synthetic.PLANS else None


def cli_main(args: argparse.Namespace) -> int:
    """debug --plan-id ID | --split NAME [--limit N] [--out DIR]: write PNGs; flag and continue on errors."""
    out_dir = Path(args.out or Path(str(config.DATA_DIR)) / "out" / "debug")
    if args.plan_id is not None:
        plan = _synthetic(args.plan_id) or resplan.get_plan(args.plan_id)
        plans = [plan]
    else:
        ids = resplan.split_ids(args.split)
        plans = [resplan.get_plan(i) for i in (ids[:args.limit] if args.limit else ids)]
    failures = 0
    for plan in plans:
        try:
            cp = build_clean_plan(plan)
            plot_clean_plan(cp, out_dir / f"{cp.plan_id}.png")
        except Exception:  # noqa: BLE001 - flag and continue over a whole split
            failures += 1
            print(f"plan {plan.get('id')}: FAILED", file=sys.stderr)
            traceback.print_exc()
    print(f"{len(plans) - failures}/{len(plans)} plans written to {out_dir}")
    return 1 if failures else 0
