// 8ball "Beat the Solver" (V2 feature 4): the player places a hub and draws a closed cable loop through every device of
// a one-hub flat; the checker (POST api/validate) scores it, and the solver's own layout is revealed next to it.
// No solver code: the answer is built in the browser in the schema of core/schema/answer.schema.json.
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
const $ = (id) => document.getElementById(id);
const el = (tag, attrs = {}, parent = null) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
};
const html = (tag, attrs = {}, text = null) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== null) n.textContent = text;
  return n;
};

const YOU = "#7fd6ff", SOLVER = "#f2b680";  // house palette (style.css theme)
const SNAP_M = 0.1;          // clicks snap to this grid (metres)
const PICK_M = 0.4;          // clicking within this of a device (or the hub, to close) connects to it
const BOARD_KEY = "8ball-challenge-v1", NAME_KEY = "8ball-challenge-name";

const S = {
  api: false, entries: [], entry: null, plan: null, solver: null,
  actions: [], flip: false, cursor: null, view: null, base: null, result: null, busy: false,
};

const svgMain = $("canvas"), svgSolver = $("canvas-solver");
const maps = [svgMain, svgSolver];
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const ringsPath = (rings) => rings.map((r) => "M" + r.map((p) => `${p[0]},${-p[1]}`).join("L") + "Z").join("");
const polyPath = (pts) => "M" + pts.map((p) => `${p[0]},${-p[1]}`).join("L");

// ---------- plan geometry ----------
const scale = () => S.plan.scale;
const nodes = () => S.plan.nodes;
const nodePoint = (id) => nodes().find((n) => n.node_id === id).point;
const snap = (v) => Math.round(v / (SNAP_M * scale())) * (SNAP_M * scale());

