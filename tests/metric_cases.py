"""Metric test cases (handoff 9). Pure data, scale = 1 (coordinates are metres).

Both metric implementations (core/metrics.py, Person A; evaluate/metrics_indep.py, Person B) must pass
every case. Values come from the slides where they exist (slide 7); the rest are hand-computed.

AGREED BY: Swasti (Person B) wrote these in Phase 0. Prasoon (Person A) must re-derive every expected
value and sign off below before contracts-v1 is final; a third teammate reviews (handoff 13).
  Prasoon sign-off: [ ]    Third reviewer: [ ]

Conventions the cases pin down (handoff 8.1 plus three clarifications, recorded in docs/DECISIONS.md):
  * A ring is the concatenation of its legs, closed at the hub. After snapping to a 1 mm grid, drop
    zero-length segments and straight-through middle vertices, but keep node and hub vertices and
    keep reversal vertices (a 180-degree turn is a bend, not a straight-through).
  * B: every 90-degree turn or 180-degree reversal along the closed ring is 1 bend, including at nodes
    and at the hub where the closing leg meets the first.
  * O: per axis line, a stretch covered by k segments (from any ring, the same ring included) adds
    (k - 1) x its length.
  * X: points where segments meet, excluding consecutive segments of one ring at their shared vertex.
      - An endpoint of a collinear overlap is NOT a crossing unless a segment from a ring that takes
        no part in that overlap also meets there.  (clarification 1)
      - With PASS_OTHER_NODE_IS_CROSSING (strict, default), a point is excluded only if EVERY ring
        meeting there has its own node or hub at that point; touching another ring's node counts.  (clarification 2)
      - T-touches count (TOUCH_IS_CROSSING). Points within 1 mm are one point; each counts once.
  * Tolerance tests use 0.2-0.4 mm (same) and 1.5 mm (different): both implementations snap to a
    1 mm grid, so separations between 0.5 and 1 mm are a grey zone we never test.  (clarification 3)
"""
from __future__ import annotations

# A ring: hub id, hub point, the visiting order (node ids), and one polyline per leg
# (hub -> first node, ..., last node -> hub). Node points live in "nodes".

