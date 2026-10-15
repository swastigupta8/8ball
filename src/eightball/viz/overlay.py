"""Submission overlay (Person B, step B3 / handoff S1.6): one SVG or PNG per plan.

    python -m eightball overlay --plan-id 14433 --answer a.json [--nodes center] --out out.svg [--format svg|png]

Shows walls, doors, windows, zones tinted per hub, hubs (squares) and nodes (circles) with their IDs,
every ring leg in its hub's colour with its visiting-order number (return leg included), violations as
red markers, and a scorecard. Metrics and violations come from the independent checker.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402

from eightball.evaluate import checker  # noqa: E402
from eightball.io import answer_io, nodes as nodes_io  # noqa: E402
from eightball.viz.export import load_plan_arg, plan_json  # noqa: E402

HUB_COLORS = ["#2563A8", "#D2601A", "#1E8A5A", "#8B4FB0", "#C23B73", "#6F7F1F", "#2B8FA6", "#9A6A2E"]
INK = "#1F2328"
QUIET = "#6B7280"
WALL = "#2F3337"
WINDOW = "#7FB8DE"
DOOR = "#EADFC6"
ROOM_FILL = "#F4F4F2"
EXCLUDED_FILL = "#E7E7E4"
BAD = "#D1242F"


def hub_color(k: int) -> str:
    return HUB_COLORS[k % len(HUB_COLORS)]


def _patch(rings, **kw) -> PathPatch:
    verts, codes = [], []
    for ring in rings:
        verts += ring
        codes += [MPath.MOVETO] + [MPath.LINETO] * (len(ring) - 2) + [MPath.CLOSEPOLY]
    return PathPatch(MPath(verts, codes), **kw)


def _leg_label_point(poly):
    best, best_len = None, -1.0
    for a, b in zip(poly, poly[1:]):
        length = abs(a[0] - b[0]) + abs(a[1] - b[1])
        if length > best_len:
            best, best_len = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), length
    return best or tuple(poly[0])


def draw(plan: dict, answer: dict | None, nodes: list[dict] | None = None, result: dict | None = None,
         title: str | None = None):
    pj = plan_json(plan, nodes or (answer["nodes"] if answer else None))
    s = pj["scale"]
    if answer is not None and result is None:
        result = checker.check(plan, answer, nodes)
    minx, miny, maxx, maxy = pj["bounds"]
    w, h = maxx - minx, maxy - miny
    plan_w = 9.0
    plan_h = max(4.0, min(12.0, plan_w * h / w))
    fig = plt.figure(figsize=(plan_w + 3.4, plan_h), dpi=150)
    ax = fig.add_axes([0.0, 0.0, plan_w / (plan_w + 3.4), 1.0])
    side = fig.add_axes([plan_w / (plan_w + 3.4), 0.0, 3.4 / (plan_w + 3.4), 1.0])
    for a in (ax, side):
        a.set_axis_off()
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_aspect("equal")

    zone_of, color_of = {}, {}
    if answer is not None:
        for k, hub in enumerate(answer["hubs"]):
            color_of[hub["hub_id"]] = hub_color(k)
            for rid in hub["room_ids"]:
                zone_of[rid] = hub["hub_id"]

    for rings in pj["inner"]:
        ax.add_patch(_patch(rings, facecolor="white", edgecolor="none", zorder=0))
    for room in pj["rooms"]:
        hub = zone_of.get(room["room_id"])
        if hub:
            face, alpha = color_of[hub], 0.16
        else:
            face, alpha = (ROOM_FILL if room["eligible"] else EXCLUDED_FILL), 1.0
        ax.add_patch(_patch(room["polygon"], facecolor=face, alpha=alpha, edgecolor="none", zorder=1))
        lx, ly = room["label_point"]
        ax.text(lx, ly - 0.35 * s, f"{room['type']}\n{room['room_id']}", fontsize=5, color=QUIET,
                ha="center", va="top", zorder=6, linespacing=1.1)
    for rings in pj["walls"]:
        ax.add_patch(_patch(rings, facecolor=WALL, edgecolor="none", zorder=3))
    for rings in pj["windows"]:
        ax.add_patch(_patch(rings, facecolor=WINDOW, edgecolor="none", zorder=3))
    for rings in pj["doors"]:
        ax.add_patch(_patch(rings, facecolor=DOOR, edgecolor="#C9B98F", linewidth=0.4, zorder=3))
    for rings in pj["front_door"]:
        ax.add_patch(_patch(rings, facecolor="#BFD7C3", edgecolor="none", zorder=3))

    node_pts = {n["node_id"]: n["point"] for n in pj["nodes"]}
    node_hub = {}
    if answer is not None:
        for hub in answer["hubs"]:
            c = color_of[hub["hub_id"]]
            for nid in hub["node_ids"]:
                node_hub[nid] = c
            for k, leg in enumerate(hub["legs"]):
                xs, ys = zip(*leg["polyline"])
                ax.plot(xs, ys, color=c, linewidth=1.6, solid_capstyle="round", solid_joinstyle="round", zorder=7)
                lx, ly = _leg_label_point(leg["polyline"])
                ax.text(lx, ly, str(k + 1), fontsize=5.5, color=c, ha="center", va="center", zorder=9,
                        fontweight="bold",
                        bbox=dict(boxstyle="circle,pad=0.18", facecolor="white", edgecolor=c, linewidth=0.8))
            hx, hy = hub["point"]
            ax.plot([hx], [hy], marker="s", markersize=7.5, color=c, markeredgecolor="white", markeredgewidth=1.0, zorder=10)
            ax.text(hx, hy + 0.32 * s, hub["hub_id"], fontsize=7, color=c, ha="center", va="bottom", zorder=11,
                    fontweight="bold")
    for nid, (nx_, ny_) in node_pts.items():
        c = node_hub.get(nid, QUIET)
        ax.plot([nx_], [ny_], marker="o", markersize=5.5, color="white", markeredgecolor=c, markeredgewidth=1.4, zorder=10)
        ax.text(nx_ + 0.18 * s, ny_ + 0.18 * s, nid, fontsize=6, color=INK, ha="left", va="bottom", zorder=11)

    violations = (result or {}).get("violations", [])
    for v in violations:
        if v.get("location"):
            vx, vy = v["location"]
            ax.plot([vx], [vy], marker="x", markersize=9, color=BAD, markeredgewidth=2.0, zorder=12)

    _scorecard(side, pj, answer, result, title)
    return fig


def _scorecard(side, pj, answer, result, title):
    y = 0.96
    side.text(0.06, y, title or f"Plan {pj['plan_id']}", fontsize=11, fontweight="bold", color=INK, va="top")
    y -= 0.06
    if answer is None:
        side.text(0.06, y, "No answer loaded", fontsize=8, color=QUIET, va="top")
        return
    m = (result or {}).get("metrics", {})
    valid = (result or {}).get("valid")
    side.text(0.06, y, "VALID" if valid else "INVALID", fontsize=10, fontweight="bold",
              color="#1E8A5A" if valid else BAD, va="top")
    y -= 0.06
    rows = [("Hubs", f"{m.get('H', len(answer['hubs']))}"), ("Cable L", f"{m.get('L', 0):.2f} m"),
            ("Crossings X", f"{m.get('X', 0)}"), ("Overlap O", f"{m.get('O', 0):.2f} m"),
            ("Bends B", f"{m.get('B', 0)}"), ("J", f"{m.get('J', 0):.2f}")]
    for label, value in rows:
        bold = label == "J"
        side.text(0.06, y, label, fontsize=8.5, color=QUIET if not bold else INK, va="top",
                  fontweight="bold" if bold else "normal")
        side.text(0.94, y, value, fontsize=8.5, color=INK, va="top", ha="right", fontweight="bold" if bold else "normal")
        y -= 0.045
    side.text(0.06, y, "J = L + 5X + O + 0.5B", fontsize=6.5, color=QUIET, va="top")
    y -= 0.06
    for k, hub in enumerate(answer["hubs"]):
        c = hub_color(k)
        side.text(0.06, y, f"■ {hub['hub_id']}", fontsize=8, color=c, va="top", fontweight="bold")
        side.text(0.30, y, f"{len(hub['node_ids'])} nodes · {hub['area_m2']:.1f} m²", fontsize=7.5, color=INK, va="top")
        y -= 0.04
        side.text(0.30, y, " → ".join(hub["sequence"]), fontsize=6.5, color=QUIET, va="top")
        y -= 0.045
    violations = (result or {}).get("violations", [])
    if violations:
        y -= 0.02
        side.text(0.06, y, f"Violations ({len(violations)})", fontsize=8.5, color=BAD, va="top", fontweight="bold")
        y -= 0.045
        room = max(1, int((y - 0.10) / 0.035))
        shown = violations if len(violations) <= room else violations[:room - 1]
        for v in shown:
            where = f" [{v['hub_id']}]" if v.get("hub_id") else ""
            msg = f"{v['rule']}{where}: {v['message']}"
            side.text(0.06, y, msg[:58] + ("…" if len(msg) > 58 else ""), fontsize=6, color=BAD, va="top")
            y -= 0.035
        if len(shown) < len(violations):
            side.text(0.06, y, f"+ {len(violations) - len(shown)} more (see check.json)", fontsize=6, color=BAD, va="top")
    meta = answer.get("meta", {})
    side.text(0.06, 0.03, f"solver: {meta.get('solver', '?')} · research exercise, not a building-services design",
              fontsize=5.5, color=QUIET, va="bottom")


def render(plan: dict, answer: dict | None, out: str | Path, nodes: list[dict] | None = None,
           result: dict | None = None, fmt: str | None = None) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig = draw(plan, answer, nodes, result)
    fig.savefig(out, format=fmt or out.suffix.lstrip(".") or "svg", facecolor="white")
    plt.close(fig)
    return out


def cli_main(args: argparse.Namespace) -> int:
    plan = load_plan_arg(args)
    answer = answer_io.read_json(args.answer) if args.answer else None
    nodes = None
    if args.nodes == "file":
        nodes = nodes_io.read_nodes_file(args.nodes_file)
    elif answer is None and args.nodes in nodes_io.MODES:
        nodes = nodes_io.get_nodes(plan, args.nodes)
    out = args.out or f"data/out/overlays/{plan['id']}.{args.format}"
    path = render(plan, answer, out, nodes, fmt=args.format)
    print(f"wrote {path}")
    return 0