function inRing(p, ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
const roomAt = (p) => S.plan.rooms.find((r) => inRing(p, r.polygon[0]) && !r.polygon.slice(1).some((h) => inRing(p, h)));

// ---------- the player's drawing, rebuilt from a list of clicks (so Undo is just removing the last click) ----------
// actions: {t:"hub", p} | {t:"v", p} a corner | {t:"node", id, flip} | {t:"close", flip}
function connect(from, target, flip) {
  const tol = 1e-6 * scale();
  if (Math.abs(from[0] - target[0]) < tol || Math.abs(from[1] - target[1]) < tol) return [target];
  return [flip ? [from[0], target[1]] : [target[0], from[1]], target];
}

function derive() {
  const d = { hub: null, legs: [], cur: [], stops: [], done: false };
  for (const a of S.actions) {
    if (a.t === "hub") { d.hub = a.p; d.cur = [a.p]; }
    else if (a.t === "v") d.cur.push(a.p);
    else {
      const target = a.t === "node" ? nodePoint(a.id) : d.hub;
      d.cur.push(...connect(d.cur[d.cur.length - 1], target, a.flip));
      d.legs.push({ from: d.stops.length ? d.stops[d.stops.length - 1] : "H1", to: a.t === "node" ? a.id : "H1", poly: d.cur });
      if (a.t === "node") { d.stops.push(a.id); d.cur = [target]; } else { d.done = true; d.cur = []; }
    }
  }
  return d;
}

function dedupe(poly) {
  const out = [poly[0]];
  for (const p of poly.slice(1)) if (dist(p, out[out.length - 1]) > 1e-9) out.push(p);
  return out;
}

function stats(d) {
  const pts = [];
  for (const l of d.legs) pts.push(...dedupe(l.poly));
  if (d.cur.length) pts.push(...dedupe(d.cur));
  let len = 0, bends = 0, lastDir = null;
  const ring = dedupe(pts);
  for (let i = 1; i < ring.length; i++) {
    const dx = Math.sign(ring[i][0] - ring[i - 1][0]), dy = Math.sign(ring[i][1] - ring[i - 1][1]);
    len += Math.abs(ring[i][0] - ring[i - 1][0]) + Math.abs(ring[i][1] - ring[i - 1][1]);
    if (lastDir && (dx !== lastDir[0] || dy !== lastDir[1])) bends++;
    lastDir = [dx, dy];
  }
  return { L: len / scale(), B: bends };
}

function phaseOf(d) {
  if (!d.hub) return "hub";
  return d.done ? "done" : "draw";
}

function buildAnswer(d) {
  const ids = nodes().map((n) => n.node_id).sort((a, b) => Number(a.slice(1)) - Number(b.slice(1)));
  const roomIds = [...new Set(nodes().map((n) => n.room_id))].sort();
  const room = roomAt(d.hub);
  const area = roomIds.reduce((sum, id) => sum + (S.plan.rooms.find((r) => r.room_id === id)?.area_m2 || 0), 0);
  return {
    schema_version: "8ball-answer/1", plan_id: S.plan.plan_id, scale: S.plan.scale,
    nodes: nodes().map((n) => ({ node_id: n.node_id, room_id: n.room_id, point: n.point })),
    hubs: [{
      hub_id: "H1", point: d.hub, room_id: room ? room.room_id : "none", room_ids: roomIds, node_ids: ids,
      sequence: ["H1", ...d.stops, "H1"],
      legs: d.legs.map((l) => ({ from: l.from, to: l.to, polyline: dedupe(l.poly) })),
      area_m2: area, length_m: stats(d).L,
    }],
    metrics: {}, meta: { solver: "human" },
  };
}

// ---------- drawing ----------
function drawBase(svg, plan) {
  svg.replaceChildren();
  const g = {};
  for (const name of ["zones", "walls", "labels", "cable", "nodes", "overlay"]) g[name] = el("g", {}, svg);
  for (const rings of plan.inner) el("path", { d: ringsPath(rings), fill: "var(--surface)", "fill-rule": "evenodd" }, g.zones);
  for (const room of plan.rooms) {
    el("path", { d: ringsPath(room.polygon), class: "room " + (room.eligible ? "free" : "excluded"), "fill-rule": "evenodd" }, g.zones);
    const t = el("text", { x: room.label_point[0], y: -room.label_point[1] + 0.55 * plan.scale, class: "room-label", "font-size": 0.26 * plan.scale }, g.labels);
    t.textContent = room.type;
  }
  for (const rings of plan.walls) el("path", { d: ringsPath(rings), class: "wall", "fill-rule": "evenodd" }, g.walls);
  for (const rings of plan.windows) el("path", { d: ringsPath(rings), class: "window", "fill-rule": "evenodd" }, g.walls);
  for (const rings of plan.doors) el("path", { d: ringsPath(rings), class: "door" }, g.walls);
  for (const rings of plan.front_door || []) el("path", { d: ringsPath(rings), class: "front-door" }, g.walls);
  return g;
}

function drawNodes(g, visited = null) {
  const s = scale();
  for (const n of nodes()) {
    const done = visited ? visited.includes(n.node_id) : false;
    el("circle", { cx: n.point[0], cy: -n.point[1], r: 0.18 * s, class: "node" + (done ? " alive" : ""), stroke: "var(--accent)" }, g.nodes);
    const t = el("text", { x: n.point[0] + 0.26 * s, y: -n.point[1] - 0.24 * s, class: "node-label", "font-size": 0.3 * s }, g.nodes);
    t.textContent = n.node_id;
  }
}

function drawHubMark(g, p, color, label = "H1") {
  const s = scale(), size = 0.42 * s;
  el("rect", { x: p[0] - size / 2, y: -p[1] - size / 2, width: size, height: size, rx: 0.06 * s, fill: color, class: "hub" }, g.nodes);
  const t = el("text", { x: p[0], y: -p[1] - 0.4 * s, class: "hub-label", fill: color, "font-size": 0.34 * s }, g.nodes);
  t.textContent = label;
}

function drawAnswerOn(svg, plan, answer, color) {
  const g = drawBase(svg, plan);
  for (const hub of answer.hubs) for (const leg of hub.legs) el("path", { d: polyPath(leg.polyline), class: "leg", stroke: color }, g.cable);
  const prev = S.plan;
  S.plan = plan;
  drawNodes(g, answer.hubs.flatMap((h) => h.node_ids));
  for (const hub of answer.hubs) drawHubMark(g, hub.point, color, hub.hub_id);
  S.plan = prev;
  return g;
}

function render() {
  if (!S.plan) return;
  const d = derive();
  const g = drawBase(svgMain, S.plan);
  const s = scale();
  for (const leg of d.legs) el("path", { d: polyPath(dedupe(leg.poly)), class: "leg", stroke: YOU }, g.cable);
  if (d.cur.length > 1) el("path", { d: polyPath(dedupe(d.cur)), class: "leg", stroke: YOU }, g.cable);
  drawNodes(g, d.stops);
  if (d.hub) drawHubMark(g, d.hub, YOU);
  S.groups = g;
  renderOverlay(d);
  renderPanel(d);
  if (S.result) drawSolverSide();
}

// the live preview under the cursor: where the next corner would go, or the L-shaped join to a device / the hub
function candidate(d, at) {
  const s = scale(), pick = PICK_M * s;
  if (!d.hub) return { kind: "hub", p: [snap(at[0]), snap(at[1])] };
  if (d.done) return null;
  const last = d.cur[d.cur.length - 1];
  const free = nodes().filter((n) => !d.stops.includes(n.node_id));
  const hit = free.find((n) => dist(n.point, at) <= pick);
  if (hit) return { kind: "node", id: hit.node_id, p: hit.point, via: connect(last, hit.point, S.flip) };
  if (!free.length && dist(d.hub, at) <= pick) return { kind: "close", p: d.hub, via: connect(last, d.hub, S.flip) };
  const dx = at[0] - last[0], dy = at[1] - last[1];
  const p = Math.abs(dx) >= Math.abs(dy) ? [snap(at[0]), last[1]] : [last[0], snap(at[1])];
  return dist(p, last) < 1e-6 * s ? null : { kind: "v", p, via: [p] };
}

function renderOverlay(d) {
  const g = S.groups;
  if (!g) return;
  g.overlay.replaceChildren();
  if (S.result || !S.cursor) return;
  const c = candidate(d, S.cursor);
  if (!c) return;
  const s = scale();
  if (c.kind === "hub") {
    const size = 0.42 * s;
    el("rect", { x: c.p[0] - size / 2, y: -c.p[1] - size / 2, width: size, height: size, rx: 0.06 * s, class: "hub-ghost" }, g.overlay);
    return;
  }
  const last = d.cur[d.cur.length - 1];
  el("path", { d: polyPath([last, ...c.via]), class: "chal-preview" }, g.overlay);
  if (c.kind !== "v") el("circle", { cx: c.p[0], cy: -c.p[1], r: 0.3 * s, class: "chal-target" }, g.overlay);
  else el("circle", { cx: c.p[0], cy: -c.p[1], r: 0.1 * s, class: "chal-dot" }, g.overlay);
}

// ---------- side panel ----------
function renderPanel(d) {
  const phase = phaseOf(d);
  const total = nodes().length;
  const st = stats(d);
  $("play-card").hidden = !S.plan;
  const text = {
    hub: "1 · Click inside a room to place the hub (the panel). Keep it away from the walls.",
    draw: d.stops.length < total
      ? `2 · Draw the loop: click to add corners (the cable runs straight), and click a device to join it. ${d.stops.length} of ${total} devices connected.`
      : "3 · All devices connected. Click the hub to close the loop.",
    done: "Loop closed. Press Submit to have it checked.",
  }[phase];
  $("step").textContent = S.result ? "Submitted. Try again or pick the next flat." : text;
  $("live").textContent = d.hub ? `Cable so far: ${st.L.toFixed(1)} m · ${st.B} bends` : "";
  $("undo").disabled = !S.actions.length || S.busy || !!S.result;
  $("restart").disabled = !S.actions.length && !S.result;
  $("flip").disabled = phase !== "draw" || !!S.result;
  $("flip").classList.toggle("on", S.flip);
  $("submit").disabled = phase !== "done" || S.busy || !!S.result;
}

function setStatus(text) {
  const st = $("status");
  st.hidden = !text;
  st.replaceChildren(...(text ? [html("span", { class: "pill" }, text)] : []));
}

function flash(text) {
  setStatus(text);
  clearTimeout(flash.timer);
  flash.timer = setTimeout(() => setStatus(""), 3500);
}

// ---------- clicks ----------
function onClick(at) {
  if (S.result || S.busy) return;
  const d = derive();
  const phase = phaseOf(d);
  if (phase === "done") return;
  const c = candidate(d, at);
  if (!c) return;
  if (phase === "hub") {
    const room = roomAt(c.p);
    if (!room || !room.eligible) return flash("The hub has to sit inside a room that has a device.");
    S.actions.push({ t: "hub", p: c.p });
  } else if (c.kind === "node") S.actions.push({ t: "node", id: c.id, flip: S.flip });
  else if (c.kind === "close") S.actions.push({ t: "close", flip: S.flip });
  else S.actions.push({ t: "v", p: c.p });
  render();
}

function undo() {
  if (!S.actions.length || S.busy || S.result) return;
  S.actions.pop();
  render();
}

function restart() {
  S.actions = [];
  S.result = null;
  $("result-card").hidden = true;
  $("wrap").classList.remove("split");
  $("title-you").hidden = true;
  $("title-solver").hidden = true;
  render();
  fit();
}

// ---------- submit, reveal ----------
const FRIENDLY = [
  [/overlap/, "Two stretches of your cable run along the same line. Give each leg its own line, a few centimetres apart."],
  [/within .* of a wall or window/, "The cable runs too close to a wall or window (keep at least 4 cm away)."],
  [/leaves the inner boundary/, "The cable leaves the flat."],
  [/passes between rooms outside a door/, "The cable goes through a wall. Use a door or an opening to change rooms."],
  [/enters .* \(zone of/, "The cable enters a room that belongs to another hub."],
  [/isn't axis-aligned/, "A stretch of cable is neither horizontal nor vertical."],
  [/hub is .* from a wall/, "The hub is too close to a wall (it needs 0.5 m)."],
  [/hub isn't inside an eligible room/, "The hub has to sit inside a room that has a device."],
  [/not assigned to any hub|served by 0 hubs/, "A room or device is not connected."],
  [/zone area/, "The zone is larger than 100 m²."],
  [/nodes > /, "The hub serves more than 5 devices."],
  [/leg doesn't (start|end) at/, "A leg of cable doesn't start or end exactly at its device."],
  [/visited \d+ times/, "A device was visited more than once, or never."],
];
const friendly = (v) => (FRIENDLY.find(([re]) => re.test(v.message)) || [null, v.message])[1];

async function submit() {
  const d = derive();
  if (phaseOf(d) !== "done" || S.busy) return;
  S.busy = true;
  renderPanel(d);
  setStatus("Checking your loop…");
  try {
    const answer = buildAnswer(d);
    const res = await fetch("api/validate", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: S.plan.plan_id, nodes: S.plan.nodes, answer }),
    });
    const check = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof check.detail === "string" ? check.detail : `HTTP ${res.status}`);
    S.result = { answer, check };
    setStatus("");
    showResult(check);
  } catch (err) {
    flash(`Couldn't check it: ${err.message}`);
  } finally {
    S.busy = false;
    render();
  }
}

const solverJ = () => S.solver.check?.metrics?.J ?? S.solver.answer.metrics.J;

function showResult(check) {
  const mine = check.metrics?.J;
  const theirs = solverJ();
  const verdict = $("verdict-line");
  verdict.className = "chal-verdict";
  let outcome;
  if (!check.valid) {
    verdict.textContent = "Not valid yet: it breaks a rule";
    verdict.classList.add("bad");
    outcome = "invalid";
  } else if (mine < theirs - 0.005) {
    verdict.textContent = `You beat 8ball by ${(theirs - mine).toFixed(2)} J`;
    verdict.classList.add("win");
    outcome = "win";
  } else if (mine <= theirs + 0.005) {
    verdict.textContent = "A tie with 8ball";
    verdict.classList.add("win");
    outcome = "tie";
  } else {
    verdict.textContent = `8ball wins by ${(mine - theirs).toFixed(2)} J`;
    outcome = "lose";
  }
  const m = check.metrics || {}, t = S.solver.check?.metrics || S.solver.answer.metrics;
  const cell = (v, digits) => (typeof v === "number" ? v.toFixed(digits) : "–");
  const row = (label, a, b) => {
    const tr = html("tr");
    tr.append(html("th", {}, label), html("td", {}, a), html("td", {}, b));
    return tr;
  };
  const table = html("table", { class: "iso-grid chal-table" });
  const head = html("tr");
  head.append(html("th", {}, ""), html("th", {}, "You"), html("th", {}, "8ball"));
  table.append(head,
    row("Cost J", cell(m.J, 2), cell(t.J, 2)), row("Cable L (m)", cell(m.L, 2), cell(t.L, 2)),
    row("Crossings X", cell(m.X, 0), cell(t.X, 0)), row("Overlap O (m)", cell(m.O, 2), cell(t.O, 2)),
    row("Bends B", cell(m.B, 0), cell(t.B, 0)));
  $("compare").replaceChildren(table);
  const grouped = new Map();   // the checker reports a rule once per cable segment: say each problem once, with a count
  for (const v of check.violations || []) {
    const key = `${v.rule}|${friendly(v)}`;
    grouped.set(key, { rule: v.rule, text: friendly(v), n: (grouped.get(key)?.n || 0) + 1 });
  }
  $("problems").replaceChildren(...[...grouped.values()].map((g) => {
    const li = html("li");
    li.append(html("b", {}, g.rule), document.createTextNode(`: ${g.text}${g.n > 1 ? ` (${g.n} places)` : ""}`));
    return li;
  }));
  $("result-card").hidden = false;
  $("title-you").textContent = `You · ${check.valid ? `J ${cell(m.J, 2)}` : "not valid"}`;
  $("title-you").hidden = false;
  $("title-you").classList.toggle("bad", !check.valid);
  $("title-solver").textContent = `8ball · J ${cell(t.J, 2)}`;
  $("title-solver").hidden = false;
  $("wrap").classList.add("split");
  drawSolverSide();
  fit();
  if (check.valid) record(mine, theirs);
  renderBoard();
  return outcome;
}

function drawSolverSide() {
  drawAnswerOn(svgSolver, S.plan, S.solver.answer, SOLVER);
}

// ---------- leaderboard (this browser only) ----------
function loadBoard() {
  try { return JSON.parse(localStorage.getItem(BOARD_KEY) || "[]"); } catch { return []; }
}
function saveBoard(list) {
  try { localStorage.setItem(BOARD_KEY, JSON.stringify(list.slice(-300))); } catch { /* private mode: the board just doesn't persist */ }
}
function playerName() {
  const v = $("name").value.trim();
  return v || "Anonymous";
}
function record(J, solver) {
  const list = loadBoard();
  list.push({ plan_id: S.plan.plan_id, name: playerName(), J: Math.round(J * 100) / 100, solver: Math.round(solver * 100) / 100, when: Date.now() });
  saveBoard(list);
  try { localStorage.setItem(NAME_KEY, $("name").value.trim()); } catch { /* optional */ }
}
function renderBoard() {
  const sec = $("board-card");
  sec.hidden = !S.plan;
  if (!S.plan) return;
  const rows = loadBoard().filter((e) => e.plan_id === S.plan.plan_id).sort((a, b) => a.J - b.J || a.when - b.when).slice(0, 5);
  $("board").replaceChildren(...(rows.length ? rows.map((e) => {
    const li = html("li");
    li.append(html("span", {}, e.name), html("b", {}, `J ${e.J.toFixed(2)}`));
    if (e.J < e.solver - 0.005) li.append(html("small", {}, "beat 8ball"));
    return li;
  }) : [html("li", { class: "quiet" }, "No valid loops yet. Be the first.")]));
}

// ---------- pan and zoom ----------
function setView(v) {
  S.view = v;
  for (const svg of maps) svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
}
function fit() {
  if (!S.plan) return;
  const [minx, miny, maxx, maxy] = S.plan.bounds;
  S.base = { x: minx, y: -maxy, w: maxx - minx, h: maxy - miny };
  setView({ ...S.base });
}
function svgPoint(svg, cx, cy) {
  const pt = svg.createSVGPoint();
  pt.x = cx; pt.y = cy;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}
function zoomAt(cx, cy, factor) {
  const v = S.view;
  const w = Math.min(Math.max(v.w * factor, S.base.w / 30), S.base.w * 3);
  const k = w / v.w;
  setView({ x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k, w, h: v.h * k });
}

for (const svg of maps) {
  svg.addEventListener("wheel", (e) => {
    if (!S.view) return;
    e.preventDefault();
    const p = svgPoint(svg, e.clientX, e.clientY);
    zoomAt(p.x, p.y, e.deltaY > 0 ? 1.15 : 1 / 1.15);
  }, { passive: false });
  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    if (!S.view) return;
    drag = { x: e.clientX, y: e.clientY, view: { ...S.view }, moved: false };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (drag) {
      if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 5) { drag.moved = true; svg.classList.add("dragging"); }
      if (drag.moved) {
        const kk = Math.max(drag.view.w / svg.clientWidth, drag.view.h / svg.clientHeight);
        setView({ ...drag.view, x: drag.view.x - (e.clientX - drag.x) * kk, y: drag.view.y - (e.clientY - drag.y) * kk });
      }
      return;
    }
    if (svg !== svgMain || !S.plan) return;
    const p = svgPoint(svg, e.clientX, e.clientY);
    S.cursor = [p.x, -p.y];
    renderOverlay(derive());
  });
  svg.addEventListener("pointerup", (e) => {
    const wasClick = drag && !drag.moved;
    drag = null;
    svg.classList.remove("dragging");
    if (wasClick && svg === svgMain) {
      const p = svgPoint(svg, e.clientX, e.clientY);
      onClick([p.x, -p.y]);
    }
  });
  svg.addEventListener("pointerleave", () => { if (svg === svgMain) { S.cursor = null; if (S.plan) renderOverlay(derive()); } });
  svg.addEventListener("pointercancel", () => { drag = null; svg.classList.remove("dragging"); });
}
$("zoom-in").addEventListener("click", () => { const v = S.view; if (v) zoomAt(v.x + v.w / 2, v.y + v.h / 2, 1 / 1.4); });
$("zoom-out").addEventListener("click", () => { const v = S.view; if (v) zoomAt(v.x + v.w / 2, v.y + v.h / 2, 1.4); });
$("zoom-reset").addEventListener("click", fit);

