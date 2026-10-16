# V2 features: specs for Person A

Four features chosen by the team on 2026-10-17. Person A builds them. Each section covers what the demo should show,
the rules, where the code goes, the interfaces, the tests, and what "done" means.

**Ground rules for all four**
- The default `/api/solve` answer must not change: the I2/I3 numbers and tags stay valid. New features only *add*
  response keys, endpoints and UI.
- The checker (`evaluate/`) stays independent: it must not import anything new from `optimize/`. These features don't
  change any rule, so the checker needs no edit.
- Most UI work lands in B's files (`web/app.js`, `web/viewer.html`, `web/style.css`, `api/server.py`). That's fine;
  post an inbox heads-up row per push, as before.
- The 3D view (`web/view3d.js`) already redraws from the same `state` through `drawAll()`. Anything drawn in 2D
  should also appear in 3D where it makes sense (isolators, shorts, a moved hub).
- Suggested build order: **1 → 3 → 2 → 4**. Drag-the-hub reuses heatmap data we already ship, while the trade-off
  view needs a small CP-SAT change.

---

## 1. Short circuits and loop isolators

**Why:** closed loops are how addressable fire-alarm systems are wired (Class A loops). Break the cable already shows
that a loop survives an *open* circuit. Real loops also fail by *short circuit*, which takes the whole loop down unless
**short-circuit isolators** split it into segments. (EN 54 limits how many devices a single loop fault may take out.)
This is the feature that speaks the judges' language.

**Demo moment:** turn on Short circuit, click a cable, and the whole ring goes red ("5 of 5 devices lost"). Set
"max devices lost per short" to 1 and press Place isolators: small isolator markers appear on the ring. Click the same
spot again and now only 1 device is lost.

