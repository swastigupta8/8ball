// 8ball viewer v0 (Person B, step B3). Vanilla JS + SVG. Reads a bundle folder with plan.json and,
// optionally, answer.json and check.json (written by `python -m eightball export-plan`).
// Plan coordinates are y-up; SVG is y-down, so every point is drawn as (x, -y).
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
const HUB_COLORS = ["#2563A8", "#D2601A", "#1E8A5A", "#8B4FB0", "#C23B73", "#6F7F1F", "#2B8FA6", "#9A6A2E"];
const LAYERS = [
  ["zones", "Zones"], ["walls", "Walls & doors"], ["rings", "Cable rings"], ["numbers", "Leg order"],
  ["nodes", "Hubs & nodes"], ["labels", "Room labels"], ["violations", "Violations"], ["passages", "Open passages"],
];

const state = { bundle: null, plan: null, answer: null, check: null, base: null, view: null, layers: {} };
LAYERS.forEach(([k]) => (state.layers[k] = k !== "passages"));

const $ = (id) => document.getElementById(id);
const svg = $("canvas");

function el(tag, attrs = {}, parent = null) {
  const node = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function html(tag, attrs = {}, text = null) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text !== null) node.textContent = text;
  return node;
}

const P = (p) => `${p[0]},${-p[1]}`;
const ringsPath = (rings) => rings.map((r) => "M" + r.map(P).join("L") + "Z").join("");
const polyPath = (pts) => "M" + pts.map(P).join("L");
const hubColor = (k) => HUB_COLORS[k % HUB_COLORS.length];

function legLength(poly, scale) {
  let d = 0;
  for (let i = 1; i < poly.length; i++) d += Math.abs(poly[i][0] - poly[i - 1][0]) + Math.abs(poly[i][1] - poly[i - 1][1]);
  return d / scale;
}

function legBends(poly) {
  let n = 0;
  for (let i = 1; i < poly.length - 1; i++) {
    const a = [Math.sign(poly[i][0] - poly[i - 1][0]), Math.sign(poly[i][1] - poly[i - 1][1])];
    const b = [Math.sign(poly[i + 1][0] - poly[i][0]), Math.sign(poly[i + 1][1] - poly[i][1])];
    if (a[0] !== b[0] || a[1] !== b[1]) n++;
  }
  return n;
}

function labelPoint(poly) {
  let best = poly[0], bestLen = -1;
  for (let i = 1; i < poly.length; i++) {
    const len = Math.abs(poly[i][0] - poly[i - 1][0]) + Math.abs(poly[i][1] - poly[i - 1][1]);
    if (len > bestLen) {
      bestLen = len;
      best = [(poly[i][0] + poly[i - 1][0]) / 2, (poly[i][1] + poly[i - 1][1]) / 2];
    }
  }
  return best;
}

// ---------- hover box ----------
const hoverBox = $("hover");
function showHover(evt, lines) {
  hoverBox.replaceChildren(...lines.map((t, i) => (i === 0 ? html("strong", {}, t) : html("div", {}, t))));
  const wrap = svg.parentElement.getBoundingClientRect();
  hoverBox.style.left = `${Math.max(8, Math.min(evt.clientX - wrap.left + 14, wrap.width - 240))}px`;
  hoverBox.style.top = `${Math.max(8, Math.min(evt.clientY - wrap.top + 14, wrap.height - 90))}px`;
  hoverBox.hidden = false;
}
function hideHover() { hoverBox.hidden = true; }
function hoverable(node, lines, onEnter, onLeave) {
  node.addEventListener("pointermove", (e) => showHover(e, typeof lines === "function" ? lines() : lines));
  node.addEventListener("pointerenter", () => onEnter && onEnter());
  node.addEventListener("pointerleave", () => { hideHover(); onLeave && onLeave(); });
}

