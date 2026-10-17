// 8ball viewer (Person B: B3 viewer, B9 break-the-cable). Vanilla JS + SVG.
// Reads a bundle folder: plan.json, and optionally answer.json, check.json, branching.json, heatmaps.json
// (written by `python -m eightball export-plan`). Plan coordinates are y-up; SVG is y-down, so every
// point is drawn as (x, -y).
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
const HUB_COLORS = ["#5ff0cf", "#f2b680", "#ff8fbd", "#a7b6ff", "#d4a8ff", "#ffe08a", "#7fd6ff", "#ff9e7a"];  // same lights as the landing page
// Display options. The heatmap has its own switch in its panel section, so it isn't listed here.
const LAYERS = [
  ["zones", "Zones"], ["walls", "Walls & doors"], ["rings", "Cable rings"], ["numbers", "Leg order"],
  ["nodes", "Hubs & devices"], ["labels", "Room labels"], ["violations", "Violations"], ["passages", "Open passages"],
];

const state = {
  bundle: null, plan: null, answer: null, check: null, branching: null, heatmaps: null,
  base: null, view: null, layers: { heatmap: false }, breakMode: false, cuts: [],
  shorts: [], faultMode: "cut", isoK: 1, isoOn: false,   // short circuits and isolators (V2 feature 1)
};
LAYERS.forEach(([k]) => (state.layers[k] = k !== "passages"));

const $ = (id) => document.getElementById(id);
const loopSvg = $("canvas");
const treeSvg = $("canvas-tree");
const maps = [loopSvg, treeSvg];

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
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

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

function project(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2)) : 0;
  const q = [a[0] + t * dx, a[1] + t * dy];
  return { q, t, d: dist(p, q) };
}

// ---------- break-the-cable model ----------
// A ring is walked as one polyline from its hub through every leg and back. Positions along it are
// distances from the hub. A cut at position c: going forward from the hub reaches every stop before
// the first cut; going backward reaches every stop after the last cut. A stop reached neither way is lost.

function ringModel(hub) {
  const segs = [];
  const stops = [];
  let d = 0;
  hub.legs.forEach((leg, i) => {
    if (i > 0) stops.push({ id: leg.from, d });
    for (let k = 1; k < leg.polyline.length; k++) {
      const a = leg.polyline[k - 1], b = leg.polyline[k];
      segs.push({ a, b, d0: d, leg: i });
      d += dist(a, b);
    }
  });
  return { hub_id: hub.hub_id, segs, stops, total: d };
}

function treeModel(branching) {
  const out = [];
  for (const h of branching?.hubs || []) {
    const paths = Object.entries(h.paths).map(([node, poly]) => ({ node, poly }));
    out.push({ hub_id: h.hub_id, point: h.point, paths });
  }
  return out;
}

function nearestRingSeg(models, p) {
  let best = null;
  for (const m of models) {
    for (const s of m.segs) {
      const pr = project(p, s.a, s.b);
      if (!best || pr.d < best.d) best = { model: m, seg: s, q: pr.q, d: pr.d, pos: s.d0 + dist(s.a, pr.q) };
    }
  }
  return best;
}

function nearestTreeSeg(trees, p) {
  let best = null;
  for (const t of trees) {
    for (const path of t.paths) {
      for (let k = 1; k < path.poly.length; k++) {
        const pr = project(p, path.poly[k - 1], path.poly[k]);
        if (!best || pr.d < best.d) best = { tree: t, q: pr.q, d: pr.d };
      }
    }
  }
  return best;
}

function onPath(poly, q, tol) {
  for (let k = 1; k < poly.length; k++) if (project(q, poly[k - 1], poly[k]).d <= tol) return true;
  return false;
}

// Effects of the current cuts on the loop: per node, how its signal arrives ("fwd", "back", "both") or "lost".
function loopEffects() {
  const s = state.plan.scale;
  const models = state.loopModels;
  const cutsByHub = {};
  const marks = [];
  for (const c of state.cuts) {
    const near = nearestRingSeg(models, c);
    if (!near || near.d > 0.3 * s) continue;
    (cutsByHub[near.model.hub_id] ||= []).push(near.pos);
    marks.push(near.q);
  }
  const status = {};
  for (const m of models) {
    const cuts = cutsByHub[m.hub_id] || [];
    for (const stop of m.stops) {
      const fwd = cuts.every((c) => c > stop.d);
      const back = cuts.every((c) => c < stop.d);
      status[stop.id] = fwd && back ? "both" : fwd ? "fwd" : back ? "back" : "lost";
    }
  }
  const shortMarks = [];  // short circuits (V2 feature 1): every device of the shorted segment is lost
  for (const c of state.shorts) {
    const near = nearestRingSeg(models, c);
    if (!near || near.d > 0.3 * s) continue;
    shortMarks.push(near.q);
    for (const id of shortLost(near)) status[id] = "lost";
  }
  return { status, marks, shortMarks };
}

function treeEffects() {
  const s = state.plan.scale;
  const status = {};
  const marks = [];
  const shortMarks = [];
  for (const t of state.treeModels) for (const p of t.paths) status[p.node] = "ok";
  for (const [list, into] of [[state.cuts, marks], [state.shorts, shortMarks]]) {
    for (const c of list) {
      const near = nearestTreeSeg(state.treeModels, c);
      if (!near || near.d > 0.3 * s) continue;
      into.push(near.q);   // a short on a branch kills everything downstream, same as a cut
      for (const p of near.tree.paths) if (onPath(p.poly, near.q, 0.01 * s)) status[p.node] = "lost";
    }
  }
  return { status, marks, shortMarks };
}

// ---------- short circuits and loop isolators (V2 feature 1; reference: optimize/isolators.py) ----------
// A short anywhere on a stretch of loop disables every device on that stretch. Isolators cut the ring into
// stretches; the hub (panel) is isolated on both sides. Positions are distances along the ring from the hub.
function legSpans(model) {
  const spans = [];
  for (const seg of model.segs) {
    const len = dist(seg.a, seg.b);
    const sp = (spans[seg.leg] ||= { d0: seg.d0, d1: seg.d0 });
    sp.d1 = Math.max(sp.d1, seg.d0 + len);
  }
  return spans;
}

function pointAtPos(model, pos) {
  for (const seg of model.segs) {
    const len = dist(seg.a, seg.b);
    if (len > 0 && pos <= seg.d0 + len + 1e-9) {
      const f = Math.max(0, (pos - seg.d0) / len);
      return [seg.a[0] + (seg.b[0] - seg.a[0]) * f, seg.a[1] + (seg.b[1] - seg.a[1]) * f];
    }
  }
  const last = model.segs[model.segs.length - 1];
  return last ? last.b : [0, 0];
}

// Isolators for "at most k devices lost per short": one on the leg after every k-th device (legs k, 2k, ... < n),
// at the middle of that leg. Same rule as isolators.place_isolators.
function isolatorSpots(models, k) {
  const out = [];
  for (const m of models) {
    const spans = legSpans(m);
    for (let leg = k; leg < m.stops.length; leg += k) {
      const sp = spans[leg];
      if (!sp) continue;
      const pos = (sp.d0 + sp.d1) / 2;
      out.push({ hub_id: m.hub_id, leg_index: leg, pos, point: pointAtPos(m, pos) });
    }
  }
  return out;
}

const isolatorsShown = () => state.isoOn && state.faultMode === "short" && !!state.loopModels.length;
const activeIsolators = () => (isolatorsShown() ? isolatorSpots(state.loopModels, state.isoK) : []);

// Device ids lost by a short at a ring position (`near` from nearestRingSeg), given the isolators now placed.
function shortLost(near) {
  const iso = activeIsolators().filter((i) => i.hub_id === near.model.hub_id).map((i) => i.pos);
  const group = (d) => iso.filter((p) => p < d).length;
  const g = group(near.pos);
  return near.model.stops.filter((stop) => group(stop.d) === g).map((stop) => stop.id);
}

// The most devices one short can take out of a ring, for a set of isolators.
function worstShort(models, spots) {
  let worst = 0;
  for (const m of models) {
    const iso = spots.filter((i) => i.hub_id === m.hub_id).map((i) => i.pos);
    const sizes = {};
    for (const stop of m.stops) {
      const g = iso.filter((p) => p < stop.d).length;
      sizes[g] = (sizes[g] || 0) + 1;
    }
    worst = Math.max(worst, ...Object.values(sizes), 0);
  }
  return worst;
}

