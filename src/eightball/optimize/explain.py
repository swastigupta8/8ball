"""Why this answer? (V3 feature: explain / audit mode).

  explain(plan_raw, nodes, answer)   the reasons behind an answer, as plain data for the viewer

Three layers, each from the solver's own functions (nothing is re-implemented, no rule changes, the answer is not touched):

  hubs    the counting lower bound (nodes per hub, area per hub), how many legal zones and fewest-hub splits exist
  groups  the best few ways to split the rooms into the same number of hubs, each with its cost before polishing,
          the extra cost its cables would add by clashing, and a full answer for the top few so the viewer can draw it
  routes  per hub: the cheapest loop orders of its zone and the cheapest hub spots (the heatmap's numbers)

Costs of the runner-ups are the solver's search costs (best loop mix of each split, exact J, before the final polish),
and the chosen split is priced the same way, so every gap compares like with like.
"""
from __future__ import annotations

import time

from eightball import config
from eightball.core import metrics
from eightball.optimize import ladder, pipeline
from eightball.optimize.clash import ClashTable, make_candidate
from eightball.optimize.hub import heatmap_points, ranked_loops
from eightball.optimize.loops import enumerate_loops
from eightball.optimize.whatif import _LOCK, context
from eightball.optimize.zones import enumerate_zones, zone_rooms

SPLITS_SHOWN = 6        # runner-up groupings listed
SPLITS_WITH_ANSWER = 4  # of those, how many come with a full answer to draw
LOOPS_SHOWN = 3
SPOTS_SHOWN = 3


def _canon(order) -> tuple[str, ...]:
    """A visiting order up to rotation and direction."""
    order = list(order)
    best = None
    for seq in (order, order[::-1]):
        k = seq.index(min(seq))
        rot = tuple(seq[k:] + seq[:k])
        if best is None or rot < best:
            best = rot
    return best


