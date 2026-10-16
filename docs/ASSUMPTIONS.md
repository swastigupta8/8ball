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