// Room fault (stretch): a fire or leak in one room shorts every cable passing through it. A room that carries two
// different segments of the same ring takes both out at once: the honest limit of "loops survive".
function roomFaults() {
  const spots = activeIsolators();
  if (!spots.length || !state.plan) return [];
  const s = state.plan.scale;
  const found = new Map();
  for (const m of state.loopModels) {
    const iso = spots.filter((i) => i.hub_id === m.hub_id).map((i) => i.pos);
    const seen = new Map();
    for (const seg of m.segs) {
      const len = dist(seg.a, seg.b);
      const steps = Math.max(1, Math.ceil(len / (0.15 * s)));
      for (let k = 0; k <= steps; k++) {
        const d = seg.d0 + (len * k) / steps;
        const p = [seg.a[0] + ((seg.b[0] - seg.a[0]) * k) / steps, seg.a[1] + ((seg.b[1] - seg.a[1]) * k) / steps];
        const room = state.plan.rooms.find((r) => pointInRooms(p, r.polygon));
        if (!room) continue;
        (seen.get(room.room_id) || seen.set(room.room_id, new Set()).get(room.room_id)).add(iso.filter((q) => q < d - 1e-9).length);
      }
    }
    for (const [rid, groups] of seen) if (groups.size > 1) found.set(rid, { room_id: rid, hub_id: m.hub_id, segments: groups.size });
  }
  return [...found.values()];
}

function pointInRooms(p, rings) {
  const inRing = (ring) => {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };
  return inRing(rings[0]) && !rings.slice(1).some(inRing);
}

// ---------- hub cost heatmap ----------
// Each heatmap point is a candidate hub spot coloured by its extra J for the zone's chosen loop
// (solver step 6). Cheapest = brightest. The chosen hub is the minimum of the same function.
const RAMP = ["#FDE725", "#7AD151", "#22A884", "#2A788E", "#414487", "#440154"];

function rampRGB(t) {
  const x = Math.max(0, Math.min(1, t)) * (RAMP.length - 1);
  const i = Math.min(RAMP.length - 2, Math.floor(x));
  const f = x - i;
  const a = RAMP[i], b = RAMP[i + 1];
  const mix = (k) => Math.round(parseInt(a.slice(k, k + 2), 16) * (1 - f) + parseInt(b.slice(k, k + 2), 16) * f);
  return [mix(1), mix(3), mix(5)];
}

function heatRange(heatmaps) {
  const vals = heatmaps.flatMap((h) => h.points.map((p) => p[2])).sort((a, b) => a - b);
  if (!vals.length) return { lo: 0, hi: 1 };
  const hi = vals[Math.min(vals.length - 1, Math.floor(0.95 * vals.length))];
  return { lo: vals[0], hi: Math.max(hi, vals[0] + 1e-9) };
}

// The cheapest point must sit at the chosen hub (within one grid step).
function heatCheck(h, scale) {
  if (!h.points.length) return { ok: false, min: null };
  let best = h.points[0];
  for (const p of h.points) if (p[2] < best[2]) best = p;
  const chosenVal = h.points.filter((p) => dist(p, h.chosen) < 1e-6 * scale).map((p) => p[2]);
  const ok = chosenVal.length ? chosenVal[0] <= best[2] + 1e-9 : dist(best, h.chosen) <= h.step_m * scale + 1e-9;
  return { ok, min: best };
}

// Smooth heatmap: one pixel per grid point, scaled up by the browser with bilinear smoothing, then clipped
// to the zone's rooms. Empty pixels next to the grid take their neighbours' mean so the edge doesn't fade.
function drawHeatmap(groups) {
  const hms = state.heatmaps || [];
  if (!hms.length) return;
  const s = state.plan.scale;
  const { lo, hi } = heatRange(hms);
  const { zoneOf } = zoneColors();
  const defs = el("defs", {}, groups.heatmap);
  hms.forEach((h, k) => {
    if (!h.points.length) return;
    const cell = h.step_m * s;
    const xs = h.points.map((p) => p[0]), ys = h.points.map((p) => p[1]);
    const x0 = Math.min(...xs) - cell, y1 = Math.max(...ys) + cell;  // one empty ring of pixels for the padding
    const cols = Math.round((Math.max(...xs) + cell - x0) / cell) + 1;
    const rows = Math.round((y1 - (Math.min(...ys) - cell)) / cell) + 1;
    const grid = new Float64Array(cols * rows).fill(NaN);
    for (const [x, y, v] of h.points) grid[Math.round((y1 - y) / cell) * cols + Math.round((x - x0) / cell)] = v;
    const padded = grid.slice();
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        if (!Number.isNaN(grid[r * cols + c])) continue;
        let sum = 0, n = 0;
        for (let dr = -1; dr <= 1; dr++) for (let dc = -1; dc <= 1; dc++) {
          const rr = r + dr, cc = c + dc;
          if (rr < 0 || cc < 0 || rr >= rows || cc >= cols) continue;
          const v = grid[rr * cols + cc];
          if (!Number.isNaN(v)) { sum += v; n++; }
        }
        if (n) padded[r * cols + c] = sum / n;
      }
    }
    const canvas = document.createElement("canvas");
    canvas.width = cols; canvas.height = rows;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(cols, rows);
    padded.forEach((v, i) => {
      if (Number.isNaN(v)) return;
      const [r, g, b] = rampRGB((v - lo) / (hi - lo));
      img.data.set([r, g, b, 255], 4 * i);
    });
    ctx.putImageData(img, 0, 0);
    const clipId = `heat-clip-${k}`;
    const clip = el("clipPath", { id: clipId }, defs);
    for (const room of state.plan.rooms) {
      if (zoneOf[room.room_id] === h.hub_id) el("path", { d: ringsPath(room.polygon), "fill-rule": "evenodd" }, clip);
    }
    const image = el("image", {
      href: canvas.toDataURL(), x: x0 - cell / 2, y: -y1 - cell / 2, width: cols * cell, height: rows * cell,
      preserveAspectRatio: "none", class: "heat-img", ...(clip.childNodes.length ? { "clip-path": `url(#${clipId})` } : {}),
    }, groups.heatmap);
    hoverable(image, () => {
      const at = state.lastPointer;
      if (!at) return [`${h.hub_id} hub cost`];
      let best = h.points[0];
      for (const p of h.points) if (dist(p, at) < dist(best, at)) best = p;
      return [`${h.hub_id} hub here: +${best[2].toFixed(2)} J`, "extra cost compared with the cheapest spot"];
    });
    el("circle", { cx: h.chosen[0], cy: -h.chosen[1], r: 0.42 * s, class: "heat-chosen" }, groups.heatmap);
  });
}

// ---------- hover box ----------
const hoverBox = $("hover");
function showHover(evt, lines) {
  hoverBox.replaceChildren(...lines.map((t, i) => (i === 0 ? html("strong", {}, t) : html("div", {}, t))));
  const wrap = loopSvg.parentElement.getBoundingClientRect();
  hoverBox.style.left = `${Math.max(8, Math.min(evt.clientX - wrap.left + 14, wrap.width - 240))}px`;
  hoverBox.style.top = `${Math.max(8, Math.min(evt.clientY - wrap.top + 14, wrap.height - 90))}px`;
  hoverBox.hidden = false;
}
function hideHover() { hoverBox.hidden = true; }
function hoverable(node, lines, onEnter, onLeave) {
  node.addEventListener("pointermove", (e) => {
    const svg = node.ownerSVGElement;
    if (svg) { const p = svgPoint(svg, e.clientX, e.clientY); state.lastPointer = [p.x, -p.y]; }
    showHover(e, typeof lines === "function" ? lines() : lines);
  });
  node.addEventListener("pointerenter", () => onEnter && onEnter());
  node.addEventListener("pointerleave", () => { hideHover(); onLeave && onLeave(); });
}

// ---------- drawing ----------
function drawBase(svg, groups, zoneOf, colorOf) {
  const { plan } = state;
  const s = plan.scale;
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
  for (const rings of plan.doors) hoverable(el("path", { d: ringsPath(rings), class: "door" }, groups.walls), ["Door", "cable may pass between rooms here"]);
  for (const rings of plan.front_door || []) hoverable(el("path", { d: ringsPath(rings), class: "front-door" }, groups.walls), ["Front door", "not a zone link"]);
}

