// Shared by the home page and the gallery: a small floor-plan drawing with zones, cables and devices.
"use strict";

const THUMB_COLORS = ["#5ff0cf", "#f2b680", "#ff8fbd", "#a7b6ff", "#d4a8ff", "#ffe08a", "#7fd6ff", "#ff9e7a"];

function svgEl(tag, attrs = {}, parent = null) {
  const n = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parent) parent.appendChild(n);
  return n;
}

function planThumbnail(plan, answer, cls = "thumb") {
  const P = (p) => `${p[0]},${-p[1]}`;
  const ringsPath = (rings) => rings.map((r) => "M" + r.map(P).join("L") + "Z").join("");
  const [minx, miny, maxx, maxy] = plan.bounds;
  const svg = svgEl("svg", { viewBox: `${minx} ${-maxy} ${maxx - minx} ${maxy - miny}`, class: cls, role: "img",
                             "aria-label": `Plan ${plan.plan_id}` });
  const zoneOf = {};
  (answer?.hubs || []).forEach((h, k) => h.room_ids.forEach((r) => (zoneOf[r] = THUMB_COLORS[k % THUMB_COLORS.length])));
  for (const room of plan.rooms) {
    const fill = zoneOf[room.room_id];
    svgEl("path", { d: ringsPath(room.polygon), "fill-rule": "evenodd",
                    class: fill ? "room" : room.eligible ? "room free" : "room excluded",
                    ...(fill ? { fill, "fill-opacity": 0.22 } : {}) }, svg);
  }
  for (const rings of plan.walls) svgEl("path", { d: ringsPath(rings), class: "wall", "fill-rule": "evenodd" }, svg);
  for (const rings of plan.doors) svgEl("path", { d: ringsPath(rings), class: "door" }, svg);
  (answer?.hubs || []).forEach((h, k) => {
    const color = THUMB_COLORS[k % THUMB_COLORS.length];
    for (const leg of h.legs) svgEl("path", { d: "M" + leg.polyline.map(P).join("L"), class: "leg", stroke: color }, svg);
    const s = 0.42 * plan.scale;
    svgEl("rect", { x: h.point[0] - s / 2, y: -h.point[1] - s / 2, width: s, height: s, rx: 0.06 * plan.scale, fill: color, class: "hub" }, svg);
  });
  for (const n of plan.nodes) svgEl("circle", { cx: n.point[0], cy: -n.point[1], r: 0.2 * plan.scale, class: "node", stroke: "var(--quiet)" }, svg);
  return svg;
}

async function fetchJSON(url) {
  try {
    const r = await fetch(url, { cache: "no-store" });
    return r.ok ? r.json() : null;
  } catch {
    return null;
  }
}