**Model** (one ring per hub; the hub/panel end counts as isolated on both sides, as on a real panel)
- The ring visits devices `d1 … dn` in `hub.sequence` order. An isolator sits on a leg between two consecutive stops
  (put the marker at the middle of that leg's polyline).
- The isolators cut the ring into **segments**. A short anywhere on the cable of a segment disables every device in it.
  With no isolators, the segment is the whole ring: all `n` lost.
- **Placement for "at most k devices lost per short":** walk the devices in ring order and put an isolator after every
  k-th device, giving `ceil(n / k) − 1` per ring. This is provably the minimum for one ring, because each segment can
  hold at most k devices.
- Total isolators = the sum over hubs. Show the table k → isolators (k = 1…5) so the user sees the trade-off.
- **Stretch (pairs well):** "room fault". A fire or water leak in a room shorts *every* cable passing through it. If one
  room carries two different segments of the same ring, a single room fault takes out both. Flag such rooms in red.
  This is the honest limit of the "loops survive" claim, and showing it is a strength.

**Where the code goes**
- Python reference (testable, goes into downloads): new `src/eightball/optimize/isolators.py`
  - `place_isolators(answer: dict, max_lost: int) -> list[dict]` → `[{"hub_id", "leg_index", "point"}]`
  - `short_effect(answer: dict, isolators: list[dict], hub_id: str, leg_index: int) -> list[str]` → node ids lost
- API: `/api/solve` adds a key `isolators: {"1": [...], "2": [...], ..., "5": [...]}` (cheap; no new endpoint).
  Uploaded plans get it too.
- Viewer (`web/app.js`): the Break the cable section gets a mode switch **Cut | Short**. Reuse `ringModel()`
  (it already has stops with positions along the ring) and `nearestRingSeg()`; a short at position `c` loses the
  stops between the isolators on either side of `c`. Add a stepper "Max devices lost per short: k" and a
  **Place isolators** toggle. Show a results box like the existing lost-boxes: "Without isolators: 5 lost · With 2
  isolators: at most 1 lost". Draw isolators as small diamonds on the cable, and the short as a ⚡ marker.
- Branching comparison: a short on the branching layout kills everything downstream, same as a cut. Keep the
  split view.
- Full report download (`dl-all`): include the isolators for the k currently selected.

**Tests:** `tests/test_isolators.py`: a 5-device ring with k = 2 gives 2 isolators and a worst short of ≤ 2 lost;
k = 5 gives 0 isolators; with no isolators a short loses all; a short on the hub's own legs loses only that segment.

**Done when:** on a gallery plan, short with no isolators → all devices on that ring lost; Place isolators (k = 1) →
any short loses ≤ 1; it works in 2D and 3D, and the counts match the Python function.

---

## 2. Choose your trade-off (hubs vs cost)

**Why:** we return one answer: fewest hubs, then cheapest J. A real client asks "what if I pay for one more hub?"
Showing the whole trade-off curve shows we understand that "optimal" depends on the buyer.

**Demo moment:** after a solve, a row of buttons "2 hubs · J 48.0 | 3 hubs · J 41.2 | 4 hubs · J 39.9" with a small
J-vs-hubs chart. Click one and the plan redraws with that layout. A note says "One more hub saves 6.8 J (14%)" or
"No saving from more hubs".

**Model**
- For each hub count `H` from `min_hubs_bound` up to `min(eligible rooms, min_hubs + 3)`: pick zones that cover every
  room with **exactly H** hubs at the lowest additive cost, then build the full answer and its true metrics (`J` counts
  crossings between rings, which the additive cost doesn't).
- Price the zones only once (`pipeline.zone_candidates`, which is the expensive part); each `H` is then a quick selection.
- An `H` with no legal split is skipped. More hubs is not always cheaper: show it anyway.

**Where the code goes**
- `optimize/cpsat.py`: `CpSatZoneSolver.select(..., hubs: int | None = None)`. When set, add `sum(x) == hubs` and skip
  solve 1. Leave the default behaviour untouched.
- `optimize/pipeline.py`: `tradeoff(plan_raw, nodes) -> list[dict]`, each item `{hubs, J, L, X, O, B, answer}`. Build
  each answer with `rings_from_candidates(...)` + `build_answer(...)`, as `solve` does.
- API: `POST /api/tradeoff {plan_id | plan, nodes?}` → `{"options": [...], "default_hubs": H}`. Run the checker on each
  option and return `check` too, so the UI shows Valid on every option. Cache the zone candidates per plan in memory
  (a small LRU) so a tradeoff call right after a solve is fast. Respect the same timeout as `/api/solve`.
- Viewer: a new panel section **Trade-off** directly under Score. Use segmented buttons, not a dropdown (the user
  removed dropdowns on purpose), plus a mini chart. Clicking an option calls `useResult(plan, {answer, check, ...})`.
  Heatmaps and branching for non-default options can be omitted at first: hide those sections when they're missing.

**Tests:** `select(hubs=H)` returns exactly H zones covering every room; `tradeoff` on fixture 900002 returns
`H = 2` first and that answer equals the default solve; every option passes the checker.

**Done when:** on 3 gallery plans the options appear within the time budget, each option is valid, and the default
option equals the normal solve.

---

## 3. Drag the hub, live

**Why:** the heatmap says "the chosen hub is the cheapest spot". Dragging lets the judge *feel* it: move the hub and
J goes up; let go and it can snap back.

**Demo moment:** grab H1, drag it around its zone, and a live label follows: "J 48.04 → 50.31 (+2.27)". The ghost hub
snaps only to legal spots. Drop it and the ring re-routes to the new spot; buttons **Snap to best** and **Reset**
appear.

**Model**
- Legal hub spots are exactly the heatmap lattice points of that hub's zone (`hub.heatmap_points` already gives
  `(x, y, extra J)` for the zone's chosen loop; confirm it only includes legal hub spots). Snapping to them should keep
  every moved answer valid (inside the zone, ≥ 0.5 m from walls); the checker confirms after the drop.
- Live value during the drag: client-side, from the heatmap points (no server call): `J_new = J + extra(point)`.
- On drop: the server rewires the hub at that point on the **same loop** with the same insertion logic that computed
  the heatmap value, so the final J matches the live label.

**Where the code goes**
- `optimize/hub.py` / `pipeline.py`: `move_hub(plan_raw, nodes, answer, hub_id, point) -> answer`. Rebuild the
  `HubContext` for the plan, wire the hub at `point` on that zone's loop, and rebuild the answer with `build_answer`.
- API: `POST /api/move_hub {plan_id | plan, nodes?, answer, hub_id, point}` → `{answer, check}`. Reject a point that
  isn't a heatmap lattice point of that zone (422).
- Viewer (`web/app.js`): pointer events on the hub rects. Disable map panning while dragging a hub, snap to the
  nearest heatmap point of that hub, draw a ghost hub plus the live label, and turn the heatmap on automatically
  while dragging. Keep the original answer in `state` for **Reset**; **Snap to best** goes back to the heatmap minimum.
- 3D: after the drop, the normal `drawAll()` refresh is enough.

**Tests:** `move_hub` to the heatmap minimum returns the original J (within 1e-6); moving to another lattice point
gives `J = original + extra` (within 1 mm of cable) and the checker says valid; a non-lattice point → 422.

**Done when:** dragging on a 2-hub gallery plan shows the live J, dropping gives a valid answer whose J equals the
live label, and Reset/Snap to best work.

---

## 4. Beat the Solver: game (optional, only if time allows)

**Why:** every judge plays instead of watching, and nobody beats the solver. That's the proof.

**Demo moment:** "Can you wire this flat better than 8ball?" The player clicks to place a hub and draws the loop
leg by leg (clicks snap to a 0.1 m grid; each segment is forced horizontal or vertical). Submit → the checker scores it
→ reveal: "You: J 61.2 · 8ball: J 48.0", with both layouts side by side and a leaderboard.

**Where the code goes**
- No new solver code. The backend already exists: `POST /api/validate {plan_id | plan, nodes, answer}`.
- New page `web/challenge.html` + `challenge.js`, or a Challenge mode in the viewer. It builds a valid answer JSON
  in the browser (schema `core/schema/answer.schema.json`): `hub.room_id` by point-in-polygon, `room_ids` = rooms
  of the visited devices, `area_m2` from the room polygons, `sequence` and `legs` from the clicks.
- Start with 1-hub gallery plans (`data/gallery`, the ones with `H == 1`), so the player draws a single loop.
- Show checker violations in plain words if the drawing breaks a rule ("cable passes through a wall").
- Leaderboard: `localStorage` on the stall laptop is enough.

**Done when:** a hand-drawn valid loop scores the same J that `/api/validate` returns, an invalid one shows why, and the
solver's answer is revealed next to it.

---

## Where each feature sits in the current product

| Feature | Backend | API | Viewer |
|---|---|---|---|
| 1 Isolators | new `optimize/isolators.py` | `isolators` key in `/api/solve` | Break the cable section: Cut / Short switch, k stepper, isolator markers (2D + 3D) |
| 2 Trade-off | `cpsat.select(hubs=)`, `pipeline.tradeoff` | new `POST /api/tradeoff` | new Trade-off section under Score |
| 3 Drag the hub | `move_hub` using `hub.py` insertion | new `POST /api/move_hub` | drag on hub icons, live J label, uses the existing heatmap |
| 4 Game | none | existing `POST /api/validate` | new Challenge page or mode |