function makeGroups(svg) {
  svg.replaceChildren();
  const groups = {};
  for (const name of ["zones", "heatmap", "passages", "walls", "labels", "rings", "numbers", "nodes", "violations", "cuts"]) {
    groups[name] = el("g", { "data-layer": name }, svg);
  }
  return groups;
}

function drawNode(groups, n, color, status, s) {
  const cls = status === "lost" ? "node lost" : status ? "node alive" : "node";
  const circle = el("circle", { cx: n.point[0], cy: -n.point[1], r: 0.16 * s, class: cls, stroke: color }, groups.nodes);
  const arrow = { fwd: " →", back: " ←", both: "", lost: " ✕" }[status] || "";
  const t = el("text", { x: n.point[0] + 0.24 * s, y: -n.point[1] - 0.22 * s, class: "node-label" + (status === "lost" ? " lost" : ""), "font-size": 0.3 * s }, groups.nodes);
  t.textContent = n.node_id + arrow;
  return circle;
}

function drawHub(groups, h, color, s) {
  const size = 0.42 * s;
  const r = el("rect", { x: h.point[0] - size / 2, y: -h.point[1] - size / 2, width: size, height: size, rx: 0.06 * s, fill: color, class: "hub" }, groups.nodes);
  const t = el("text", { x: h.point[0], y: -h.point[1] - 0.4 * s, class: "hub-label", fill: color, "font-size": 0.34 * s }, groups.nodes);
  t.textContent = h.hub_id;
  return r;
}

function drawCutMarks(groups, marks, s) {
  for (const q of marks) {
    const a = 0.2 * s;
    const g = el("g", { class: "cut" }, groups.cuts);
    el("circle", { cx: q[0], cy: -q[1], r: 0.32 * s, class: "cut-ring" }, g);
    el("path", { d: `M${q[0] - a},${-q[1] - a}L${q[0] + a},${-q[1] + a}M${q[0] - a},${-q[1] + a}L${q[0] + a},${-q[1] - a}`, class: "cut-x" }, g);
  }
}

function drawShortMarks(groups, marks, s) {
  for (const q of marks) {
    const g = el("g", { class: "short" }, groups.cuts);
    el("circle", { cx: q[0], cy: -q[1], r: 0.32 * s, class: "short-ring" }, g);
    const u = 0.1 * s;   // a lightning bolt
    el("path", { d: `M${q[0] + 0.4 * u},${-q[1] - 2 * u}L${q[0] - 1.2 * u},${-q[1] + 0.3 * u}L${q[0] - 0.1 * u},${-q[1] + 0.3 * u}L${q[0] - 0.5 * u},${-q[1] + 2 * u}L${q[0] + 1.3 * u},${-q[1] - 0.5 * u}L${q[0] + 0.2 * u},${-q[1] - 0.5 * u}Z`, class: "short-bolt" }, g);
  }
}

function drawIsolators(groups, spots, s) {
  for (const sp of spots) {
    const [x, y] = [sp.point[0], -sp.point[1]], r = 0.22 * s;
    const g = el("g", { class: "isolator" }, groups.cuts);
    el("path", { d: `M${x},${y - r}L${x + r},${y}L${x},${y + r}L${x - r},${y}Z`, class: "isolator-mark" }, g);
    hoverable(g, [`Isolator · ${sp.hub_id}`, "splits the loop: a short beyond it stops here"]);
  }
}

function drawFaultRooms(groups) {
  for (const f of roomFaults()) {
    const room = state.plan.rooms.find((r) => r.room_id === f.room_id);
    if (!room) continue;
    el("path", { d: ringsPath(room.polygon), class: "fault-room", "fill-rule": "evenodd" }, groups.cuts);  // listed in the panel
  }
}

function zoneColors() {
  const zoneOf = {}, colorOf = {}, hubOfNode = {};
  (state.answer?.hubs || []).forEach((h, k) => {
    colorOf[h.hub_id] = hubColor(k);
    h.room_ids.forEach((r) => (zoneOf[r] = h.hub_id));
    h.node_ids.forEach((n) => (hubOfNode[n] = h.hub_id));
  });
  return { zoneOf, colorOf, hubOfNode };
}

function nodePoints() {
  const { plan, answer } = state;
  return Object.fromEntries((plan.nodes.length ? plan.nodes : answer?.nodes || []).map((n) => [n.node_id, n]));
}

function drawLoopMap() {
  const { plan, answer, check } = state;
  const s = plan.scale;
  const groups = makeGroups(loopSvg);
  const { zoneOf, colorOf, hubOfNode } = zoneColors();
  drawBase(loopSvg, groups, zoneOf, colorOf);
  drawHeatmap(groups);
  const effects = state.breakMode ? loopEffects() : null;

  const legEls = [];
  (answer?.hubs || []).forEach((h) => {
    const c = colorOf[h.hub_id];
    h.legs.forEach((leg, i) => {
      const d = polyPath(leg.polyline);
      const line = el("path", { d, class: "leg", stroke: c }, groups.rings);
      const hit = el("path", { d, class: "leg hit" }, groups.rings);
      legEls.push(line);
      const len = legLength(leg.polyline, s);
      hoverable(hit, () => [
        `${h.hub_id} · leg ${i + 1} of ${h.legs.length}${i === h.legs.length - 1 ? " (return)" : ""}`,
        `${leg.from} → ${leg.to}`,
        `${len.toFixed(2)} m · ${legBends(leg.polyline)} bends inside the leg`,
        ...(state.breakMode ? ["Click to cut this cable"] : []),
      ], () => legEls.forEach((e) => e !== line && e.classList.add("dim")),
         () => legEls.forEach((e) => e.classList.remove("dim")));
      const [lx, ly] = labelPoint(leg.polyline);
      const g = el("g", { class: "leg-num" }, groups.numbers);
      el("circle", { cx: lx, cy: -ly, r: 0.2 * s, stroke: c }, g);
      const t = el("text", { x: lx, y: -ly, fill: c, "font-size": 0.22 * s }, g);
      t.textContent = String(i + 1);
    });
  });

  for (const [nid, n] of Object.entries(nodePoints())) {
    const hub = hubOfNode[nid];
    const status = effects ? effects.status[nid] : null;
    const circle = drawNode(groups, n, hub ? colorOf[hub] : "var(--quiet)", status, s);
    const how = { fwd: "signal arrives forward along the ring", back: "signal arrives backward along the ring",
                  both: "reached both ways", lost: "cut off: no path to the hub" }[status];
    hoverable(circle, [`Node ${nid}`, `room ${n.room_id}`, hub ? `served by ${hub}` : "not served by any hub", ...(how ? [how] : [])]);
  }
  (answer?.hubs || []).forEach((h) => {
    const r = drawHub(groups, h, colorOf[h.hub_id], s);
    hoverable(r, [`Hub ${h.hub_id}`, `in ${h.room_id}`, `${h.node_ids.length} nodes · ${h.area_m2.toFixed(1)} m²`, h.sequence.join(" → ")]);
    enableHubDrag(r, h);
  });

  if (!state.breakMode) {
    for (const v of check?.violations || []) {
      if (!v.location) continue;
      const [x, y] = v.location, a = 0.22 * s;
      const g = el("g", {}, groups.violations);
      el("circle", { cx: x, cy: -y, r: 0.45 * s, class: "violation-ring" }, g);
      el("path", { d: `M${x - a},${-y - a}L${x + a},${-y + a}M${x - a},${-y + a}L${x + a},${-y - a}`, class: "violation" }, g);
      hoverable(g, [`${v.rule}${v.hub_id ? " · " + v.hub_id : ""}`, v.message]);
    }
  }
  if (effects) {
    if (isolatorsShown()) drawFaultRooms(groups);
    drawCutMarks(groups, effects.marks, s);
    drawShortMarks(groups, effects.shortMarks, s);
    drawIsolators(groups, activeIsolators(), s);
  }
  applyLayers(loopSvg);
  return effects;
}