CASES = [
    {
        "id": "01_slide7_rectangle",
        "desc": "Slide 7 loop 4+2+3+3 = 12 m; straight through N3",
        "nodes": {"N1": [4, 0], "N2": [4, 2], "N3": [1, 2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2", "N3"],
             "legs": [[[0, 0], [4, 0]], [[4, 0], [4, 2]], [[4, 2], [1, 2]], [[1, 2], [0, 2], [0, 0]]]},
        ],
        "expect": {"L": 12.0, "X": 0, "O": 0.0, "B": 4},
    },
    {
        "id": "02_slide7_retrace",
        "desc": "Out-and-back 3 m: overlap 3, reversals at N and at H",
        "nodes": {"N1": [3, 0]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1"],
             "legs": [[[0, 0], [3, 0]], [[3, 0], [0, 0]]]},
        ],
        "expect": {"L": 6.0, "X": 0, "O": 3.0, "B": 2},
    },
    {
        "id": "03_slide7_plus_crossing",
        "desc": "Two out-and-back rings crossing in a '+' at (2,0), away from nodes: one point",
        "nodes": {"N1": [4, 0], "N2": [2, 2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1"], "legs": [[[0, 0], [4, 0]], [[4, 0], [0, 0]]]},
            {"hub": "H2", "point": [2, -2], "order": ["N2"], "legs": [[[2, -2], [2, 2]], [[2, 2], [2, -2]]]},
        ],
        "expect": {"L": 16.0, "X": 1, "O": 8.0, "B": 4},
    },
    {
        "id": "04_slide7_meet_at_node",
        "desc": "Legs meeting at a node in an L-shape are not a crossing",
        "nodes": {"N1": [3, 0], "N2": [3, 2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2"],
             "legs": [[[0, 0], [3, 0]], [[3, 0], [3, 2]], [[3, 2], [0, 2], [0, 0]]]},
        ],
        "expect": {"L": 10.0, "X": 0, "O": 0.0, "B": 4},
    },
    {
        "id": "05_slide7_shared_2m",
        "desc": "Two rings share 2 m of y=0; the overlap ends are not crossings (clarification 1)",
        "nodes": {"N1": [4, 0], "N2": [4, 2], "N3": [3, -2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2"],
             "legs": [[[0, 0], [4, 0]], [[4, 0], [4, 2]], [[4, 2], [0, 2], [0, 0]]]},
            {"hub": "H2", "point": [1, -2], "order": ["N3"],
             "legs": [[[1, -2], [3, -2]], [[3, -2], [3, 0], [1, 0], [1, -2]]]},
        ],
        "expect": {"L": 20.0, "X": 0, "O": 2.0, "B": 8},
    },
    {
        "id": "06_slide7_parallel_3cm",
        "desc": "Same layout with ring 2's top run 3 cm below y=0: distinct lines, no overlap",
        "nodes": {"N1": [4, 0], "N2": [4, 2], "N3": [3, -2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2"],
             "legs": [[[0, 0], [4, 0]], [[4, 0], [4, 2]], [[4, 2], [0, 2], [0, 0]]]},
            {"hub": "H2", "point": [1, -2], "order": ["N3"],
             "legs": [[[1, -2], [3, -2]], [[3, -2], [3, -0.03], [1, -0.03], [1, -2]]]},
        ],
        "expect": {"L": 19.94, "X": 0, "O": 0.0, "B": 8},
    },
    {
        "id": "07a_slide7_z_shape",
        "desc": "Z-shaped leg (2 turns) out and back: 2 + 2 turns + 2 reversals; full retrace overlap",
        "nodes": {"N1": [4, 2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1"],
             "legs": [[[0, 0], [2, 0], [2, 2], [4, 2]], [[4, 2], [2, 2], [2, 0], [0, 0]]]},
        ],
        "expect": {"L": 12.0, "X": 0, "O": 6.0, "B": 6},
    },
    {
        "id": "07b_slide7_straight_through_node",
        "desc": "Straight through N1 costs no bend",
        "nodes": {"N1": [2, 0], "N2": [4, 0], "N3": [4, 2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2", "N3"],
             "legs": [[[0, 0], [2, 0]], [[2, 0], [4, 0]], [[4, 0], [4, 2]], [[4, 2], [0, 2], [0, 0]]]},
        ],
        "expect": {"L": 12.0, "X": 0, "O": 0.0, "B": 4},
    },
    {
        "id": "08_t_touch",
        "desc": "Ring 2's spur reverses exactly on ring 1's bottom edge at (2,0): a T-touch (strict) = 1",
        "nodes": {"N1": [4, 0], "N2": [4, 2], "N3": [2, -2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2"],
             "legs": [[[0, 0], [4, 0]], [[4, 0], [4, 2]], [[4, 2], [0, 2], [0, 0]]]},
            {"hub": "H2", "point": [4, -2], "order": ["N3"],
             "legs": [[[4, -2], [2, -2]], [[2, -2], [2, 0], [2, -2], [4, -2]]]},
        ],
        "expect": {"L": 20.0, "X": 1, "O": 4.0, "B": 8},
    },
    {
        "id": "09_three_legs_one_stretch",
        "desc": "[1,2] on y=0 covered by 3 segments (+2), the rest of ring 1's retrace by 2 (+3)",
        "nodes": {"N1": [3, 0], "N2": [2, -2]},
        "rings": [
            {"hub": "H1", "point": [-1, 0], "order": ["N1"], "legs": [[[-1, 0], [3, 0]], [[3, 0], [-1, 0]]]},
            {"hub": "H2", "point": [1, -2], "order": ["N2"],
             "legs": [[[1, -2], [2, -2]], [[2, -2], [2, 0], [1, 0], [1, -2]]]},
        ],
        "expect": {"L": 14.0, "X": 0, "O": 5.0, "B": 6},
    },
    {
        "id": "10_collinear_and_duplicate",
        "desc": "Case 01's rectangle with a collinear middle vertex and a duplicate point: no extra bend",
        "nodes": {"N1": [4, 0], "N2": [4, 2], "N3": [1, 2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2", "N3"],
             "legs": [[[0, 0], [2, 0], [2, 0], [4, 0]], [[4, 0], [4, 2]], [[4, 2], [1, 2]],
                      [[1, 2], [0, 2], [0, 0]]]},
        ],
        "expect": {"L": 12.0, "X": 0, "O": 0.0, "B": 4},
    },
    {
        "id": "11a_tol_point_0p2mm",
        "desc": "Leg ends 0.2 mm past N1: the same point after snapping",
        "nodes": {"N1": [4, 0], "N2": [4, 2], "N3": [1, 2]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2", "N3"],
             "legs": [[[0, 0], [4.0002, 0]], [[4, 0], [4, 2]], [[4, 2], [1, 2]], [[1, 2], [0, 2], [0, 0]]]},
        ],
        "expect": {"L": 12.0, "X": 0, "O": 0.0, "B": 4},
    },
    {
        "id": "11b_tol_line_0p4mm",
        "desc": "Return run 0.4 mm off the outbound line: the same line, so a full retrace",
        "nodes": {"N1": [3, 0]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1"],
             "legs": [[[0, 0], [3, 0]], [[3, 0], [3, 0.0004], [0, 0.0004], [0, 0]]]},
        ],
        "expect": {"L": 6.0, "X": 0, "O": 3.0, "B": 2},
    },
    {
        "id": "11c_tol_line_1p5mm",
        "desc": "Return run 1.5 mm off the outbound line: a different line, no overlap, 4 bends",
        "nodes": {"N1": [3, 0]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1"],
             "legs": [[[0, 0], [3, 0]], [[3, 0], [3, 0.0015], [0, 0.0015], [0, 0]]]},
        ],
        "expect": {"L": 6.003, "X": 0, "O": 0.0, "B": 4},
    },
    {
        "id": "12_through_other_node",
        "desc": "Ring 1's bottom edge passes through ring 2's node at (2,0): X = 1 (clarification 2)",
        "nodes": {"N1": [4, 0], "N2": [4, 2], "N3": [2, 0]},
        "rings": [
            {"hub": "H1", "point": [0, 0], "order": ["N1", "N2"],
             "legs": [[[0, 0], [4, 0]], [[4, 0], [4, 2]], [[4, 2], [0, 2], [0, 0]]]},
            {"hub": "H2", "point": [2, -2], "order": ["N3"], "legs": [[[2, -2], [2, 0]], [[2, 0], [2, -2]]]},
        ],
        "expect": {"L": 16.0, "X": 1, "O": 2.0, "B": 6},
    },
]

