"""python -m eightball <command> (BUILD_SPLIT 3.1 item 7). Frozen after Phase 0: nobody edits this file.

Each command dispatches by lazy import to its owner's module, calling ``cli_main(args)``. Flags not
listed here are passed through in ``args.extra`` for the owning module to parse itself.
"""
from __future__ import annotations

import argparse
import importlib
import sys

COMMANDS = {
    "solve": ("eightball.optimize.pipeline", "A", "Solve a plan: answer + overlay + check result"),
    "check": ("eightball.evaluate.checker", "B", "Check an answer against a plan"),
    "export-plan": ("eightball.viz.export", "B", "Export plan geometry to plan.json for the viewer"),
    "overlay": ("eightball.viz.overlay", "B", "Draw the submission overlay (SVG/PNG)"),
    "batch": ("eightball.bench.run_all", "B", "Solve and check many plans; differential test"),
    "audit": ("eightball.bench.audit", "B", "Data audit -> docs/data_facts.md"),
    "stitch": ("eightball.bench.stitch", "B", "Stitched-floor scalability benchmark"),
    "serve": ("eightball.api.server", "B", "Run the API server"),
    "debug": ("eightball.viz.debug", "A", "Debug PNGs of cleaned plans"),
    "finegrid": ("eightball.routing.finegrid", "A", "Fine-grid path-quality check"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="eightball", description="8ball: hub placement and closed-loop cable routing")
    sub = parser.add_subparsers(dest="command", required=True)
    plan_args = {"--plan-id": dict(type=int), "--plan-file": dict(help="pickled or JSON plan dict instead of an id")}
    nodes_args = {"--nodes": dict(default="center", help="center | random | file"),
                  "--nodes-file": dict(help="node JSON when --nodes file")}
    for name, (_mod, owner, help_text) in COMMANDS.items():
        p = sub.add_parser(name, help=f"{help_text} [Person {owner}]")
        if name in ("solve", "check", "export-plan", "overlay", "debug"):
            for flag, kw in plan_args.items():
                p.add_argument(flag, **kw)
        if name in ("solve", "check", "overlay"):
            for flag, kw in nodes_args.items():
                p.add_argument(flag, **kw)
        if name in ("check", "overlay"):
            p.add_argument("--answer", help="answer JSON path")
        if name == "solve":
            p.add_argument("--solver", default="exact", choices=("greedy", "exact"))
        if name in ("batch", "finegrid", "stitch", "debug"):
            p.add_argument("--split", default="train")
            p.add_argument("--limit", type=int)
        if name == "batch":
            p.add_argument("--solver", default="exact", help="comma list: greedy,exact")
            p.add_argument("--nodes", default="center", help="comma list: center,random")
            p.add_argument("--workers", type=int, default=0)
            p.add_argument("--fixture", action="store_true", help="replay fixture answers instead of solving")
            p.add_argument("--name", help="run name for data/out/runs/")
        if name == "overlay":
            p.add_argument("--format", default="svg", choices=("svg", "png"))
        if name == "serve":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
        p.add_argument("--out", help="output file or directory")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args, extra = parser.parse_known_args(argv)
    args.extra = extra
    module_name, owner, _help = COMMANDS[args.command]
    module = importlib.import_module(module_name)
    try:
        return int(module.cli_main(args) or 0)
    except NotImplementedError as exc:
        print(f"'{args.command}' is not built yet ({exc}). Owner: Person {owner}.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