function drawTreeMap() {
  const { plan, answer } = state;
  const s = plan.scale;
  const groups = makeGroups(treeSvg);
  const { zoneOf, colorOf, hubOfNode } = zoneColors();
  drawBase(treeSvg, groups, zoneOf, colorOf);
  const effects = treeEffects();
  for (const t of state.treeModels) {
    const c = colorOf[t.hub_id] || "var(--quiet)";
    for (const p of t.paths) {
      const line = el("path", { d: polyPath(p.poly), class: "leg tree", stroke: c }, groups.rings);
      hoverable(line, [`${t.hub_id} branch to ${p.node}`, `${legLength(p.poly, s).toFixed(2)} m`, "Click to cut this cable"]);
    }
  }
  for (const [nid, n] of Object.entries(nodePoints())) {
    const hub = hubOfNode[nid];
    const status = effects.status[nid] === "lost" ? "lost" : effects.status[nid] ? "both" : null;
    const circle = drawNode(groups, n, hub ? colorOf[hub] : "var(--quiet)", status, s);
    hoverable(circle, [`Node ${nid}`, status === "lost" ? "cut off: the branch to it is broken" : "connected"]);
  }
  for (const h of answer?.hubs || []) drawHub(groups, h, colorOf[h.hub_id], s);
  drawCutMarks(groups, effects.marks, s);
  drawShortMarks(groups, effects.shortMarks, s);
  applyLayers(treeSvg);
  return effects;
}

function drawAll() {
  const loop = drawLoopMap();
  let tree = null;
  if (state.breakMode && state.treeModels.length) tree = drawTreeMap();
  breakPanel(loop, tree);
  syncRail();
  window.view3d?.refresh();  // the 3D view (view3d.js) redraws from the same state
}

// ---------- side panel ----------
function panel() {
  const { plan, answer, check } = state;
  const title = html("div", { class: "verdict-title" }, plan.plan_id != null ? `Plan ${plan.plan_id}` : "Plan");
  let badge;
  if (!answer) badge = html("span", { class: "badge" }, "Not solved yet");
  else if (!check) badge = html("span", { class: "badge" }, "Not checked");
  else if (check.valid) badge = html("span", { class: "badge good" }, "Valid");
  else badge = html("span", { class: "badge bad" }, `${check.violations.length} rule violation${check.violations.length === 1 ? "" : "s"}`);
  $("verdict").replaceChildren(title, badge,
    ...(!answer && state.api ? [html("p", { class: "help" }, "Press Solve to place the hubs and route the cables.")] : []));

  const m = check?.metrics && Object.keys(check.metrics).length ? check.metrics : answer?.metrics || {};
  $("score-section").hidden = !answer;
  if (answer) scoreCard(m, answer);

  $("paths-section").hidden = !answer;
  $("hubs").replaceChildren(...(answer?.hubs || []).map((h, k) => {
    const li = html("li", { tabindex: "0", title: "Show this hub on the plan" });
    const head = html("div", { class: "hub-head" });
    const sw = html("span", { class: "swatch" });
    sw.style.background = hubColor(k);
    head.append(sw, html("b", {}, h.hub_id),
      html("span", { class: "hub-facts" }, `${h.node_ids.length} device${h.node_ids.length === 1 ? "" : "s"} · ${h.area_m2.toFixed(1)} m²`));
    const chain = html("div", { class: "chain" });
    h.sequence.forEach((id, i) => {
      if (i) chain.append(html("span", { class: "arrow", "aria-hidden": "true" }, "→"));
      const tok = html("span", { class: id === h.hub_id ? "tok hub-tok" : "tok" }, id);
      if (id === h.hub_id) tok.style.background = hubColor(k);
      chain.append(tok);
    });
    li.append(head, chain);
    li.addEventListener("click", () => focusHub(h));
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") focusHub(h); });
    return li;
  }));

  const viol = check?.violations || [];
  $("violations-section").hidden = viol.length === 0;
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
    box.addEventListener("change", () => { state.layers[key] = box.checked; maps.forEach(applyLayers); });
    lab.append(box, document.createTextNode(label));
    return lab;
  }));
  $("break-section").hidden = !answer;
  heatPanel();
  tradeoffPanel();
  movePanel();
}

// The score card: hubs and J up top, the four cable terms below, and the formula with this answer's numbers.
function scoreCard(m, answer) {
  const stat = (label, value, unit, cls = "") => {
    const d = html("div", { class: `metric ${cls}` });
    const v = html("div", { class: "metric-value" }, value);
    if (unit) v.append(html("span", { class: "unit" }, unit));
    d.append(html("div", { class: "metric-label" }, label), v);
    return d;
  };
  const num = (x) => (typeof x === "number" ? x.toFixed(2) : "–");
  $("score").replaceChildren(
    stat("Hubs", String(m.H ?? answer.hubs.length), "", "big"),
    stat("Total cost J", num(m.J), "", "big accent"),
    stat("Cable length L", num(m.L), " m"),
    stat("Crossings X", String(m.X ?? "–")),
    stat("Overlap O", num(m.O), " m"),
    stat("Bends B", String(m.B ?? "–")),
  );
  const v = (s) => html("var", {}, s);
  const line = (...parts) => {
    const d = html("div", { class: "eq" });
    d.append(...parts.map((p) => (typeof p === "string" ? document.createTextNode(p) : p)));
    return d;
  };
  $("formula").replaceChildren(
    line(v("J"), " = ", v("L"), " + 5", v("X"), " + ", v("O"), " + 0.5", v("B")),
    line(html("span", { class: "eq-pad" }), "= ", num(m.L), " + 5 × ", String(m.X ?? "–"), " + ", num(m.O), " + 0.5 × ", String(m.B ?? "–")),
    line(html("span", { class: "eq-pad" }), "= ", html("b", {}, num(m.J))),
  );
}

function heatPanel() {
  const hms = state.heatmaps || [];
  const sec = $("heat-section");
  sec.hidden = !hms.length;
  if (!hms.length) return;
  const { lo, hi } = heatRange(hms);
  $("heat-bar").style.background = `linear-gradient(to right, ${RAMP.join(", ")})`;
  $("heat-lo").textContent = `+${lo.toFixed(2)} J`;
  $("heat-hi").textContent = `+${hi.toFixed(2)} J or more`;
  const box = $("heat-toggle");
  box.checked = state.layers.heatmap;
  $("heat-body").hidden = !box.checked;
  box.onchange = () => { state.layers.heatmap = box.checked; maps.forEach(applyLayers); heatPanel(); };
  $("heat-checks").replaceChildren(...hms.map((h) => {
    const c = heatCheck(h, state.plan.scale);
    const li = html("li", { class: c.ok ? "ok" : "bad", tabindex: "0", title: "Show this hub on the plan" },
      c.ok ? `${h.hub_id} sits at its cheapest spot` : `${h.hub_id}: a cheaper spot exists`);
    const hub = (state.answer?.hubs || []).find((x) => x.hub_id === h.hub_id);
    const go = () => (hub ? focusHub(hub) : zoomTo(h.chosen, 6 * state.plan.scale));
    li.addEventListener("click", go);
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    return li;
  }));
}

function breakPanel(loop, tree) {
  const btn = $("break-toggle");
  btn.textContent = state.breakMode ? "Done" : "Break the cable";
  btn.classList.toggle("active", state.breakMode);
  const hasTree = state.treeModels.length > 0;
  $("break-help").textContent = state.breakMode
    ? (state.faultMode === "short"
      ? `Click a cable to short it: every device on the same stretch of loop is lost. Click the mark again to remove it.${hasTree ? " Each short is made on both layouts." : ""}`
      : `Click a cable to cut it; click the cut again to repair it.${hasTree ? " Each cut is made on both layouts." : ""}`)
    : "A closed loop keeps every device connected when one cable is cut. Try it.";
  $("break-reset").hidden = !state.breakMode || !(state.cuts.length || state.shorts.length);
  faultPanel();
  document.querySelector(".canvas-wrap").classList.toggle("split", state.breakMode && hasTree);
  $("map-loop-title").hidden = !state.breakMode;
  $("map-tree-title").hidden = !(state.breakMode && hasTree);
  const stats = $("break-stats");
  if (!state.breakMode) { stats.replaceChildren(); return; }
  const total = Object.keys(loop.status).length;
  const lostLoop = Object.values(loop.status).filter((x) => x === "lost").length;
  const lostTree = tree ? Object.values(tree.status).filter((x) => x === "lost").length : null;
  $("map-loop-title").textContent = `Our closed loop · ${lostLoop} of ${total} devices lost`;
  $("map-loop-title").classList.toggle("bad", lostLoop > 0);
  if (tree) {
    $("map-tree-title").textContent = `Branching layout · ${lostTree} of ${total} devices lost`;
    $("map-tree-title").classList.toggle("bad", lostTree > 0);
  }
  const box = (label, lost) => {
    const d = html("div", { class: `lost-box ${lost ? "bad" : "good"}` });
    d.append(html("div", { class: "metric-label" }, label), html("div", { class: "metric-value" }, `${lost} of ${total}`),
      html("div", { class: "metric-label" }, "devices lost"));
    return d;
  };
  stats.replaceChildren(box("Our loop", lostLoop), ...(tree ? [box("Branching", lostTree)] : []));
}

