# Open questions for the organisers

Most important first. When one is answered, record the answer here, change the matching switch in `config.py` through a contract PR, and add a row to `DECISIONS.md`.

| # | Question | Switch / impact | Answer |
|---|---|---|---|
| 1 | Can we get the scoring checker, or at least a sample output JSON with its schema? | `io/answer_io.to_organiser_format` adapter | |
| 2 | What's the judging split between the hidden-plan score and the demo/presentation? | Effort split | |
| 3 | Time limit per plan in the live run, and the input format? Are node points supplied, and in what format? | `TIME_BUDGET_S`, `io/nodes.read_organiser_nodes` | |
| 4 | Can a loop pass through a room assigned to a different hub? | `ALLOW_THROUGH_OTHER_ZONES` (False) | |
| 5 | Is retracing allowed anywhere other than into a single-door room? | `RETRACE_ONLY_SINGLE_DOOR` (True) | |
| 6 | How is room area computed for the 100 m² limit (raw polygon, repaired, which scale)? | `resplan.room_parts` | |
| 7 | Does a T-touch count as a crossing? Does passing through another loop's node? Does a cable on a wall's edge count as touching the wall? Are the ends of a shared run crossings? | `TOUCH_IS_CROSSING`, `PASS_OTHER_NODE_IS_CROSSING`, `WALL_CLEARANCE_M`, metric clarification 1 | |
| 8 | Are collinear middle vertices or duplicate points allowed in polylines, and how do they affect bend counting? | Polyline cleaning | |
| 9 | Is a zone contiguous if two noded rooms connect only through a bathroom or stair? (28 plans) | `ZONE_VIA_EXCLUDED_ROOMS` (False) | |
| 10 | How does the checker detect open passages? Is a return leg a few cm away a distinct line? | `PASSAGE_MIN_WIDTH_M`, `LANE_SPACING_M` | |
| 11 | Is a multi-polygon living room one room or several? (256 plans) What happens with non-axis-aligned walls? (1.6% of plans) | `MIN_ROOM_PART_M2`, room_parts | |
| 12 | Confirm 5 nodes per hub, not 20. Is pre-written code allowed before the event? | `MAX_NODES_PER_HUB` | |
| 13 | A room whose polygon is cut out of another room's polygon (e.g. a storage alcove inside the living room, no door, open on one side), or a room with no door or passage at all: is it a legal zone partner of the room around it, and may cable run through the shared area? Under the strict reading no split covers it. Seen on about 8% of plans in a 300-plan trial (plans 47, 70, 144, 188 ...). | A switch that links overlapping rooms as open space (not built) | |
| 14 | A single eligible room above 100 m² (organisers say these plans are excluded): confirm they never appear in the hidden set. About 2% of plans in the trial (plans 74, 146, 147, 151 ...). | none: no valid answer exists | |
| 15 | A node point that lies inside a wall or window (random practice nodes do this in about 1 of 200 plans): does the organisers' node placement guarantee 0.5 m of clear floor? | node clearance check, flag node_not_in_free_space | |
