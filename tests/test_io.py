import math

import pytest
from shapely.geometry import MultiPolygon, Polygon, box

from eightball.io import resplan

HAVE_DATA = (resplan.raw_dir() / "ResPlan.pkl").exists() and (resplan.raw_dir() / "split.json").exists()
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="ResPlan data not in data/raw/ (see README)")


def test_parts_handles_single_multi_and_empty():
    a, b = box(0, 0, 1, 1), box(2, 0, 3, 1)
    assert resplan.parts(None) == []
    assert resplan.parts(Polygon()) == []
    assert resplan.parts(a) == [a]
    assert len(resplan.parts(MultiPolygon([a, b]))) == 2


def test_normalize_keys():
    assert resplan.normalize_keys({"balacony": 1}) == {"balcony": 1}


@needs_data
def test_all_plans_load():
    plans = resplan.load_plans()
    assert len(plans) == 17_000
    assert all("balacony" not in p for p in plans)


@needs_data
def test_split_sizes():
    sizes = {name: len(resplan.split_ids(name)) for name in ("train", "val", "test", "augmented")}
    assert sizes == {"train": 13_053, "val": 1_632, "test": 1_632, "augmented": 683}


@needs_data
def test_scale_of_plan_14433():
    plan = resplan.get_plan(14433)
    assert resplan.scale(plan) == pytest.approx(math.sqrt(46029.3 / 120.77), rel=1e-3)


@needs_data
def test_room_parts_deterministic_on_real_plans():
    for pid in resplan.split_ids("train")[:50]:
        plan = resplan.get_plan(pid)
        first = [(r[0], r[2].wkb) for r in resplan.room_parts(plan)]
        assert first == [(r[0], r[2].wkb) for r in resplan.room_parts(plan)]