// Cut | Short switch, the isolator controls and their results (V2 feature 1). Only shown in break mode.
function faultPanel() {
  const tools = $("fault-tools");
  tools.hidden = !state.breakMode;
  if (!state.breakMode) return;
  const short = state.faultMode === "short";
  $("fault-cut").classList.toggle("on", !short);
  $("fault-short").classList.toggle("on", short);
  $("fault-cut").setAttribute("aria-pressed", String(!short));
  $("fault-short").setAttribute("aria-pressed", String(short));
  $("iso-tools").hidden = !short;
  if (!short) return;
  $("iso-k").textContent = String(state.isoK);
  $("iso-on").checked = state.isoOn;
  $("iso-minus").disabled = state.isoK <= 1;
  $("iso-plus").disabled = state.isoK >= 5;
  const models = state.loopModels;
  const devices = models.map((m) => m.stops.length);
  const row = (cells, tag = "td") => { const tr = html("tr"); cells.forEach((c) => tr.append(html(tag, {}, String(c)))); return tr; };
  const ks = [1, 2, 3, 4, 5];
  const table = html("table", { class: "iso-grid" });
  table.append(row(["Devices lost per short at most", ...ks], "th"), row(["Isolators needed", ...ks.map((k) => isolatorSpots(models, k).length)]));
  $("iso-table").replaceChildren(table);
  const withoutIso = Math.max(0, ...devices);
  const spots = isolatorSpots(models, state.isoK);
  const result = html("div", { class: "iso-box" });
  result.append(html("div", {}, `Without isolators: a short loses up to ${withoutIso} device${withoutIso === 1 ? "" : "s"}`));
  result.append(html("div", { class: state.isoOn ? "good" : "" },
    state.isoOn
      ? `With ${spots.length} isolator${spots.length === 1 ? "" : "s"}: at most ${worstShort(models, spots)} lost`
      : `Switch on Place isolators to cap it at ${state.isoK} (needs ${spots.length})`));
  $("iso-result").replaceChildren(result);
  const faults = roomFaults();
  $("room-faults").replaceChildren(...(faults.length ? [
    html("div", { class: "metric-label" }, "Room fault risk"),
    ...faults.map((f) => {
      const room = state.plan.rooms.find((r) => r.room_id === f.room_id);
      return html("div", { class: "fault-line" }, `${room ? room.type : f.room_id}: ${f.segments} segments of ${f.hub_id} pass through it, so one fire or leak there can take out several at once`);
    }),
  ] : []));
}

function fmt(v, unit = "") { return typeof v === "number" ? v.toFixed(2) + unit : "–"; }

function applyLayers(svg) {
  svg.querySelectorAll("g[data-layer]").forEach((g) => {
    const key = g.dataset.layer;
    g.style.display = key === "cuts" || state.layers[key] ? "" : "none";
  });
}

// ---------- pan, zoom and clicks (both maps share one view) ----------
function setView(v) {
  state.view = v;
  for (const svg of maps) svg.setAttribute("viewBox", `${v.x} ${v.y} ${v.w} ${v.h}`);
}
function fit() {
  const [minx, miny, maxx, maxy] = state.plan.bounds;
  state.base = { x: minx, y: -maxy, w: maxx - minx, h: maxy - miny };
  setView({ ...state.base });
}
function svgPoint(svg, clientX, clientY) {
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
// Centre the view on `loc` (plan coordinates), `width` plan units wide. The visible box takes the map's own
// aspect ratio so the point lands in the middle of what is on screen; the move is animated.
function zoomTo(loc, width) {
  const box = loopSvg.getBoundingClientRect();
  const aspect = box.width && box.height ? box.height / box.width : state.base.h / state.base.w;
  const target = { x: loc[0] - width / 2, y: -loc[1] - (width * aspect) / 2, w: width, h: width * aspect };
  const from = { ...state.view };
  const t0 = performance.now();
  cancelAnimationFrame(zoomTo.raf);
  const step = (now) => {
    const t = Math.min(1, (now - t0) / 350);
    const e = 1 - Math.pow(1 - t, 3);
    setView(Object.fromEntries(Object.keys(target).map((k) => [k, from[k] + (target[k] - from[k]) * e])));
    if (t < 1) zoomTo.raf = requestAnimationFrame(step);
  };
  zoomTo.raf = requestAnimationFrame(step);
}

// Pan to a hub, framing its zone, and pulse a ring around it so the eye finds it.
function focusHub(h) {
  const s = state.plan.scale;
  const zone = state.plan.rooms.filter((r) => h.room_ids.includes(r.room_id)).flatMap((r) => r.polygon.flat());
  const xs = zone.map((p) => p[0]), ys = zone.map((p) => p[1]);
  const span = xs.length ? Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) : 0;
  zoomTo(h.point, Math.max(6 * s, 1.4 * span));
  const layer = loopSvg.querySelector('g[data-layer="nodes"]');
  if (!layer) return;
  const ring = el("circle", { cx: h.point[0], cy: -h.point[1], r: 0.6 * s, class: "hub-pulse" }, layer);
  setTimeout(() => ring.remove(), 1800);
}

// A click near an existing cut repairs it; anywhere else on a cable cuts it.
const faultList = () => (state.faultMode === "short" ? state.shorts : state.cuts);

function handleCut(svg, e) {
  const p = svgPoint(svg, e.clientX, e.clientY);
  const at = [p.x, -p.y];
  const s = state.plan.scale;
  const list = faultList();
  const hit = list.findIndex((c) => dist(c, at) <= 0.6 * s);
  if (hit >= 0) {
    list.splice(hit, 1);
    drawAll();
    return;
  }
  const near = svg === treeSvg ? nearestTreeSeg(state.treeModels, at) : nearestRingSeg(state.loopModels, at);
  if (!near || near.d > 0.4 * s) return;
  list.push(near.q);
  drawAll();
}

for (const svg of maps) {
  svg.addEventListener("wheel", (e) => {
    if (!state.view) return;
    e.preventDefault();
    const p = svgPoint(svg, e.clientX, e.clientY);
    zoomAt(p.x, p.y, e.deltaY > 0 ? 1.15 : 1 / 1.15);
  }, { passive: false });
  let drag = null;
  svg.addEventListener("pointerdown", (e) => {
    if (!state.view) return;
    drag = { x: e.clientX, y: e.clientY, view: { ...state.view }, moved: false };
    svg.setPointerCapture(e.pointerId);
  });
  svg.addEventListener("pointermove", (e) => {
    if (!drag) return;
    if (Math.abs(e.clientX - drag.x) + Math.abs(e.clientY - drag.y) > 4) {
      drag.moved = true;
      svg.classList.add("dragging");
    }
    if (!drag.moved) return;
    const kk = Math.max(drag.view.w / svg.clientWidth, drag.view.h / svg.clientHeight);
    setView({ ...drag.view, x: drag.view.x - (e.clientX - drag.x) * kk, y: drag.view.y - (e.clientY - drag.y) * kk });
  });
  svg.addEventListener("pointerup", (e) => {
    const wasClick = drag && !drag.moved;
    drag = null;
    svg.classList.remove("dragging");
    if (wasClick && state.breakMode) handleCut(svg, e);
  });
  svg.addEventListener("pointercancel", () => { drag = null; svg.classList.remove("dragging"); });
}
$("zoom-in").addEventListener("click", () => { const v = state.view; zoomAt(v.x + v.w / 2, v.y + v.h / 2, 1 / 1.4); });
$("zoom-out").addEventListener("click", () => { const v = state.view; zoomAt(v.x + v.w / 2, v.y + v.h / 2, 1.4); });
$("zoom-reset").addEventListener("click", fit);
$("break-toggle").addEventListener("click", () => {
  state.breakMode = !state.breakMode;
  state.cuts = [];
  state.shorts = [];
  state.faultMode = "cut";
  drawAll();
});
$("break-reset").addEventListener("click", () => { state.cuts = []; state.shorts = []; drawAll(); });
$("fault-cut").addEventListener("click", () => { state.faultMode = "cut"; drawAll(); });
$("fault-short").addEventListener("click", () => { state.faultMode = "short"; drawAll(); });
$("iso-minus").addEventListener("click", () => { state.isoK = Math.max(1, state.isoK - 1); drawAll(); });
$("iso-plus").addEventListener("click", () => { state.isoK = Math.min(5, state.isoK + 1); drawAll(); });
$("iso-on").addEventListener("change", (e) => { state.isoOn = e.target.checked; drawAll(); });

