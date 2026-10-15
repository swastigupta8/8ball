"""Write viewer bundles for the synthetic fixtures (Person B, B3/B8/B9): python -m eightball.viz.fixture_bundles

Creates web/data/plans/<name>/{plan,answer,check,branching,heatmaps}.json and web/data/plans/index.json,
so the viewer works before the solver exists. Uses tests/fixtures, so run it from the repo root.
"""
from __future__ import annotations

import json
from pathlib import Path

from eightball.viz.export import export_bundle

ROOT = Path("web/data/plans")

# Hand-made branching layout for the 1-hub fixture: the shortest-path tree from H1.
BRANCHING_900001 = {"schema_version": "8ball-branching/1", "plan_id": 900001, "hubs": [
    {"hub_id": "H1", "point": [1.0, 1.97], "paths": {
        "N1": [[1.0, 1.97], [1.0, 2.0], [1.95, 2.0]],
        "N2": [[1.0, 1.97], [1.0, 2.0], [6.05, 2.0]]}},
]}


def main() -> None:
    from tests.fixtures import synthetic as S

    fixtures = Path("tests/fixtures/json")
    branching_2hub = json.loads((fixtures / "branching_900002.json").read_text(encoding="utf-8"))
    heatmap_2hub = json.loads((fixtures / "heatmap_900002_H1.json").read_text(encoding="utf-8"))
    entries = []
    for name, plan_id, answer_file, label, branching, heatmaps in [
        ("fixture_900001", 900001, "answer_900001_valid.json", "Synthetic 2-room flat · 1 hub", BRANCHING_900001, None),
        ("fixture_900002", 900002, "answer_900002_valid.json", "Synthetic 6-room row · 2 hubs", branching_2hub, [heatmap_2hub]),
        ("fixture_900002_broken_zone", 900002, "answer_900002_broken_zone.json", "Broken: zone rule", None, None),
        ("fixture_900002_broken_free_space", 900002, "answer_900002_broken_free_space.json", "Broken: through a wall", None, None),
    ]:
        answer = json.loads((fixtures / answer_file).read_text(encoding="utf-8"))
        export_bundle(S.PLANS[plan_id](), ROOT / name, answer, S.NODES[plan_id], branching, heatmaps)
        entries.append({"id": name, "label": label, "plan_id": plan_id, "path": f"data/plans/{name}",
                        "has_branching": branching is not None, "has_heatmap": heatmaps is not None})
    (ROOT / "index.json").write_text(json.dumps({"plans": entries}, indent=1), encoding="utf-8")
    print(f"wrote {len(entries)} bundles to {ROOT}")


if __name__ == "__main__":
    main()
