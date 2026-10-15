"""Write the fixture JSON files from synthetic.py: python -m tests.fixtures.make_fixtures"""
from __future__ import annotations

import json
from pathlib import Path

from tests.fixtures import synthetic as S

OUT = Path(__file__).parent / "json"


def _dump(name: str, doc) -> None:
    (OUT / name).write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for plan_id, nodes in S.NODES.items():
        _dump(f"nodes_{plan_id}.json", {"plan_id": plan_id, "mode": "fixture", "nodes": nodes})
    _dump("answer_900001_valid.json", S.answer_1hub())
    _dump("answer_900002_valid.json", S.answer_2hub())
    for rule, ans in S.broken_2hub().items():
        _dump(f"answer_900002_broken_{rule}.json", ans)
    _dump("zone_candidates_900002.json", S.zone_candidates_2hub())
    _dump("heatmap_900002_H1.json", S.heatmap_2hub_h1())
    _dump("branching_900002.json", S.branching_2hub())


if __name__ == "__main__":
    main()