// ---------- API (served by `python -m eightball serve`) ----------
async function detectApi() {
  try {
    const res = await fetch("api/health", { cache: "no-store" });
    if (!res.ok) return;
    state.api = await res.json();
  } catch {
    return;
  }
  $("api-controls").hidden = false;
  $("api-status").textContent = state.api.solver === "ready" ? "" : "Solver unavailable";  // only worth saying when it's down
}

function flash(text) {
  setStatus(text);
  clearTimeout(flash.timer);
  flash.timer = setTimeout(() => setStatus(""), 5000);
}

function useResult(plan, extra = {}) {
  Object.assign(state, { plan, answer: null, check: null, branching: null, heatmaps: null, breakMode: false, cuts: [], shorts: [], faultMode: "cut",
    tradeoff: null, baseAnswer: null, moveInfo: null, solveExtras: null }, extra);
  state.tradeoffToken = (state.tradeoffToken || 0) + 1;   // an answer for the previous plan must not land on this one
  state.loopModels = (state.answer?.hubs || []).map(ringModel);
  state.treeModels = treeModel(state.branching);
  fit();
  panel();
  drawAll();
  downloadPanel();
}

async function loadFromApi(id) {
  setStatus(`Loading plan ${id}…`);
  const res = await fetch(`api/plan/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!res.ok) return flash(`Plan ${id}: ${(await res.json()).detail}`);
  useResult(await res.json());
  state.bundle = `api:${id}`;
  setStatus("");
  const url = new URL(location.href);
  url.searchParams.delete("plan");
  url.searchParams.set("id", id);
  history.replaceState(null, "", url);
}

async function solveViaApi() {
  if (!state.plan) return;
  if (state.bundle === "upload" && state.upload) return solveUpload(state.upload, state.uploadName || "uploaded plan");
  const id = state.plan.plan_id;
  const btn = $("solve");
  btn.disabled = true;
  setStatus(`Solving plan ${id}…`);
  try {
    const res = await fetch("api/solve", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: id, nodes: state.plan.nodes.length ? state.plan.nodes : null, solver: "exact" }),
    });
    const data = await res.json();
    if (!res.ok) return flash(`Can't solve: ${data.detail}`);
    useResult(data.plan, {
      answer: data.answer, check: data.check, savedTo: data.saved_to,
      branching: data.branching?.hubs?.length ? data.branching : null,
      heatmaps: data.heatmaps?.length ? data.heatmaps : null,
    });
    state.solveExtras = { branching: state.branching, heatmaps: state.heatmaps };
    flash(`Solved in ${data.runtime_s.toFixed(2)} s`);
    requestTradeoff();   // the trade-off options appear when the server has them (does not hold up the solve)
  } finally {
    btn.disabled = false;
  }
}

// ---------- download the result ----------
function saveBlob(name, blob) {
  const url = URL.createObjectURL(blob);
  const a = html("a", { href: url, download: name });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function downloadJSON(name, data) {
  saveBlob(name, new Blob([JSON.stringify(data, null, 1)], { type: "application/json" }));
}

function downloadPanel() {
  const section = $("download-section");
  section.hidden = !state.answer;
  if (!state.answer) return;
}

async function downloadOverlay(format) {
  const btn = $(`dl-overlay-${format}`);
  btn.disabled = true;
  try {
    const body = { answer: state.answer, format };
    if (state.bundle === "upload" && state.upload) {
      body.plan = state.upload.plan;
      body.nodes = state.upload.nodes;
    } else {
      body.plan_id = state.plan.plan_id;
    }
    const res = await fetch("api/overlay", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) return flash(`Can't make the overlay: ${(await res.json().catch(() => ({}))).detail || res.status}`);
    saveBlob(`overlay_${state.plan.plan_id}.${format}`, await res.blob());
  } finally {
    btn.disabled = false;
  }
}

$("dl-answer").addEventListener("click", () => downloadJSON(`answer_${state.plan.plan_id}.json`, state.answer));
$("dl-all").addEventListener("click", () => downloadJSON(`result_${state.plan.plan_id}.json`, {
  answer: state.answer, check: state.check, heatmaps: state.heatmaps || [], branching: state.branching || {},
  isolators: {  // V2 feature 1: where the isolators go for the "devices lost per short" setting chosen in the viewer
    max_lost: state.isoK,
    placed: isolatorSpots(state.loopModels, state.isoK).map(({ hub_id, leg_index, point }) => ({ hub_id, leg_index, point })),
  },
}));
$("dl-overlay-svg").addEventListener("click", () => downloadOverlay("svg"));
$("dl-overlay-png").addEventListener("click", () => downloadOverlay("png"));

// ---------- upload a floor plan ----------
// Accepts the body of POST api/solve ({"plan": {...}, "nodes": [...]}) or a bare plan; without nodes the server
// makes practice nodes (centre of each room).
function uploadBody(data) {
  const plan = data.plan && typeof data.plan === "object" ? data.plan : data;
  const body = { plan, solver: "exact" };
  if (Array.isArray(data.nodes) && data.nodes.length) body.nodes = data.nodes;
  return body;
}

async function solveUpload(body, name) {
  const buttons = [$("solve"), $("upload-btn")];
  buttons.forEach((b) => (b.disabled = true));
  setStatus(`Solving ${name}…`);
  try {
    const res = await fetch("api/solve", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const why = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data);
      return flash(`Can't solve ${name}: ${why}`);
    }
    state.upload = body;
    state.uploadName = name;
    useResult(data.plan, {
      answer: data.answer, check: data.check, savedTo: data.saved_to,
      branching: data.branching?.hubs?.length ? data.branching : null,
      heatmaps: data.heatmaps?.length ? data.heatmaps : null,
    });
    state.bundle = "upload";
    state.solveExtras = { branching: state.branching, heatmaps: state.heatmaps };
    flash(`Solved ${name} in ${data.runtime_s.toFixed(2)} s`);
    requestTradeoff();
  } catch (err) {
    flash(`Can't reach the solver: ${err.message}`);
  } finally {
    buttons.forEach((b) => (b.disabled = false));
  }
}

async function handleUploadedFile(file) {
  if (!file) return;
  let data;
  try {
    data = JSON.parse(await file.text());
  } catch {
    return flash(`${file.name} is not a JSON file`);
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) return flash(`${file.name}: expected a JSON object with a floor plan`);
  await solveUpload(uploadBody(data), file.name);
}

$("upload-btn").addEventListener("click", () => $("upload-file").click());
$("upload-file").addEventListener("change", (e) => { handleUploadedFile(e.target.files[0]); e.target.value = ""; });
let dragDepth = 0;
window.addEventListener("dragenter", (e) => { if (state.api && e.dataTransfer?.types?.includes("Files")) { dragDepth++; document.body.classList.add("drop-target"); } });
window.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) document.body.classList.remove("drop-target"); });
window.addEventListener("dragover", (e) => { if (state.api) e.preventDefault(); });
window.addEventListener("drop", (e) => {
  dragDepth = 0;
  document.body.classList.remove("drop-target");
  if (!state.api) return;
  e.preventDefault();
  handleUploadedFile(e.dataTransfer?.files?.[0]);
});

$("load-id").addEventListener("click", () => { const v = $("plan-id").value.trim(); if (v) loadFromApi(v); });
$("plan-id").addEventListener("keydown", (e) => { if (e.key === "Enter") $("load-id").click(); });
$("solve").addEventListener("click", solveViaApi);

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
  st.replaceChildren(...(text ? [html("span", { class: "pill" }, text)] : []));
}

async function loadBundle(path, entry) {
  setStatus("Loading…");
  try {
    const want = (flag) => !entry || entry[flag] !== false;
    const [plan, answer, check, branching, heatmaps] = await Promise.all([
      getJSON(`${path}/plan.json`), getJSON(`${path}/answer.json`, true), getJSON(`${path}/check.json`, true),
      want("has_branching") ? getJSON(`${path}/branching.json`, true) : null,
      want("has_heatmap") ? getJSON(`${path}/heatmaps.json`, true) : null,
    ]);
    Object.assign(state, { bundle: path, plan, answer, check, branching, heatmaps, breakMode: false, cuts: [], shorts: [], faultMode: "cut", tradeoff: null, baseAnswer: null, moveInfo: null, solveExtras: null });
    state.tradeoffToken = (state.tradeoffToken || 0) + 1;
    state.loopModels = (answer?.hubs || []).map(ringModel);
    state.treeModels = treeModel(branching);
    fit();
    panel();
    drawAll();
    setStatus("");
    const url = new URL(location.href);
    url.searchParams.set("plan", path);
    history.replaceState(null, "", url);
  } catch (err) {
    setStatus(`Couldn't load ${path}: ${err.message}`);
  }
}

