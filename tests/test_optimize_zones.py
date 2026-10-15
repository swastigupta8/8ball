"""A7: zone enumeration (Person A)."""
from __future__ import annotations

import itertools
import statistics
import time

import networkx as nx
import pytest

from eightball import config
from eightball.geometry import build_clean_plan
from eightball.io import resplan
from eightball.optimize.zones import enumerate_zones, zone_rooms
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def brute_force(cp) -> set[frozenset[str]]:
    rooms = zone_rooms(cp)
    out = set()
    for k in range(1, int(config.MAX_NODES_PER_HUB) + 1):
        for combo in itertools.combinations(rooms, k):
            if sum(cp.rooms[r].area_m2 for r in combo) > config.MAX_AREA_M2 + 1e-9:
                continue
            sub = cp.links.subgraph(combo)
            if nx.is_connected(sub):
                out.add(frozenset(combo))
    return out


def test_synthetic_chain_matches_the_phase_0_fixture():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    zones = enumerate_zones(cp)
    expected = {frozenset(c["room_ids"]) for c in syn.zone_candidates_2hub()["candidates"]}
    assert {frozenset(z.room_ids) for z in zones} == expected
    assert len(zones) == len(expected) == 18  # contiguous runs of 1-4 rooms; 5 rooms exceed 100 m2
    assert all(z.n_nodes == len(z.room_ids) for z in zones)
    assert len({z.zone_id for z in zones}) == len(zones)


def test_one_hub_plan():
    cp = build_clean_plan(syn.synth_1hub(), syn.NODES[900001])
    assert {frozenset(z.room_ids) for z in enumerate_zones(cp)} == {
        frozenset({"living_0"}), frozenset({"bedroom_0"}), frozenset({"living_0", "bedroom_0"})}


def test_limits_come_from_config():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    old = config.override(MAX_NODES_PER_HUB=2)
    try:
        assert max(z.n_nodes for z in enumerate_zones(cp)) == 2
    finally:
        config.override(**old)
    old = config.override(MAX_AREA_M2=30.0)
    try:
        assert max(z.n_nodes for z in enumerate_zones(cp)) == 1
    finally:
        config.override(**old)


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_matches_brute_force_on_real_plans():
    for pid in resplan.split_ids("train")[:40]:
        cp = build_clean_plan(resplan.get_plan(pid))
        zones = enumerate_zones(cp)
        found = [frozenset(z.room_ids) for z in zones]
        assert len(found) == len(set(found)), f"plan {pid}: duplicate zones"
        assert set(found) == brute_force(cp), f"plan {pid}"


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_counts_and_speed_on_train_sample():
    counts, times = [], []
    for pid in resplan.split_ids("train")[:300]:
        cp = build_clean_plan(resplan.get_plan(pid))
        t0 = time.perf_counter()
        counts.append(len(enumerate_zones(cp)))
        times.append(time.perf_counter() - t0)
    assert 5 <= statistics.median(counts) <= 20, statistics.median(counts)
    assert max(counts) <= 250
    assert statistics.median(times) < 0.001, f"median {statistics.median(times) * 1000:.2f} ms"