// ---------- drawing ----------
function draw() {
  const { plan, answer, check } = state;
  svg.replaceChildren();
  const s = plan.scale;
  const groups = {};
  for (const name of ["zones", "passages", "walls", "labels", "rings", "numbers", "nodes", "violations"]) {
    groups[name] = el("g", { "data-layer": name }, svg);
  }

  const zoneOf = {}, colorOf = {}, hubOfNode = {};
  (answer?.hubs || []).forEach((h, k) => {
    colorOf[h.hub_id] = hubColor(k);
    h.room_ids.forEach((r) => (zoneOf[r] = h.hub_id));
    h.node_ids.forEach((n) => (hubOfNode[n] = h.hub_id));
  });

  for (const rings of plan.inner) el("path", { d: ringsPath(rings), fill: "var(--surface)", "fill-rule": "evenodd" }, groups.zones);
  for (const room of plan.rooms) {
    const hub = zoneOf[room.room_id];
    const attrs = { d: ringsPath(room.polygon), "fill-rule": "evenodd" };
    if (hub) Object.assign(attrs, { class: "room", fill: colorOf[hub], "fill-opacity": 0.16 });
    else attrs.class = "room " + (room.eligible ? "free" : "excluded");
    const path = el("path", attrs, groups.zones);
    hoverable(path, [
      `${room.type} · ${room.room_id}`,
      `${room.area_m2.toFixed(1)} m²${room.eligible ? "" : " · no node (excluded)"}`,
      hub ? `zone of ${hub}` : room.eligible ? "not assigned" : "",
    ].filter(Boolean));
    const t = el("text", { x: room.label_point[0], y: -room.label_point[1] + 0.55 * s, class: "room-label", "font-size": 0.26 * s }, groups.labels);
    t.textContent = room.type;
  }
  for (const rings of plan.passages || []) el("path", { d: ringsPath(rings), class: "passage" }, groups.passages);
  for (const rings of plan.walls) el("path", { d: ringsPath(rings), class: "wall", "fill-rule": "evenodd" }, groups.walls);
  for (const rings of plan.windows) el("path", { d: ringsPath(rings), class: "window", "fill-rule": "evenodd" }, groups.walls);
  for (const rings of plan.doors) {
    const d = el("path", { d: ringsPath(rings), class: "door" }, groups.walls);
    hoverable(d, ["Door", "cable may pass between rooms here"]);
  }
  for (const rings of plan.front_door || []) {
    const d = el("path", { d: ringsPath(rings), class: "front-door" }, groups.walls);
    hoverable(d, ["Front door", "not a zone link"]);
  }

  const nodePts = Object.fromEntries((plan.nodes.length ? plan.nodes : answer?.nodes || []).map((n) => [n.node_id, n]));
  const legEls = [];
  (answer?.hubs || []).forEach((h, k) => {
    const c = colorOf[h.hub_id];
    h.legs.forEach((leg, i) => {
      const d = polyPath(leg.polyline);
      const line = el("path", { d, class: "leg", stroke: c }, groups.rings);
      const hit = el("path", { d, class: "leg hit" }, groups.rings);
      legEls.push(line);
      const len = legLength(leg.polyline, s);
      hoverable(hit, [
        `${h.hub_id} · leg ${i + 1} of ${h.legs.length}${i === h.legs.length - 1 ? " (return)" : ""}`,
        `${leg.from} → ${leg.to}`,
        `${len.toFixed(2)} m · ${legBends(leg.polyline)} bends inside the leg`,
      ], () => legEls.forEach((e) => e !== line && e.classList.add("dim")),
         () => legEls.forEach((e) => e.classList.remove("dim")));
      const [lx, ly] = labelPoint(leg.polyline);
      const g = el("g", { class: "leg-num" }, groups.numbers);
      el("circle", { cx: lx, cy: -ly, r: 0.2 * s, stroke: c }, g);
      const t = el("text", { x: lx, y: -ly, fill: c, "font-size": 0.22 * s }, g);
      t.textContent = String(i + 1);
    });
  });

  for (const [nid, n] of Object.entries(nodePts)) {
    const hub = hubOfNode[nid];
    const c = hub ? colorOf[hub] : "var(--quiet)";
    const circle = el("circle", { cx: n.point[0], cy: -n.point[1], r: 0.16 * s, class: "node", stroke: c }, groups.nodes);
    hoverable(circle, [`Node ${nid}`, `room ${n.room_id}`, hub ? `served by ${hub}` : "not served by any hub"]);
    const t = el("text", { x: n.point[0] + 0.24 * s, y: -n.point[1] - 0.22 * s, class: "node-label", "font-size": 0.3 * s }, groups.nodes);
    t.textContent = nid;
  }
  (answer?.hubs || []).forEach((h) => {
    const c = colorOf[h.hub_id];
    const size = 0.42 * s;
    const r = el("rect", { x: h.point[0] - size / 2, y: -h.point[1] - size / 2, width: size, height: size, rx: 0.06 * s, fill: c, class: "hub" }, groups.nodes);
    hoverable(r, [`Hub ${h.hub_id}`, `in ${h.room_id}`, `${h.node_ids.length} nodes · ${h.area_m2.toFixed(1)} m²`, h.sequence.join(" → ")]);
    const t = el("text", { x: h.point[0], y: -h.point[1] - 0.4 * s, class: "hub-label", fill: c, "font-size": 0.34 * s }, groups.nodes);
    t.textContent = h.hub_id;
  });

  for (const v of check?.violations || []) {
    if (!v.location) continue;
    const [x, y] = v.location, a = 0.22 * s;
    const g = el("g", {}, groups.violations);
    el("circle", { cx: x, cy: -y, r: 0.45 * s, class: "violation-ring" }, g);
    el("path", { d: `M${x - a},${-y - a}L${x + a},${-y + a}M${x - a},${-y + a}L${x + a},${-y - a}`, class: "violation" }, g);
    hoverable(g, [`${v.rule}${v.hub_id ? " · " + v.hub_id : ""}`, v.message]);
  }
  applyLayers();
}

