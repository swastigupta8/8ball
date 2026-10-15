// 8ball gallery (Person B, B10). Reads data/gallery/index.json (bench/gallery.py) and draws a card per
// plan with a small floor-plan thumbnail; each card opens the plan in the viewer.
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
const HUB_COLORS = ["#2563A8", "#D2601A", "#1E8A5A", "#8B4FB0", "#C23B73", "#6F7F1F", "#2B8FA6", "#9A6A2E"];
const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, parent = null) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}
function html(tag, attrs = {}, text = null) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (text !== null) n.textContent = text;
  return n;
}
async function getJSON(url) {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}

const P = (p) => `${p[0]},${-p[1]}`;
const ringsPath = (rings) => rings.map((r) => "M" + r.map(P).join("L") + "Z").join("");

function thumbnail(plan, answer) {
  const [minx, miny, maxx, maxy] = plan.bounds;
  const svg = el("svg", { viewBox: `${minx} ${-maxy} ${maxx - minx} ${maxy - miny}`, class: "thumb", role: "img",
                          "aria-label": `Plan ${plan.plan_id}` });
  const zoneOf = {};
  (answer?.hubs || []).forEach((h, k) => h.room_ids.forEach((r) => (zoneOf[r] = HUB_COLORS[k % HUB_COLORS.length])));
  for (const room of plan.rooms) {
    const fill = zoneOf[room.room_id];
    el("path", { d: ringsPath(room.polygon), "fill-rule": "evenodd",
                 class: fill ? "room" : room.eligible ? "room free" : "room excluded",
                 ...(fill ? { fill, "fill-opacity": 0.22 } : {}) }, svg);
  }
  for (const rings of plan.walls) el("path", { d: ringsPath(rings), class: "wall", "fill-rule": "evenodd" }, svg);
  for (const rings of plan.doors) el("path", { d: ringsPath(rings), class: "door" }, svg);
  (answer?.hubs || []).forEach((h, k) => {
    for (const leg of h.legs) {
      el("path", { d: "M" + leg.polyline.map(P).join("L"), class: "leg", stroke: HUB_COLORS[k % HUB_COLORS.length] }, svg);
    }
  });
  for (const n of plan.nodes) el("circle", { cx: n.point[0], cy: -n.point[1], r: 0.2 * plan.scale, class: "node", stroke: "var(--quiet)" }, svg);
  return svg;
}

async function init() {
  const index = await getJSON("data/gallery/index.json");
  if (!index || !index.plans?.length) {
    $("empty").hidden = false;
    return;
  }
  if (!index.solver_ready) {
    $("lead").textContent += " The solver isn't built yet, so these show plans and nodes only.";
  }
  const cards = await Promise.all(index.plans.map(async (e) => {
    const [plan, answer] = await Promise.all([getJSON(`${e.path}/plan.json`), e.solved ? getJSON(`${e.path}/answer.json`) : null]);
    const a = html("a", { class: "card", href: `index.html?plan=${encodeURIComponent(e.path)}` });
    if (plan) a.append(thumbnail(plan, answer));
    const body = html("div", { class: "card-body" });
    body.append(html("div", { class: "card-title" }, `Plan ${e.plan_id}`));
    const facts = `${e.rooms} rooms · ${e.area_m2} m² · needs ${e.min_hubs}+ hub${e.min_hubs > 1 ? "s" : ""}`;
    body.append(html("div", { class: "card-facts" }, facts));
    const chips = html("div", { class: "chips" });
    for (const t of e.tags) chips.append(html("span", { class: "chip" }, t));
    body.append(chips);
    const status = e.solved
      ? html("div", { class: `card-status ${e.valid ? "good" : "bad"}` },
          `${e.valid ? "Valid" : "Invalid"} · J ${e.metrics?.J?.toFixed(2) ?? "–"} · ${e.metrics?.H ?? "?"} hubs`)
      : html("div", { class: "card-status" }, "Not solved yet");
    body.append(status);
    a.append(body);
    return a;
  }));
  $("cards").replaceChildren(...cards);
}

init();
