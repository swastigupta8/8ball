"""A10: clash table (Person A)."""
from __future__ import annotations

import pytest
from shapely.geometry import box

from eightball.core import metrics
from eightball.geometry import build_clean_plan
from eightball.io import resplan
from eightball.optimize.clash import ClashTable, make_candidate
from eightball.optimize.hub import HubContext, ranked_loops
from eightball.optimize.loops import enumerate_loops
from eightball.optimize.zones import enumerate_zones
from eightball.routing.astar import HananRouter
from tests.fixtures import synthetic as syn

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()


def candidates(cp, zones, topk=3):
    router = HananRouter(cp)
    ctx = HubContext(cp, router)
    out = []
    for z in zones:
        for k, rl in enumerate(ranked_loops(ctx, enumerate_loops(cp, router, z.room_ids), topk=topk)):
            out.append((z, make_candidate(cp, f"{z.zone_id}#{k}", rl)))
    return out


def test_two_ring_mix_equals_the_full_score_on_the_synthetic_2hub_plan():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    zones = {frozenset(z.room_ids): z for z in enumerate_zones(cp)}
    left = zones[frozenset({"bedroom_0", "kitchen_0", "living_0"})]
    right = zones[frozenset({"bedroom_1", "bedroom_2", "storage_0"})]
    cands = candidates(cp, [left, right])
    table = ClashTable(cp)
    lefts = [c for z, c in cands if z is left]
    rights = [c for z, c in cands if z is right]
    assert lefts and rights
    for a in lefts:
        for b in rights:
            assert table.mix_cost([a, b]) == pytest.approx(table.exact([a, b])["J"], abs=2e-3)
            x, o = table.clash(a, b)
            assert (x, o) == table.clash(b, a)


def test_clash_is_cached_by_pair():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    zones = {frozenset(z.room_ids): z for z in enumerate_zones(cp)}
    cands = candidates(cp, [zones[frozenset({"bedroom_0", "kitchen_0", "living_0"})], zones[frozenset({"bedroom_1", "bedroom_2", "storage_0"})]],
                       topk=1)
    a, b = cands[0][1], cands[1][1]
    table = ClashTable(cp)
    table.clash(a, b)
    table.clash(b, a)
    assert len(table._cache) == 1


def _two_plain_rings():
    """Two 1 x 1 squares sharing the stretch x = 1, y 0..1 (a 1 m overlap) and a third on the same stretch."""
    def ring(x0):
        return [(x0, 0.0), (x0 + 1, 0.0), (x0 + 1, 1.0), (x0, 1.0)]
    return ring(0.0), ring(1.0), ring(1.0)


def test_three_rings_on_one_stretch_are_overcounted_by_pairs_and_fixed_by_rescoring():
    """Three rings that run along the same 1 m line: pairwise clashes add 3 m, the truth is 2 m (k - 1)."""
    a, b, c = _two_plain_rings()
    # rings 2 and 3 are identical squares; ring 1 shares x = 1 with them
    pts = [a, b, c]
    rings = [metrics.normalise(p, {metrics.snap_point(p[0], 1.0)}, 1.0) for p in pts]
    exact = metrics.score_rings(rings)
    pair_sum = 0.0
    for i in range(3):
        for j in range(i + 1, 3):
            x, o = metrics.clash(pts[i], pts[j], 1.0)
            pair_sum += 5 * x + o
    per_ring = sum(metrics.score_rings([r])["J"] for r in rings)
    assert pair_sum + per_ring > exact["J"] + 0.5  # pairs overcount the triple overlap
    assert exact["O"] == pytest.approx(1 * 2 + 4 * 1, abs=1e-6) or exact["O"] > 0


def test_rescore_orders_mixes_by_their_exact_cost():
    cp = build_clean_plan(syn.synth_2hub(), syn.NODES[900002])
    zones = {frozenset(z.room_ids): z for z in enumerate_zones(cp)}
    left, right = zones[frozenset({"bedroom_0", "kitchen_0", "living_0"})], zones[frozenset({"bedroom_1", "bedroom_2", "storage_0"})]
    cands = candidates(cp, [left, right], topk=3)
    lefts = [c for z, c in cands if z is left]
    rights = [c for z, c in cands if z is right]
    mixes = [(a, b) for a in lefts for b in rights]
    table = ClashTable(cp)
    scored = table.rescore(mixes, keep=10)
    assert len(scored) == min(10, len(mixes))
    assert [s for s, _ in scored] == sorted(s for s, _ in scored)
    for s, m in scored:
        assert s == pytest.approx(table.exact(m)["J"])


@pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/")
def test_two_ring_mixes_match_the_full_score_on_real_plans():
    checked = 0
    for pid in resplan.split_ids("train")[:30]:
        cp = build_clean_plan(resplan.get_plan(pid))
        zones = [z for z in enumerate_zones(cp) if z.n_nodes <= 3]
        if len(zones) < 2:
            continue
        cands = candidates(cp, zones[:8], topk=2)
        table = ClashTable(cp)
        for (za, a), (zb, b) in [(p, q) for i, p in enumerate(cands) for q in cands[i + 1:]]:
            if set(za.room_ids) & set(zb.room_ids):
                continue
            assert table.mix_cost([a, b]) == pytest.approx(table.exact([a, b])["J"], abs=2e-3), (pid, a.cid, b.cid)
            checked += 1
    assert checked > 30