// ---------- side panel ----------
function panel() {
  const { plan, answer, check } = state;
  const verdict = $("verdict");
  verdict.className = "verdict";
  if (!answer) verdict.replaceChildren(document.createTextNode(`Plan ${plan.plan_id}`), html("small", {}, "No answer loaded"));
  else if (!check) verdict.replaceChildren(document.createTextNode("Not checked"), html("small", {}, `Plan ${plan.plan_id}`));
  else {
    verdict.classList.add(check.valid ? "good" : "bad");
    verdict.replaceChildren(document.createTextNode(check.valid ? "Valid" : `Invalid · ${check.violations.length} violations`),
      html("small", {}, `Plan ${plan.plan_id} · solver: ${answer.meta?.solver ?? "?"}`));
  }
  const m = check?.metrics && Object.keys(check.metrics).length ? check.metrics : answer?.metrics || {};
  const rows = answer ? [
    ["Hubs", m.H ?? answer.hubs.length], ["Cable L", fmt(m.L, " m")], ["Crossings X", m.X ?? "–"],
    ["Overlap O", fmt(m.O, " m")], ["Bends B", m.B ?? "–"], ["J", fmt(m.J)],
  ] : [["Scale", `${plan.scale.toFixed(2)} units/m`], ["Rooms", plan.rooms.length], ["Doors", plan.doors.length]];
  $("score").replaceChildren(...rows.map(([k, v]) => {
    const tr = html("tr", k === "J" ? { class: "total" } : {});
    tr.append(html("td", {}, k), html("td", {}, String(v)));
    return tr;
  }));
  document.querySelector(".formula").hidden = !answer;
  $("hubs-title").hidden = !answer;
  $("hubs").replaceChildren(...(answer?.hubs || []).map((h, k) => {
    const li = html("li");
    const sw = html("span", { class: "swatch" });
    sw.style.background = hubColor(k);
    li.append(sw, html("b", {}, h.hub_id), document.createTextNode(` · ${h.node_ids.length} nodes · ${h.area_m2.toFixed(1)} m²`),
      html("div", { class: "seq" }, h.sequence.join(" → ")));
    return li;
  }));
  const viol = check?.violations || [];
  $("violations-title").hidden = viol.length === 0;
  $("violations").replaceChildren(...viol.map((v) => {
    const li = html("li");
    li.append(html("b", {}, v.rule), document.createTextNode(`${v.hub_id ? " · " + v.hub_id : ""}: ${v.message}`));
    if (v.location) li.addEventListener("click", () => zoomTo(v.location, 3 * plan.scale));
    return li;
  }));
  $("layers").replaceChildren(...LAYERS.map(([key, label]) => {
    const lab = html("label");
    const box = html("input", { type: "checkbox" });
    box.checked = state.layers[key];
    box.addEventListener("change", () => { state.layers[key] = box.checked; applyLayers(); });
    lab.append(box, document.createTextNode(label));
    return lab;
  }));
}

