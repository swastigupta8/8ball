# Assumptions we make (solver side, Person A)

The organisers gave no answers to questions 1 to 3 (scoring checker or sample JSON, judging split, time limit and node format), and we are not chasing the layout questions. Wherever the rules or the data are unclear we take the **safe reading** and say so here. Each line names the switch in `config.py` where there is one. Person B should add the checker-side assumptions below this list, and the deck should quote it.

## Rules we read strictly
| # | Assumption | Why | Switch |
|---|---|---|---|
| 1 | At most 5 nodes and 100 m² per hub, both at once. 5 nodes, not 20 | The detailed slides say 5 | `MAX_NODES_PER_HUB`, `MAX_AREA_M2` |
| 2 | Room area is the repaired polygon divided by scale², where scale = sqrt(inner area / stated area) | The README's "metres" is wrong; `net_area` is 0 in 32% of plans | `resplan.scale` |
| 3 | A zone is connected only through doors or open passages between rooms of that same zone. A path through a bathroom, stair or balcony does not connect two rooms | Safe reading; affects 28 of 17,000 plans | `ZONE_VIA_EXCLUDED_ROOMS` |
| 4 | Cable never enters another hub's room | Always feasible, never breaks a rule | `ALLOW_THROUGH_OTHER_ZONES` (off) |
| 5 | Cable may pass through rooms with no node (bathroom, stair, hall) | Confirmed by the organisers earlier | `ALLOW_THROUGH_EXCLUDED` |
| 6 | Cable stays inside the inner boundary, so balconies and the garden are off limits | Rule 5 | free space = inner minus walls and windows |
| 7 | Cable keeps 4 cm from walls and windows | The 1 mm tolerance means touching is a risk | `WALL_CLEARANCE_M` |
| 8 | A ring may retrace its own cable only inside a dead-end room (one door or passage) and that room's door gaps. Everywhere else parallel runs use separate lines 3 cm apart | Slide 5 shows two parallel runs, not a retrace | `RETRACE_ONLY_SINGLE_DOOR` |
| 9 | Touching another cable counts as a crossing (5 each); a cable through another ring's node counts too | Safe reading of slide 7 | `TOUCH_IS_CROSSING`, `PASS_OTHER_NODE_IS_CROSSING` |
| 10 | Lines within 1 mm are the same line, lines further apart are different | Slide 7 | `TOL_M` |
| 11 | Hub: inside an eligible room of its own zone, at least 0.5 m from every wall and room boundary, and at least 0.3 m from its nodes | Rule 6; we never put the hub on a node | `HUB_CLEARANCE_M` |
| 12 | The weights are L + 5X + O + 0.5B as printed | "Starting values" on the slides | `core/metrics.py` |

## Geometry we infer from the data
| # | Assumption | Why |
|---|---|---|
| 13 | Door shapes are always cut out of the walls | 0.48% of plans have a door buried in a wall |
| 14 | An open passage is a wall-free stretch of shared room boundary at least 0.6 m long that is not a door or window | The stored graph is unreliable |
| 15 | The front door is not a link between rooms | Cable must stay inside |
| 16 | Each polygon part of at least 0.5 m² of an eligible type is its own room with its own node; smaller parts are dropped and logged | "Each polygon is one room" |
| 17 | Where two room polygons overlap, the cell belongs to every room that contains it, so cable there needs all of them to be allowed | The overlap cannot be resolved from the data |
| 18 | Jagged room outlines are simplified inward only, never outward | Never put cable outside a wall |

## Practice inputs (until the organisers' format is known)
| # | Assumption |
|---|---|
| 19 | Nodes are generated in two modes: `center` (deepest point, 0.5 m from walls) and `random` (seeded). Every benchmark uses both |
| 20 | The time budget per plan is 30 s (`TIME_BUDGET_S`). If it runs out, the best answer so far is returned, and greedy is always computed first |