// Opens the plan named in the URL (?plan=bundle from the gallery, ?id= with the API), else the first gallery plan.
async function init() {
  await detectApi();
  const index = (await getJSON("data/plans/index.json", true)) || { plans: [] };
  const gallery = (await getJSON("data/gallery/index.json", true)) || { plans: [] };
  const params = new URL(location.href).searchParams;
  const wanted = params.get("plan");
  const wantedId = params.get("id");
  const entries = [...gallery.plans, ...index.plans];
  const byPath = Object.fromEntries(entries.map((e) => [e.path, e]));
  if (state.api && wantedId) {
    $("plan-id").value = wantedId;
    return loadFromApi(wantedId);
  }
  const first = wanted || entries[0]?.path;
  if (!first) return setStatus(state.api ? "Enter a plan ID or upload a plan to start." : "No plans found: open one from the Gallery.");
  loadBundle(first, byPath[first]);
}

// ---------- what the API needs to know about the plan on screen ----------
function planRequest() {
  if (state.bundle === "upload" && state.upload) return { plan: state.upload.plan, nodes: state.upload.nodes };
  return { plan_id: state.plan.plan_id, nodes: state.plan.nodes?.length ? state.plan.nodes : null };
}

const currentJ = () => state.check?.metrics?.J ?? state.answer?.metrics?.J ?? 0;
const sgn = (x, d = 2) => `${x >= 0 ? "+" : "−"}${Math.abs(x).toFixed(d)}`;

function refreshAnswerViews() {
  state.loopModels = (state.answer?.hubs || []).map(ringModel);
  state.treeModels = treeModel(state.branching);
  panel();
  drawAll();
  downloadPanel();
}

// ---------- trade-off: hubs vs cost (V2 feature 2; POST api/tradeoff) ----------
// After a solve the server prices the best layout for the default hub count and a few more. Choosing an option
// redraws the plan with that layout; the default option is the normal solve (its heatmaps and branching come back).
async function requestTradeoff() {
  if (!state.api || !state.answer) return tradeoffPanel();
  const token = (state.tradeoffToken = (state.tradeoffToken || 0) + 1);
  state.tradeoff = { status: "loading" };
  tradeoffPanel();
  let next;
  try {
    const res = await fetch("api/tradeoff", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...planRequest(), answer: state.answer }),
    });
    const data = await res.json().catch(() => ({}));
    next = res.ok
      ? { status: "ready", options: data.options, default_hubs: data.default_hubs, selected: data.default_hubs, notes: data.notes || [] }
      : { status: "error", why: typeof data.detail === "string" ? data.detail : `HTTP ${res.status}` };
  } catch (err) {
    next = { status: "error", why: err.message };
  }
  if (token !== state.tradeoffToken) return;   // another plan or solve came in meanwhile
  state.tradeoff = next;
  tradeoffPanel();
}

function selectTradeoff(hubs) {
  const t = state.tradeoff;
  const opt = t?.status === "ready" ? t.options.find((o) => o.hubs === hubs) : null;
  if (!opt) return;
  t.selected = hubs;
  const isDefault = hubs === t.default_hubs;
  Object.assign(state, {
    answer: opt.answer, check: opt.check,
    branching: isDefault ? state.solveExtras?.branching ?? null : null,   // only the default layout has these
    heatmaps: isDefault ? state.solveExtras?.heatmaps ?? null : null,
    breakMode: false, cuts: [], shorts: [], faultMode: "cut", baseAnswer: null, moveInfo: null,
  });
  refreshAnswerViews();
}

function tradeoffPanel() {
  const t = state.tradeoff;
  const sec = $("tradeoff-section");
  sec.hidden = !t;
  if (!t) return;
  const body = $("tradeoff-body");
  if (t.status === "loading") return body.replaceChildren(html("p", { class: "help" }, "Working out the best layout for more hubs…"));
  if (t.status === "error") return body.replaceChildren(html("p", { class: "help" }, `Trade-off unavailable: ${t.why}`));
  const opts = t.options;
  const row = html("div", { class: "tradeoff-opts", role: "group", "aria-label": "Number of hubs" });
  for (const o of opts) {
    const b = html("button", { type: "button", class: `opt${o.hubs === t.selected ? " on" : ""}${o.valid ? "" : " invalid"}`,
      title: o.valid ? `${o.hubs} hubs: J ${o.J.toFixed(2)}, cable ${o.L.toFixed(1)} m` : "this layout breaks a rule" });
    b.append(html("b", {}, `${o.hubs} hub${o.hubs === 1 ? "" : "s"}`), html("span", {}, `J ${o.J.toFixed(1)}`));
    b.addEventListener("click", () => selectTradeoff(o.hubs));
    row.append(b);
  }
  const nodes = [row];
  if (opts.length > 1) nodes.push(tradeoffChart(opts, t));
  const base = opts.find((o) => o.hubs === t.default_hubs);
  const others = opts.filter((o) => o.hubs > t.default_hubs && o.valid);
  const best = others.reduce((a, o) => (!a || o.J < a.J ? o : a), null);
  const note = html("div", { class: "tradeoff-note" });
  if (!base || !others.length) note.textContent = "The fewest hubs is the only option for this plan.";
  else if (best.J < base.J - 0.05) {
    const next = others.find((o) => o.hubs === t.default_hubs + 1);
    const save = base.J - best.J;
    const who = next && next.J <= best.J + 1e-9 ? "One more hub" : `${best.hubs - t.default_hubs} more hubs`;
    note.textContent = `${who} saves ${save.toFixed(1)} J (${Math.round((100 * save) / base.J)}%)`;
    note.classList.add("good");
  } else note.textContent = "No saving from more hubs.";
  nodes.push(note);
  if (state.moveInfo) nodes.push(html("p", { class: "help" }, "Choosing a layout replaces any hub you moved."));
  body.replaceChildren(...nodes);
}

function tradeoffChart(opts, t) {
  const W = 260, H = 96, padL = 26, padR = 12, padT = 12, padB = 22;
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, class: "tradeoff-chart", role: "img", "aria-label": "Total cost J for each number of hubs" });
  const hs = opts.map((o) => o.hubs), js = opts.map((o) => o.J);
  const [h0, h1] = [Math.min(...hs), Math.max(...hs)];
  const j1 = Math.max(...js), j0 = Math.min(0, ...js);
  const x = (h) => padL + ((h - h0) / Math.max(1, h1 - h0)) * (W - padL - padR);
  const y = (j) => padT + (1 - (j - j0) / Math.max(1e-9, j1 - j0)) * (H - padT - padB);
  el("line", { x1: padL, y1: H - padB, x2: W - padR, y2: H - padB, class: "axis" }, svg);
  el("line", { x1: padL, y1: padT, x2: padL, y2: H - padB, class: "axis" }, svg);
  el("path", { d: "M" + opts.map((o) => `${x(o.hubs)},${y(o.J)}`).join("L"), class: "line" }, svg);
  for (const o of opts) {
    const c = el("circle", { cx: x(o.hubs), cy: y(o.J), r: 5, class: `pt${o.hubs === t.selected ? " on" : ""}` }, svg);
    c.addEventListener("click", () => selectTradeoff(o.hubs));
    const tip = el("title", {}, c);
    tip.textContent = `${o.hubs} hubs · J ${o.J.toFixed(2)}`;
    el("text", { x: x(o.hubs), y: H - 8 }, svg).textContent = String(o.hubs);
  }
  el("text", { x: padL - 4, y: padT + 3, "text-anchor": "end" }, svg).textContent = j1.toFixed(0);
  el("text", { x: padL - 4, y: H - padB, "text-anchor": "end" }, svg).textContent = j0.toFixed(0);
  return svg;
}