$("undo").addEventListener("click", undo);
$("restart").addEventListener("click", restart);
$("flip").addEventListener("click", () => { S.flip = !S.flip; render(); });
$("submit").addEventListener("click", submit);
$("again").addEventListener("click", restart);
$("next").addEventListener("click", () => {
  const i = S.entries.indexOf(S.entry);
  choose(S.entries[(i + 1) % S.entries.length]);
});
window.addEventListener("keydown", (e) => {
  if (e.target instanceof HTMLInputElement) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); undo(); }
  else if (e.key.toLowerCase() === "b" && !e.ctrlKey && !e.metaKey) { S.flip = !S.flip; render(); }
});

// ---------- choosing a flat ----------
async function getJSON(url, optional = false) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    if (optional) return null;
    throw new Error(`${url}: HTTP ${res.status}`);
  }
  return res.json();
}

function renderChoices() {
  $("plan-choice").replaceChildren(...S.entries.map((e) => {
    const b = html("button", { type: "button", class: `opt${e === S.entry ? " on" : ""}` });
    b.append(html("b", {}, `Plan ${e.plan_id}`), html("span", {}, `${e.rooms} rooms · ${e.area_m2.toFixed(0)} m²`));
    b.addEventListener("click", () => choose(e));
    return b;
  }));
}