## Plans we do not solve (decision of 2026-10-16: ignore)
About 8% of plans have no legal split under the strict reading above (a room cut out of another room's polygon, a room with no door, a node inside a wall, a room above 100 m²). We do **not** invent an assumption to rescue them. The solver returns the greedy answer with the reason in `meta.warnings`, and the checker marks it invalid. If we ever add an assumption to solve them, it must be a realistic one and listed here first.

# Assumptions we make (checker side, Person B)

The checker (`evaluate/`) is written separately from the solver. It shares only the room IDs
(`io/resplan.room_parts`) and the config switches, and builds its own walls, door links, passages and
metrics. Where the solver list above already states a rule (1-12), the checker enforces the same reading
and isn't repeated here. These lines are how the checker reads the geometry and the rules, and how the
benchmark gates are scored. The checker leans strict: if in doubt, it reports a violation.

## How the checker reads the plan
| # | Assumption | Why | Where |
|---|---|---|---|
| C1 | Land, garden, pool and parking are outdoors, not rooms: they never link rooms, never count as passages, and never make cable "inside a room" | The land polygon covers the whole plot; counted as a room, it linked everything to everything | `geom_indep.OUTDOOR` |
| C2 | A door joins the two rooms found just beyond its two faces: three probes 15 cm past each face of the door's thin side, majority room per side. Doors that aren't thin rectangles fall back to the two rooms with the most contact | Contact length picked the wrong pair where two rooms sit side by side behind one face (plans 425, 1140) | `geom_indep._door_rooms_by_probe` |
| C3 | A door part that lies mostly (> 50%) inside the front-door shape is the front door and links nothing | Rule: the entrance doesn't count | `geom_indep.build` |
| C4 | An open passage is found independently of the solver: grow both rooms by 0.6 x wall depth, keep their overlap inside the inner boundary minus walls, doors and windows (+1 cm); a piece at least 0.6 m long is a passage | Two methods (ours and the solver's) cross-check each other; "unsure gap = wall" | `geom_indep.build`, `PASSAGE_MIN_WIDTH_M` |
| C5 | A room is single-door only if it has exactly one opening: each door and each passage counts, so a room with a door **and** a passage to the same neighbour has two | Strict reading of "single-door room"; this is plan 719 (open question 16) | `CheckGeom.degree` |

## How the checker reads the rules
| # | Assumption | Why | Where |
|---|---|---|---|
| C6 | Overlap inside one ring is a retrace, legal only when the two legs are consecutive, the stop between them is in a single-door room (C5), and the shared stretch lies inside that room and its door or passage gap. Overlap is measured as shared length on the same line (1 mm grid); legs that only cross or touch share nothing | Rule 4 and solver assumption 8; a perpendicular crossing is an X, not an overlap (fixed 2026-10-16) | `checker.collinear_pieces`, `_check_retrace` |
| C7 | Free space: every segment inside the inner boundary (+1 mm), axis-aligned, at least 2 cm (half of `WALL_CLEARANCE_M`) from walls and windows. The solver keeps 4 cm; the checker allows half so rounding never fails a good answer, while touching a wall still does | Rule 5 with the 1 mm tolerance | `_check_free_space` |
| C8 | Any part of a segment outside every room polygon must lie in a door or passage gap; stray pieces up to 5 cm (drawing slivers between room and wall) are ignored | Rule 5: between rooms only through doors and passages | `_check_free_space` |
| C9 | With `ALLOW_THROUGH_OTHER_ZONES` off, a segment may not run more than 1 mm inside an eligible room outside its zone, including rooms no hub serves | Solver assumption 4 | `_check_free_space` |
| C10 | Hub: inside (or on the edge of) an eligible room of its zone, at least 0.5 m - 1 mm from that room's outline and from every wall, and `hub.room_id` must name that room. The checker does **not** require the solver's extra 0.3 m from nodes (not a rule) | Rule 6 | `_check_hub` |
| C11 | Coverage: the answer's nodes must equal the official nodes (same IDs and rooms, points within 1 mm); every eligible room in exactly one hub; each hub's `node_ids` are exactly its rooms' nodes | Rule 1; nodes are fixed inputs | `_check_nodes`, `_check_coverage` |
| C12 | Capacity area = repaired polygons / scale², limit 100 m² + 1e-9 | Solver assumption 2, same numbers | `_check_capacity` |

## How the metrics are counted (both implementations, `tests/metric_cases.py`)
| # | Assumption | Why |
|---|---|---|
| C13 | Coordinates snap to a 1 mm grid in metres. 0.2-0.4 mm apart is the same point or line, 1.5 mm apart is different; 0.5-1 mm is a grey zone we never test | Slide 7 tolerance; metric clarification 3 |
| C14 | Straight-through vertices are dropped except at nodes and the hub; a 180-degree reversal is one bend | Slide 7 |
| C15 | The end of a shared run is not a crossing unless a ring outside that run also meets there | Metric clarification 1 |
| C16 | A meeting point is excluded from X only if every ring meeting there has its own node or hub at that point (touching another ring's node counts) | Metric clarification 2, solver assumption 9 |

## How the benchmark gates are scored (`bench/run_all.py`)
| # | Assumption | Why |
|---|---|---|
| C17 | Solver metrics and checker metrics must agree: lengths within 1 mm, counts exactly. Any difference is a bug in one of the two | Two independent implementations |
| C18 | An invalid answer whose solver notes say "no split covers every room" / "no split into N zone(s)", or whose flags say the node is off the floor, is **blocked** (open questions 13-15): listed, but left out of the gates. `--strict-blocked` counts them | Decision of 2026-10-16: ignore these plans, no rescuing assumption |
| C19 | M2 and M3 require the exact solver's answers to be valid; greedy is only the yardstick (its metric mismatches still count). J is compared with greedy only at equal hub count | Ranking is hubs first, then J |
| C20 | CP-SAT must match the exact search's additive optimum where that search finished; where the time budget cut it (backup solver picked the split) or it retried with more hubs, CP-SAT may only be cheaper | CP-SAT prices every zone; a time-cut search doesn't |
