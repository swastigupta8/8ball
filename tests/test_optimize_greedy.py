"""A4: greedy baseline, solve facade, solve CLI (Person A).

Person A never reads evaluate/, so these checks are our own: coverage, capacity, zone, ring shape, free space,
hub point and "no overlap inside a ring". The independent checker runs at checkpoint I1.
"""
from __future__ import annotations

import json
import math

import networkx as nx
import pytest
from shapely.geometry import LineString, Point

from eightball import config
from eightball.core import metrics
from eightball.geometry import build_clean_plan
from eightball.io import answer_io, nodes as nodes_io, resplan
from eightball.optimize import pipeline
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def own_checks(plan: dict, nodes: list[dict], answer: dict) -> list[str]:
    cp = build_clean_plan(plan, nodes)
    s = cp.scale
    problems: list[str] = list(answer_io.answer_errors(answer))
    eligible = {rid for rid, r in cp.rooms.items() if r.eligible}
    assigned = [rid for h in answer["hubs"] for rid in h["room_ids"]]
    if sorted(assigned) != sorted(eligible):
        problems.append(f"coverage: {sorted(assigned)} vs {sorted(eligible)}")
    node_room = {n["node_id"]: n["room_id"] for n in answer["nodes"]}
    free = cp.free.buffer(1e-6 * s)
    for h in answer["hubs"]:
        hid = h["hub_id"]
        if sum(cp.rooms[r].area_m2 for r in h["room_ids"]) > config.MAX_AREA_M2 + 1e-9 or len(h["node_ids"]) > 5:
            problems.append(f"{hid}: capacity")
        if {node_room[n] for n in h["node_ids"]} != set(h["room_ids"]):
            problems.append(f"{hid}: node/room mismatch")
        zone = cp.links.subgraph(h["room_ids"])
        if not nx.is_connected(zone):
            problems.append(f"{hid}: zone not connected")
        hub_room = cp.rooms[h["room_id"]]
        hp = Point(h["point"])
        if h["room_id"] not in h["room_ids"] or not hub_room.poly.contains(hp) or \
                hub_room.poly.exterior.distance(hp) < config.HUB_CLEARANCE_M * s - 1e-6:
            problems.append(f"{hid}: hub point")
        if sorted(h["sequence"][1:-1]) != sorted(h["node_ids"]):
            problems.append(f"{hid}: sequence")
        for leg in h["legs"]:
            if not free.covers(LineString(leg["polyline"])):
                problems.append(f"{hid} {leg['from']}->{leg['to']}: leaves the free space")
    result = metrics.score(answer, s)
    for hid, per in result["per_hub"].items():
        if per["O"] > 0.002:
            problems.append(f"{hid}: overlaps itself by {per['O']:.3f} m")
    for key in ("L", "X", "O", "B", "J"):
        if abs(result[key] - answer["metrics"][key]) > 1e-9:
            problems.append(f"metrics.{key} not from core.metrics")
    return problems


@pytest.mark.parametrize("plan_id", [900001, 900002])
def test_synthetic_plans(plan_id):
    plan = syn.PLANS[plan_id]()
    nodes = syn.NODES[plan_id]
    result = pipeline.solve(plan, nodes, "greedy")
    assert own_checks(plan, nodes, result.answer) == []
    assert result.answer["metrics"]["H"] == (1 if plan_id == 900001 else 2)
    assert result.answer["meta"]["min_hubs_bound"] == result.answer["metrics"]["H"]
    assert result.heatmaps == [] and result.branching["schema_version"] == "8ball-branching/1"
    assert answer_io.branching_errors(result.branching) == []
    assert {h["hub_id"] for h in result.branching["hubs"]} == {h["hub_id"] for h in result.answer["hubs"]}


def test_exact_solver_is_labelled_and_unknown_solvers_are_refused():
    plan = syn.synth_1hub()
    result = pipeline.solve(plan, syn.NODES[900001], "exact")
    assert result.answer["meta"]["solver"] == "exact"
    greedy = pipeline.solve(plan, syn.NODES[900001], "greedy")
    assert result.answer["metrics"]["J"] <= greedy.answer["metrics"]["J"] + 1e-9
    with pytest.raises(ValueError):
        pipeline.solve(plan, syn.NODES[900001], "magic")


def test_solve_is_deterministic():
    plan, nodes = syn.synth_2hub(), syn.NODES[900002]
    a = pipeline.solve(plan, nodes, "greedy").answer
    b = pipeline.solve(plan, nodes, "greedy").answer
    for doc in (a, b):
        doc["meta"].pop("runtime_s")
    assert a == b


def test_solve_cli_writes_valid_files(tmp_path):
    from eightball.cli import main

    assert main(["solve", "--plan-id", "900002", "--solver", "greedy", "--out", str(tmp_path)]) == 0
    answer = answer_io.read_answer(tmp_path / "answer.json")
    assert answer["metrics"]["H"] == 2
    assert answer_io.branching_errors(json.loads((tmp_path / "branching.json").read_text())) == []


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
@pytest.mark.parametrize("mode", ["center", "random"])
def test_ten_train_plans_pass_our_own_checks(mode):
    for pid in resplan.split_ids("train")[:10]:
        plan = resplan.get_plan(pid)
        nodes = nodes_io.make_nodes(plan, mode)
        result = pipeline.solve(plan, nodes, "greedy")
        assert own_checks(plan, nodes, result.answer) == [], f"plan {pid} ({mode})"
        assert result.answer["metrics"]["H"] >= result.answer["meta"]["min_hubs_bound"]
        assert math.isfinite(result.answer["metrics"]["J"])


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_demo_plan_14433():
    plan = resplan.get_plan(14433)
    nodes = nodes_io.make_nodes(plan, "center")
    result = pipeline.solve(plan, nodes, "greedy")
    assert own_checks(plan, nodes, result.answer) == []