L_TOL = 0.002  # metres; lengths compare within 2 mm (snapping moves points by up to 0.5 mm)
O_TOL = 0.002


def to_answer(case: dict) -> dict:
    """Wrap a case as an answer-shaped dict (scale 1) for score(answer, scale)."""
    nodes = [{"node_id": nid, "room_id": f"room_{nid}", "point": list(map(float, pt))}
             for nid, pt in case["nodes"].items()]
    hubs = []
    for ring in case["rings"]:
        seq = [ring["hub"], *ring["order"], ring["hub"]]
        legs = [{"from": seq[k], "to": seq[k + 1], "polyline": [list(map(float, p)) for p in poly]}
                for k, poly in enumerate(ring["legs"])]
        hubs.append({"hub_id": ring["hub"], "point": list(map(float, ring["point"])),
                     "room_id": f"room_{ring['hub']}", "room_ids": [f"room_{n}" for n in ring["order"]],
                     "node_ids": list(ring["order"]), "sequence": seq, "legs": legs,
                     "area_m2": 0.0, "length_m": 0.0})
    return {"schema_version": "8ball-answer/1", "plan_id": 0, "scale": 1.0, "nodes": nodes, "hubs": hubs,
            "metrics": {}, "meta": {"solver": "metric_case"}}


def check_result(result: dict, case: dict) -> list[str]:
    exp = case["expect"]
    problems = []
    if abs(result["L"] - exp["L"]) > L_TOL:
        problems.append(f"L {result['L']} != {exp['L']}")
    if abs(result["O"] - exp["O"]) > O_TOL:
        problems.append(f"O {result['O']} != {exp['O']}")
    for key in ("X", "B"):
        if result[key] != exp[key]:
            problems.append(f"{key} {result[key]} != {exp[key]}")
    j = exp["L"] + 5 * exp["X"] + exp["O"] + 0.5 * exp["B"]
    if abs(result["J"] - j) > L_TOL + O_TOL:
        problems.append(f"J {result['J']} != {j}")
    return problems
