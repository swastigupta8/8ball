import itertools
import json
import math
import random
from pathlib import Path

import pytest

from eightball.core.contracts import ZoneCandidate, ZoneSolver, zone_candidate_from_json
from eightball.optimize.cpsat import CpSatZoneSolver

FIX = Path(__file__).parent / "fixtures" / "json"


def Z(zid, rooms, cost):
    return ZoneCandidate(zone_id=zid, room_ids=frozenset(rooms), area_m2=0.0, n_nodes=len(rooms), cost=float(cost))


def brute_force(rooms, cands):
    """Exact cover by search: fewest zones first, then lowest cost. Returns (hubs, cost) or None."""
    best = None
    by_room = {r: [c for c in cands if r in c.room_ids] for r in rooms}

    def go(left, chosen, cost):
        nonlocal best
        if not left:
            key = (len(chosen), cost)
            if best is None or key < best:
                best = key
            return
        r = min(left, key=lambda q: len(by_room[q]))
        for c in by_room[r]:
            if c.room_ids <= left:
                go(left - c.room_ids, chosen + [c], cost + c.cost)

    go(frozenset(rooms), [], 0.0)
    return best


def test_matches_zone_solver_protocol():
    solver: ZoneSolver = CpSatZoneSolver()
    assert solver.name == "cpsat"


def test_fixture_zone_candidates():
    data = json.loads((FIX / "zone_candidates_900002.json").read_text(encoding="utf-8"))
    cands = [zone_candidate_from_json(d) for d in data["candidates"]]
    sel = CpSatZoneSolver().select(data["rooms"], cands, data["min_hubs"], 5.0)
    exp = data["expected"]
    assert sel.zone_ids == sorted(exp["zone_ids"]) and sel.hubs == exp["hubs"]
    assert sel.cost == pytest.approx(exp["cost"]) and sel.optimal
    assert sel.bound == pytest.approx(exp["cost"])


def test_fewer_hubs_beat_lower_cost():
    cands = [Z("ab", "ab", 5), Z("c", "c", 3), Z("a", "a", 1), Z("bc", "bc", 2), Z("abc", "abc", 20)]
    sel = CpSatZoneSolver().select(list("abc"), cands, 1, 5.0)
    assert sel.zone_ids == ["abc"] and sel.hubs == 1 and sel.cost == 20


def test_cheapest_split_at_fixed_hub_count():
    cands = [Z("ab", "ab", 5), Z("c", "c", 3), Z("a", "a", 1), Z("bc", "bc", 2)]
    sel = CpSatZoneSolver().select(list("abc"), cands, 1, 5.0)
    assert sel.hubs == 2 and sel.zone_ids == ["a", "bc"] and sel.cost == 3


def test_min_hubs_is_respected():
    cands = [Z("abc", "abc", 20), Z("ab", "ab", 5), Z("c", "c", 3)]
    sel = CpSatZoneSolver().select(list("abc"), cands, 2, 5.0)
    assert sel.hubs == 2 and sel.zone_ids == ["ab", "c"]


def test_uncovered_room_is_infeasible():
    sel = CpSatZoneSolver().select(list("abd"), [Z("ab", "ab", 1)], 1, 2.0)
    assert sel.zone_ids == [] and not sel.optimal and math.isinf(sel.cost)


def test_overlapping_only_cover_is_infeasible():
    sel = CpSatZoneSolver().select(list("abc"), [Z("ab", "ab", 1), Z("bc", "bc", 1)], 1, 2.0)
    assert sel.zone_ids == [] and not sel.optimal


def test_candidates_with_unknown_rooms_are_ignored():
    sel = CpSatZoneSolver().select(list("ab"), [Z("ab", "ab", 4), Z("abx", "abx", 1)], 1, 2.0)
    assert sel.zone_ids == ["ab"]


@pytest.mark.parametrize("seed", range(25))
def test_random_instances_match_brute_force(seed):
    rng = random.Random(seed)
    rooms = [f"r{i}" for i in range(rng.randint(4, 9))]
    cands = [Z(f"s{i}", [r], rng.uniform(1, 10)) for i, r in enumerate(rooms)]  # always feasible
    for k in range(rng.randint(5, 40)):
        size = rng.randint(2, min(5, len(rooms)))
        cands.append(Z(f"m{k}", rng.sample(rooms, size), rng.uniform(1, 30)))
    sel = CpSatZoneSolver().select(rooms, cands, 1, 5.0)
    hubs, cost = brute_force(rooms, cands)
    assert sel.optimal and sel.hubs == hubs and sel.cost == pytest.approx(cost, abs=1e-3)
    chosen = [c for c in cands if c.zone_id in sel.zone_ids]
    assert sorted(r for c in chosen for r in c.room_ids) == sorted(rooms)


def test_large_instance_runs_within_limit():
    """~80 rooms in a row, every contiguous run of 1-5 rooms: the scale of a stitched floor."""
    rooms = [f"r{i:02d}" for i in range(80)]
    cands = [Z(f"z{i}_{n}", rooms[i:i + n], 3 * n * n + 4 + (i % 3)) for i in range(80) for n in range(1, 6)
             if i + n <= 80]
    sel = CpSatZoneSolver().select(rooms, cands, 16, 20.0)
    assert sel.hubs == 16 and sel.optimal
    assert sorted(r for c in cands if c.zone_id in sel.zone_ids for r in c.room_ids) == rooms