def _hubs_layer(cp, rooms, zones, answer, hubs_found, notes) -> dict:
    n_nodes = len(rooms)
    area = round(sum(cp.rooms[r].area_m2 for r in rooms), 2)
    max_n, max_a = int(config.MAX_NODES_PER_HUB), float(config.MAX_AREA_M2)
    by_nodes = -(-n_nodes // max_n)
    import math
    by_area = max(1, math.ceil(area / max_a - 1e-9))
    bound = ladder.min_hub_bound(cp, rooms)
    binding = "both" if by_nodes == by_area else ("devices" if by_nodes > by_area else "area")
    used = answer["metrics"]["H"]
    out = {"devices": n_nodes, "area_m2": area, "max_devices": max_n, "max_area_m2": max_a,
           "by_devices": by_nodes, "by_area": by_area, "bound": bound, "binding": binding, "hubs_used": used,
           "legal_zones": len(zones), "meets_bound": used == bound, "notes": list(notes)}
    def hubs(n):
        return f"{n} hub" + ("" if n == 1 else "s")
    if used == bound:
        out["summary"] = (f"{n_nodes} devices, at most {max_n} per hub, needs at least {hubs(by_nodes)}. {area:g} m², at most "
                          f"{max_a:g} m² per hub, needs at least {hubs(by_area)}. So {bound} is the minimum, and the answer uses {used}.")
    else:
        out["summary"] = (f"The counting bound is {hubs(bound)}, but the doors and passages allow no legal split into "
                          f"{bound}, so {used} are needed.")
    out["fewest_splits"] = hubs_found
    return out


def explain(plan_raw: dict, nodes: list[dict], answer: dict, time_budget_s: float | None = None) -> dict:
    t0 = time.perf_counter()
    budget = float(config.TIME_BUDGET_S) if time_budget_s is None else float(time_budget_s)
    deadline = t0 + budget
    with _LOCK:
        ctx = context(plan_raw, nodes)
        cp, router, hctx = ctx.cp, ctx.router, ctx.hub
        rooms = zone_rooms(cp)
        zones = enumerate_zones(cp, rooms)
        used = answer["metrics"]["H"]
        bound = ladder.min_hub_bound(cp, rooms)
        result: dict = {"plan_id": cp.plan_id}

        # ---- groups: every fewest-hub split, priced like the search prices them -------------------------------
        needed = ladder._zones_in_fewest_splits(rooms, zones, bound)
        data = ladder.build_zone_data(cp, router, hctx, needed, deadline=t0 + 0.5 * budget) if needed else []
        found_hubs, splits, notes = ladder.fewest_hub_covers(rooms, data, bound, int(config.MAX_SPLITS) + 1) if data else (0, [], [])
        result["hubs"] = _hubs_layer(cp, rooms, zones, answer, len(splits), notes)
        chosen_key = frozenset(frozenset(h["room_ids"]) for h in answer["hubs"])
        groups: dict = {"options": [], "total": len(splits), "capped": len(splits) > int(config.MAX_SPLITS),
                        "comparable": bool(splits) and found_hubs == used}
        if groups["comparable"]:
            table = ClashTable(cp)
            zone_area = {frozenset(d.zone.room_ids): d.zone.area_m2 for d in data}
            ordered = sorted(splits, key=lambda s: sum(d.cost for d in s))
            pick = ordered[:SPLITS_SHOWN + 2]
            if not any(frozenset(frozenset(d.zone.room_ids) for d in s) == chosen_key for s in pick):
                pick += [s for s in ordered if frozenset(frozenset(d.zone.room_ids) for d in s) == chosen_key][:1]
            priced = []
            for split in pick:
                if time.perf_counter() > deadline and priced:
                    break
                mix = ladder.best_mix(table, split, zone_area, deadline)
                if mix is None:
                    continue
                cands, J = mix
                ring_sum = sum(c.J for c in cands)
                priced.append({"split": split, "cands": cands, "J": J,
                               "chosen": frozenset(frozenset(d.zone.room_ids) for d in split) == chosen_key,
                               "ring_J": round(ring_sum, 3), "clash_J": round(max(0.0, J - ring_sum), 3),
                               "gap_area": ladder._area_gap(cands, zone_area)})
            priced.sort(key=lambda p: (round(p["J"], 6), p["gap_area"]))
            ref = next((p["J"] for p in priced if p["chosen"]), priced[0]["J"] if priced else 0.0)
            for rank, p in enumerate(priced[:SPLITS_SHOWN + (0 if any(q["chosen"] for q in priced[:SPLITS_SHOWN]) else 1)], start=1):
                opt = {"rank": rank, "chosen": p["chosen"], "J_est": round(p["J"], 3), "gap": round(p["J"] - ref, 3),
                       "ring_J": p["ring_J"], "clash_J": p["clash_J"],
                       "zones": [{"room_ids": list(d.zone.room_ids), "node_ids": sorted(
                           (n.id for n in cp.nodes.values() if n.room_id in d.zone.room_ids), key=lambda s: int(s[1:])),
                           "area_m2": round(d.zone.area_m2, 1)} for d in p["split"]]}
                if rank <= SPLITS_WITH_ANSWER or p["chosen"]:
                    rings = pipeline.rings_from_candidates(p["cands"])
                    opt["answer"] = pipeline.build_answer(cp, rings, "exact", 0.0,
                                                          ["explain: alternative grouping (not the chosen answer)"])
                if not p["chosen"]:
                    why = []
                    if p["J"] - ref > 1e-9:
                        d_ring = p["ring_J"] - next((q["ring_J"] for q in priced if q["chosen"]), p["ring_J"])
                        d_clash = p["clash_J"] - next((q["clash_J"] for q in priced if q["chosen"]), p["clash_J"])
                        if d_ring > 0.05:
                            why.append(f"its own cables are {d_ring:.1f} longer or bendier")
                        if d_clash > 0.05:
                            why.append(f"its loops would clash for {d_clash:.1f} extra")
                    else:
                        why.append("it costs the same; the chosen one has the more even areas or came first")
                    opt["why"] = "; ".join(why) if why else "a slightly different mix of loops"
                groups["options"].append(opt)
        result["groups"] = groups

        # ---- routes: loop orders and hub spots, per hub of the answer -----------------------------------------
        per_hub_j = {}
        try:
            per_hub_j = {hid: v.get("J") for hid, v in metrics.score(answer, cp.scale).get("per_hub", {}).items()}
        except Exception:
            pass
        routes = []
        for hub in answer["hubs"]:
            if time.perf_counter() > deadline:
                break
            hub_rooms = tuple(sorted(hub["room_ids"]))
            order = hub["sequence"][1:-1]
            entry = {"hub_id": hub["hub_id"], "room_ids": list(hub_rooms), "node_ids": list(hub["node_ids"]),
                     "order": list(order), "J": per_hub_j.get(hub["hub_id"]), "loops": [], "spots": [], "note": ""}
            if len(order) < 2:
                entry["note"] = "one device: a single out-and-back cable, nothing to compare"
                routes.append(entry)
                continue
            ranked = ranked_loops(hctx, enumerate_loops(cp, router, hub_rooms), topk=40)
            if not ranked:
                entry["note"] = "no alternative loops could be priced"
                routes.append(entry)
                continue
            want = _canon(order)
            cands = [make_candidate(cp, f"{hub['hub_id']}#{k}", rl) for k, rl in enumerate(ranked)]
            idx = next((k for k, rl in enumerate(ranked) if _canon(rl.loop.order) == want), None)
            ref_c = cands[idx] if idx is not None else cands[0]
            seen = set()
            for k, c in enumerate(cands):
                key = _canon(c.ranked.loop.order)
                if key in seen:
                    continue
                seen.add(key)
                entry["loops"].append({"order": list(c.ranked.loop.order), "J": round(c.J, 3),
                                       "gap": round(c.J - ref_c.J, 3), "chosen": k == idx,
                                       "polyline": [[round(p[0], 4), round(p[1], 4)] for p in c.points]})
                if len(entry["loops"]) >= LOOPS_SHOWN + 1:
                    break
            entry["loops"].sort(key=lambda l: (l["gap"], l["order"]))
            entry["loops"] = entry["loops"][:LOOPS_SHOWN]
            if idx is None:
                entry["note"] = "the final answer was fine-tuned by the polish step, so no listed loop is exactly the chosen one"
            hp = ranked[idx if idx is not None else 0]
            pts = heatmap_points(hctx, hp.loop, hp.hub)
            chosen_pt = (round(hp.hub.point[0], 4), round(hp.hub.point[1], 4))
            chosen_extra = 0.0 if hp.hub.on_wire else float(hp.hub.field_extra)
            others = sorted(((e, x, y) for x, y, e in pts if (round(x, 4), round(y, 4)) != chosen_pt))
            entry["spots"].append({"point": list(chosen_pt), "extra": round(chosen_extra, 3), "chosen": True})
            for e, x, y in others[:SPOTS_SHOWN]:
                entry["spots"].append({"point": [round(x, 4), round(y, 4)], "extra": round(e, 3), "chosen": False,
                                       "gap": round(e - chosen_extra, 3)})
            routes.append(entry)
        result["routes"] = routes
        result["runtime_s"] = round(time.perf_counter() - t0, 3)
    return result
