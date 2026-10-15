"""Write viewer bundles for the synthetic fixtures (Person B, B3): python -m eightball.viz.fixture_bundles

Creates web/data/plans/<name>/{plan,answer,check}.json and web/data/plans/index.json, so the viewer
works before the solver exists. Uses tests/fixtures, so run it from the repo root.
"""
from __future__ import annotations

import json
from pathlib import Path

from eightball.viz.export import export_bundle

ROOT = Path("web/data/plans")


def main() -> None:
    from tests.fixtures import synthetic as S

    fixtures = Path("tests/fixtures/json")
    entries = []
    for name, plan_id, answer_file, label in [
        ("fixture_900001", 900001, "answer_900001_valid.json", "Synthetic 2-room flat · 1 hub"),
        ("fixture_900002", 900002, "answer_900002_valid.json", "Synthetic 6-room row · 2 hubs"),
        ("fixture_900002_broken_zone", 900002, "answer_900002_broken_zone.json", "Broken: zone rule"),
        ("fixture_900002_broken_free_space", 900002, "answer_900002_broken_free_space.json", "Broken: through a wall"),
    ]:
        answer = json.loads((fixtures / answer_file).read_text(encoding="utf-8"))
        export_bundle(S.PLANS[plan_id](), ROOT / name, answer, S.NODES[plan_id])
        entries.append({"id": name, "label": label, "plan_id": plan_id, "path": f"data/plans/{name}"})
    (ROOT / "index.json").write_text(json.dumps({"plans": entries}, indent=1), encoding="utf-8")
    print(f"wrote {len(entries)} bundles to {ROOT}")


if __name__ == "__main__":
    main()
