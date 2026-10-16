"""Make a sample input for the API from one ResPlan test plan: the plan geometry as WKT text plus the nodes.

Usage (from the 8ball folder):  .venv/Scripts/python.exe sample_input/make_sample.py [plan_id]
Writes sample_input/sample_plan_<id>.json, which is exactly the body of POST /api/solve.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from eightball.io import nodes as nodes_io, resplan  # noqa: E402

plan_id = int(sys.argv[1]) if len(sys.argv) > 1 else resplan.split_ids("test")[321]
plan = resplan.get_plan(plan_id)
geometry_keys = ["living", "bedroom", "bathroom", "kitchen", "storage", "stair", "balcony", "door", "window", "wall",
                 "front_door", "inner", "land", "garden", "pool", "parking"]
body = {"plan": {"id": plan_id, "area": float(plan["area"]), "wall_depth": float(plan["wall_depth"]),
                 **{k: plan[k].wkt for k in geometry_keys if plan.get(k) is not None and not plan[k].is_empty}},
        "nodes": [{"node_id": n["node_id"], "room_id": n["room_id"], "point": n["point"]}
                  for n in nodes_io.make_nodes(plan, "center")],
        "solver": "exact"}
out = Path(__file__).with_name(f"sample_plan_{plan_id}.json")
out.write_text(json.dumps(body, indent=1), encoding="utf-8")
print(f"wrote {out}  ({out.stat().st_size // 1024} KB, {len(body['nodes'])} nodes)")