function fmt(v, unit = "") { return typeof v === "number" ? v.toFixed(2) + unit : "–"; }

function applyLayers() {
  svg.querySelectorAll("g[data-layer]").forEach((g) => {
    g.style.display = state.layers[g.dataset.layer] ? "" : "none";
  });
}

// ---------- pan & zoom ----------
function setView(v) {
  state.view = v;
  svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
}
function fit() {
  const [minx, miny, maxx, maxy] = state.plan.bounds;
  state.base = { x: minx, y: -maxy, w: maxx - minx, h: maxy - miny };
  setView({ ...state.base });
}
function svgPoint(clientX, clientY) {
  const pt = svg.createSVGPoint();
  pt.x = clientX; pt.y = clientY;
  return pt.matrixTransform(svg.getScreenCTM().inverse());
}
function zoomAt(cx, cy, factor) {
  const v = state.view;
  const w = Math.min(Math.max(v.w * factor, state.base.w / 40), state.base.w * 4);
  const k = w / v.w;
  setView({ x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k, w, h: v.h * k });
}
function zoomTo(loc, width) {
  const h = width * state.base.h / state.base.w;
  setView({ x: loc[0] - width / 2, y: -loc[1] - h / 2, w: width, h });
}
svg.addEventListener("wheel", (e) => {
  if (!state.view) return;
  e.preventDefault();
  const p = svgPoint(e.clientX, e.clientY);
  zoomAt(p.x, p.y, e.deltaY > 0 ? 1.15 : 1 / 1.15);
}, { passive: false });
let drag = null;
svg.addEventListener("pointerdown", (e) => {
  if (!state.view) return;
  drag = { x: e.clientX, y: e.clientY, view: { ...state.view } };
  svg.setPointerCapture(e.pointerId);
  svg.classList.add("dragging");
});
svg.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const k = drag.view.w / svg.clientWidth;
  const kk = Math.max(k, drag.view.h / svg.clientHeight);
  setView({ ...drag.view, x: drag.view.x - (e.clientX - drag.x) * kk, y: drag.view.y - (e.clientY - drag.y) * kk });
});
const endDrag = () => { drag = null; svg.classList.remove("dragging"); };
svg.addEventListener("pointerup", endDrag);
svg.addEventListener("pointercancel", endDrag);
$("zoom-in").addEventListener("click", () => { const v = state.view; zoomAt(v.x + v.w / 2, v.y + v.h / 2, 1 / 1.4); });
$("zoom-out").addEventListener("click", () => { const v = state.view; zoomAt(v.x + v.w / 2, v.y + v.h / 2, 1.4); });
$("zoom-reset").addEventListener("click", fit);

// ---------- loading ----------
async function getJSON(url, optional = false) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) {
    if (optional) return null;
    throw new Error(`${url}: HTTP ${res.status}`);
  }
  return res.json();
}

function setStatus(text) {
  const st = $("status");
  st.hidden = !text;
  st.textContent = text || "";
}

async function loadBundle(path) {
  setStatus("Loading…");
  try {
    const [plan, answer, check] = await Promise.all([
      getJSON(`${path}/plan.json`), getJSON(`${path}/answer.json`, true), getJSON(`${path}/check.json`, true),
    ]);
    Object.assign(state, { bundle: path, plan, answer, check });
    fit();
    draw();
    panel();
    setStatus("");
    const url = new URL(location.href);
    url.searchParams.set("plan", path);
    history.replaceState(null, "", url);
  } catch (err) {
    setStatus(`Couldn't load ${path}: ${err.message}`);
  }
}

async function init() {
  const index = (await getJSON("data/plans/index.json", true)) || { plans: [] };
  const select = $("plan-select");
  const wanted = new URL(location.href).searchParams.get("plan");
  const entries = index.plans.slice();
  if (wanted && !entries.some((e) => e.path === wanted)) entries.unshift({ path: wanted, label: wanted });
  select.replaceChildren(...entries.map((e) => html("option", { value: e.path }, e.label)));
  select.addEventListener("change", () => loadBundle(select.value));
  const first = wanted || entries[0]?.path;
  if (!first) return setStatus("No plans found: run `python -m eightball export-plan` first.");
  select.value = first;
  loadBundle(first);
}

init();