// ---------- drag the hub, live (V2 feature 3; POST api/move_hub) ----------
// Legal hub spots are the heatmap points of the hub's zone. While dragging, the hub's ghost snaps to the nearest one and a
// label shows J + (extra at that spot - extra here), straight from the heatmap. On drop the server re-wires the ring
// there (around its own cable where needed) and returns the true answer, which can differ a little from the estimate.
const hubDraggable = (h) => !!state.api && !state.breakMode && !state.dragBusy && !!state.heatmaps?.some((m) => m.hub_id === h.hub_id && m.points.length > 1);

function heatValueAt(hm, p, tol) {
  let best = null;
  for (const q of hm.points) {
    const d = dist(q, p);
    if (d <= tol && (!best || d < best.d)) best = { d, v: q[2] };
  }
  return best ? best.v : 0;
}

function enableHubDrag(rect, hub) {
  if (!hubDraggable(hub)) return;
  rect.classList.add("draggable");
  rect.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.stopPropagation();   // not a pan of the map
    e.preventDefault();
    beginHubDrag(rect, hub, e);
  });
}

function beginHubDrag(rect, hub, e) {
  const hm = state.heatmaps.find((m) => m.hub_id === hub.hub_id);
  const s = state.plan.scale;
  const label = $("drag-label");
  const cur = heatValueAt(hm, hub.point, 1e-6 * s);
  const J0 = currentJ();
  const wasOn = state.layers.heatmap;
  const start = { x: e.clientX, y: e.clientY };
  let ghost = null, target = null, moved = false;
  rect.setPointerCapture(e.pointerId);

  const finish = () => {
    rect.removeEventListener("pointermove", move);
    rect.removeEventListener("pointerup", up);
    rect.removeEventListener("pointercancel", cancel);
    ghost?.remove();
    label.hidden = true;
    if (moved && !wasOn) { state.layers.heatmap = false; maps.forEach(applyLayers); heatPanel(); }
  };
  const move = (ev) => {
    if (!moved) {
      if (Math.abs(ev.clientX - start.x) + Math.abs(ev.clientY - start.y) < 5) return;
      moved = true;
      hideHover();
      if (!state.layers.heatmap) { state.layers.heatmap = true; maps.forEach(applyLayers); heatPanel(); }   // show the cost of every spot
      const size = 0.42 * s;
      ghost = el("rect", { width: size, height: size, rx: 0.06 * s, class: "hub-ghost" }, loopSvg);
    }
    const p = svgPoint(loopSvg, ev.clientX, ev.clientY);
    const at = [p.x, -p.y];
    let best = hm.points[0];
    for (const q of hm.points) if (dist(q, at) < dist(best, at)) best = q;
    target = best;
    const size = 0.42 * s;
    ghost.setAttribute("x", best[0] - size / 2);
    ghost.setAttribute("y", -best[1] - size / 2);
    const delta = best[2] - cur;
    label.textContent = `J ${J0.toFixed(2)} → ≈ ${(J0 + delta).toFixed(2)} (${sgn(delta)})`;   // an estimate: the drop re-wires the ring and returns the true J
    label.classList.toggle("worse", delta > 0.005);
    label.classList.toggle("better", delta < -0.005);
    const wrap = loopSvg.parentElement.getBoundingClientRect();
    label.style.left = `${Math.max(8, Math.min(ev.clientX - wrap.left + 16, wrap.width - 190))}px`;
    label.style.top = `${Math.max(8, Math.min(ev.clientY - wrap.top - 36, wrap.height - 40))}px`;
    label.hidden = false;
  };
  const up = () => {
    const drop = moved && target && dist(target, hub.point) > 1e-6 * s ? target : null;
    finish();
    if (drop) moveHub(hub.hub_id, [drop[0], drop[1]], J0 + (drop[2] - cur));
  };
  const cancel = () => finish();
  rect.addEventListener("pointermove", move);
  rect.addEventListener("pointerup", up);
  rect.addEventListener("pointercancel", cancel);
}

async function moveHub(hubId, point, estimate = null) {
  if (state.dragBusy) return false;
  state.dragBusy = true;
  const J0 = currentJ();
  setStatus(`Moving ${hubId}…`);
  try {
    const res = await fetch("api/move_hub", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...planRequest(), answer: state.answer, hub_id: hubId, point }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      flash(`${hubId} can't go there: ${typeof data.detail === "string" ? data.detail : `HTTP ${res.status}`}`);
      return false;
    }
    if (!state.baseAnswer) state.baseAnswer = { answer: state.answer, check: state.check, branching: state.branching, heatmaps: state.heatmaps };
    state.answer = data.answer;
    state.check = data.check;
    state.branching = data.branching?.hubs?.length ? data.branching : null;
    state.heatmaps = state.heatmaps.map((m) => (m.hub_id === hubId ? { ...m, chosen: data.answer.hubs.find((h) => h.hub_id === hubId).point } : m));
    state.breakMode = false; state.cuts = []; state.shorts = [];
    const J1 = currentJ();
    state.moveInfo = { hub_id: hubId, from: J0, to: J1, estimate };
    refreshAnswerViews();
    setStatus("");
    return true;
  } catch (err) {
    flash(`Can't move the hub: ${err.message}`);
    return false;
  } finally {
    state.dragBusy = false;
  }
}

function movePanel() {
  const sec = $("move-section");
  const ok = !!state.api && !!state.answer && !!state.heatmaps?.some((m) => m.points.length > 1);
  sec.hidden = !ok;
  if (!ok) return;
  const info = state.moveInfo;
  const status = $("move-status");
  if (!info) status.replaceChildren();
  else {
    const line = html("div", { class: "move-line" }, `${info.hub_id} moved: J ${info.from.toFixed(2)} → ${info.to.toFixed(2)} (${sgn(info.to - info.from)})`);
    if (info.estimate != null && Math.abs(info.estimate - info.to) > 0.02) {
      line.append(html("small", {}, `The heatmap said ${info.estimate.toFixed(2)}. It prices a spot without the ring's own cable in the way; going around or across it changes the cost.`));
    }
    status.replaceChildren(line);
  }
  $("move-reset").hidden = !info;
}

function resetMoves() {
  if (!state.baseAnswer) return;
  Object.assign(state, state.baseAnswer, { baseAnswer: null, moveInfo: null, breakMode: false, cuts: [], shorts: [] });
  refreshAnswerViews();
}

$("move-reset").addEventListener("click", resetMoves);

// ---------- feature panel (left): three headline features + trade-off and download, one open at a time ----------
// A button shows when its section is available (each section's own panel function decides that).
const TOOLS = { heat: "heat-section", move: "move-section", break: "break-section", tradeoff: "tradeoff-section", download: "download-section" };

function syncRail() {
  let any = false;
  if (state.tool && $(TOOLS[state.tool]).hidden) state.tool = null;
  document.querySelectorAll("#tools-panel [data-tool]").forEach((b) => {
    const sec = $(TOOLS[b.dataset.tool]);
    const on = state.tool === b.dataset.tool;
    b.hidden = sec.hidden;
    any ||= !sec.hidden;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", String(on));
    sec.classList.toggle("open", on);
  });
  $("tools-panel").hidden = !any;
  $("tool-dock").hidden = !state.tool;
}

function setHeat(on) {
  const box = $("heat-toggle");
  if (box.checked !== on) { box.checked = on; box.onchange?.(); }
}

function openTool(name) {
  const prev = state.tool;
  state.tool = prev === name ? null : name;
  if (prev === "heat") setHeat(false);
  if (prev === "break" && state.breakMode) $("break-toggle").click();
  if (state.tool === "heat") setHeat(true);
  if (state.tool === "break" && !state.breakMode) $("break-toggle").click();
  drawAll();
}
document.querySelectorAll("#tools-panel [data-tool]").forEach((b) => b.addEventListener("click", () => openTool(b.dataset.tool)));

// ---------- hooks for the 3D view (view3d.js reads these; nothing here changes the 2D viewer) ----------
// Same rule as handleCut for the loop map: a click near an existing cut repairs it, otherwise it cuts the nearest cable.
function toggleCutAt(at) {
  const s = state.plan.scale;
  const list = faultList();
  const hit = list.findIndex((c) => dist(c, at) <= 0.6 * s);
  if (hit >= 0) {
    list.splice(hit, 1);
    drawAll();
    return;
  }
  const near = nearestRingSeg(state.loopModels, at);
  if (!near || near.d > 0.4 * s) return;
  list.push(near.q);
  drawAll();
}
window.eightballViewer = { state, nearestRingSeg, loopEffects, zoneColors, nodePoints, toggleCutAt, heatRange, rampRGB, RAMP,
  activeIsolators, roomFaults, isolatorSpots };

init();