async function choose(entry) {
  S.entry = entry;
  S.actions = [];
  S.result = null;
  S.flip = false;
  $("result-card").hidden = true;
  $("wrap").classList.remove("split");
  $("title-you").hidden = true;
  $("title-solver").hidden = true;
  setStatus("Loading…");
  try {
    const [plan, answer, check] = await Promise.all([
      getJSON(`${entry.path}/plan.json`), getJSON(`${entry.path}/answer.json`), getJSON(`${entry.path}/check.json`, true),
    ]);
    S.plan = plan;
    S.solver = { answer, check };
    setStatus("");
    fit();
    render();
    renderBoard();
    renderChoices();
    const url = new URL(location.href);
    url.searchParams.set("plan", entry.plan_id);
    history.replaceState(null, "", url);
  } catch (err) {
    setStatus(`Couldn't load plan ${entry.plan_id}: ${err.message}`);
  }
}

async function init() {
  try { $("name").value = localStorage.getItem(NAME_KEY) || ""; } catch { /* optional */ }
  try {
    S.api = (await fetch("api/health", { cache: "no-store" })).ok;
  } catch { S.api = false; }
  const gallery = await getJSON("data/gallery/index.json", true);
  S.entries = (gallery?.plans || []).filter((e) => e.metrics?.H === 1 && e.valid !== false && e.solved !== false);
  if (!S.entries.length) return setStatus("No one-hub flats found. Build the gallery first: python -m eightball.bench.gallery");
  if (!S.api) return setStatus("The challenge needs the 8ball server (python -m eightball serve): it checks your loop.");
  const want = Number(new URL(location.href).searchParams.get("plan"));
  renderChoices();
  choose(S.entries.find((e) => e.plan_id === want) || S.entries[0]);
}

init();
