// 8ball How it works page (Person B, B10; was the dashboard). Reads data/dashboard.json (bench/report.py) and data/scale.json
// (bench/stitch.py). Both are optional: missing data shows how to produce it.
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
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

const tip = $("tip");
function showTip(e, lines) {
  tip.replaceChildren(...lines.map((t, i) => (i === 0 ? html("strong", {}, t) : html("div", {}, t))));
  tip.style.left = `${Math.min(e.clientX + 14, innerWidth - 240)}px`;
  tip.style.top = `${e.clientY + 14 + scrollY}px`;
  tip.hidden = false;
}
function hideTip() { tip.hidden = true; }
function hover(node, lines) {
  node.addEventListener("pointermove", (e) => showTip(e, lines));
  node.addEventListener("pointerleave", hideTip);
}

const pct = (v) => (v == null ? "–" : `${(100 * v).toFixed(1)}%`);
const sec = (v) => (v == null ? "–" : v < 1 ? `${(v * 1000).toFixed(0)} ms` : `${v.toFixed(2)} s`);

// ---------- benchmark ----------
function tiles(d) {
  const solvable = d.n - (d.blocked || 0);
  const items = [
    ["Test cases", d.n.toLocaleString(), "each test plan with two device layouts"],
    ["Solved and valid", d.valid.toLocaleString(), solvable ? `${pct(d.valid / solvable)} of the ${solvable.toLocaleString()} with a legal layout` : ""],
    ["Solver vs checker", String(d.mismatches), "disagreements, on any rule or number"],
    ["Fewest possible hubs", pct(d.min_hub_share), "of answers hit the proven minimum"],
    ["Cheaper than greedy", pct(d.W), "lower J with the same number of hubs"],
    ["Typical solve time", sec(d.runtime_s?.p50), `95% finish within ${sec(d.runtime_s?.p95)}`],
  ];
  $("tiles").replaceChildren(...items.map(([label, value, note]) => {
    const t = html("div", { class: "tile" });
    t.append(html("div", { class: "tile-label" }, label), html("div", { class: "tile-value" }, value),
      html("div", { class: "tile-note" }, note));
    return t;
  }));
}

function histogramChart(hist) {
  const svg = $("hist");
  const W = 560, H = 260, m = { l: 40, r: 12, t: 12, b: 36 };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.replaceChildren();
  const maxC = Math.max(...hist.map((b) => b[2]), 1);
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const bw = iw / hist.length;
  const y = (c) => m.t + ih - (c / maxC) * ih;
  const ticks = niceTicks(0, maxC, 4).filter(Number.isInteger);
  for (const t of ticks) {
    el("line", { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: "grid" }, svg);
    el("text", { x: m.l - 6, y: y(t) + 4, class: "axis-label", "text-anchor": "end" }, svg).textContent = String(t);
  }
  hist.forEach(([lo, hi, c], i) => {
    const x = m.l + i * bw + 1, w = Math.max(1, bw - 2);
    const h = Math.max(c ? 1 : 0, (c / maxC) * ih);
    el("path", { d: roundedTop(x, m.t + ih - h, w, h, Math.min(4, w / 2)), class: "bar s1" }, svg);
    const hit = el("rect", { x: m.l + i * bw, y: m.t, width: bw, height: ih, class: "hit" }, svg);
    hover(hit, [`J ${lo.toFixed(1)} – ${hi.toFixed(1)}`, `${c} plan${c === 1 ? "" : "s"}`]);
    if (i % 2 === 0) el("text", { x: m.l + i * bw, y: H - m.b + 16, class: "axis-label", "text-anchor": "middle" }, svg).textContent = lo.toFixed(0);
  });
  el("line", { x1: m.l, x2: W - m.r, y1: m.t + ih, y2: m.t + ih, class: "axis" }, svg);
  el("text", { x: m.l + iw / 2, y: H - 4, class: "axis-title", "text-anchor": "middle" }, svg).textContent = "J (lower is better)";
}

function roundedTop(x, y, w, h, r) {
  if (h <= r) return `M${x},${y + h}V${y}H${x + w}V${y + h}Z`;
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function niceTicks(lo, hi, n) {
  const span = hi - lo || 1;
  const step = Math.pow(10, Math.floor(Math.log10(span / n)));
  const err = (span / n) / step;
  const s = step * (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1);
  const out = [];
  for (let v = Math.ceil(lo / s) * s; v <= hi + 1e-9; v += s) out.push(+v.toFixed(6));
  return out;
}

function failures(f) {
  const rows = Object.entries(f || {});
  const table = $("fail-table");
  if (!rows.length) {
    table.replaceChildren(html("caption", {}, "No failures."));
    return;
  }
  // Report keys name the open questions (Q13-15); say what they mean instead.
  const plain = (k) => (/Q13|Q14|no legal split/.test(k) ? "The rooms can't be split into legal zones"
    : /Q15|free floor/.test(k) ? "A device sits off the usable floor" : k);
  table.replaceChildren(...rows.map(([k, v]) => {
    const tr = html("tr");
    tr.append(html("td", {}, plain(k)), html("td", {}, String(v)));
    return tr;
  }));
}

// ---------- scalability ----------
function scaleChart(data) {
  const pts = data.points.slice().sort((a, b) => a.rooms - b.rooms);
  const svg = $("scale");
  const W = 760, H = 320, m = { l: 56, r: 92, t: 14, b: 40 };
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.replaceChildren();
  const floorS = (t) => Math.max(t, 1e-3);
  const maxX = Math.max(...pts.map((p) => p.rooms)) * 1.05;
  const yLo = -3, yHi = Math.ceil(Math.log10(data.budget_s * 1.6));
  const iw = W - m.l - m.r, ih = H - m.t - m.b;
  const x = (r) => m.l + (r / maxX) * iw;
  const y = (t) => m.t + ih - ((Math.log10(floorS(t)) - yLo) / (yHi - yLo)) * ih;
  for (let e = yLo; e <= yHi; e++) {
    el("line", { x1: m.l, x2: m.l + iw, y1: y(10 ** e), y2: y(10 ** e), class: "grid" }, svg);
    el("text", { x: m.l - 8, y: y(10 ** e) + 4, class: "axis-label", "text-anchor": "end" }, svg).textContent =
      e < 0 ? `${10 ** (e + 3)} ms` : `${10 ** e} s`;
  }
  for (const t of niceTicks(0, maxX, 6)) {
    el("text", { x: x(t), y: m.t + ih + 18, class: "axis-label", "text-anchor": "middle" }, svg).textContent = String(t);
  }
  el("line", { x1: m.l, x2: m.l + iw, y1: m.t + ih, y2: m.t + ih, class: "axis" }, svg);
  el("text", { x: m.l + iw / 2, y: H - 4, class: "axis-title", "text-anchor": "middle" }, svg).textContent = "Eligible rooms on the floor";
  el("line", { x1: m.l, x2: m.l + iw, y1: y(data.budget_s), y2: y(data.budget_s), class: "budget" }, svg);
  el("text", { x: m.l + 4, y: y(data.budget_s) - 6, class: "axis-label" }, svg).textContent = `${data.budget_s} s budget`;

  const series = [
    { key: "cpsat", label: "CP-SAT", cls: "s1", pts: pts.map((p) => ({ p, t: p.cpsat_s })) },
    { key: "exh", label: "Exhaustive search", cls: "s2", pts: pts.filter((p) => p.exhaustive_finished).map((p) => ({ p, t: p.exhaustive_s })) },
  ];
  for (const s of series) {
    if (!s.pts.length) continue;
    el("path", { d: "M" + s.pts.map(({ p, t }) => `${x(p.rooms)},${y(t)}`).join("L"), class: `line ${s.cls}` }, svg);
    const last = s.pts[s.pts.length - 1];
    el("text", { x: x(last.p.rooms) + 8, y: y(last.t) + 4, class: "direct-label" }, svg).textContent = s.label;
    for (const { p, t } of s.pts) {
      el("circle", { cx: x(p.rooms), cy: y(t), r: 4, class: `dot ${s.cls}` }, svg);
      const hit = el("circle", { cx: x(p.rooms), cy: y(t), r: 11, class: "hit" }, svg);
      hover(hit, [`${s.label} · ${p.rooms} rooms`, `${sec(t)} · ${p.candidates} candidate zones`,
        s.key === "cpsat" ? `${p.cpsat_hubs} hubs · ${p.cpsat_optimal ? "proven optimal" : "best found"}` : `${p.exhaustive_hubs} hubs`]);
    }
  }
  for (const p of pts.filter((q) => !q.exhaustive_finished)) {
    const cx = x(p.rooms), cy = y(data.budget_s), a = 5;
    el("path", { d: `M${cx - a},${cy - a}L${cx + a},${cy + a}M${cx - a},${cy + a}L${cx + a},${cy - a}`, class: "stop s2" }, svg);
    const hit = el("circle", { cx, cy, r: 11, class: "hit" }, svg);
    hover(hit, [`Exhaustive search · ${p.rooms} rooms`, `stopped at the ${data.budget_s} s budget`, `CP-SAT took ${sec(p.cpsat_s)}`]);
  }
  $("scale-legend").replaceChildren(
    legendItem("s1", "line", "CP-SAT"), legendItem("s2", "line", "Exhaustive search"),
    legendItem("s2", "stop", `Exhaustive stopped at ${data.budget_s} s`));

  const table = $("scale-table");
  const head = html("tr");
  ["Flats", "Rooms", "Candidate zones", "Hubs", "CP-SAT", "Optimal", "Exhaustive", "Finished"].forEach((h) => head.append(html("th", {}, h)));
  table.replaceChildren(head, ...pts.map((p) => {
    const tr = html("tr");
    [p.flats, p.rooms, p.candidates, p.cpsat_hubs, sec(p.cpsat_s), p.cpsat_optimal ? "yes" : "no",
     p.exhaustive_finished ? sec(p.exhaustive_s) : `> ${data.budget_s} s`, p.exhaustive_finished ? "yes" : "no"]
      .forEach((v) => tr.append(html("td", {}, String(v))));
    return tr;
  }));
}

function legendItem(cls, kind, label) {
  const item = html("span", { class: "legend-item" });
  const sw = document.createElementNS(SVGNS, "svg");
  sw.setAttribute("width", "22"); sw.setAttribute("height", "12");
  if (kind === "line") {
    el("line", { x1: 1, x2: 21, y1: 6, y2: 6, class: `line ${cls}` }, sw);
    el("circle", { cx: 11, cy: 6, r: 3.5, class: `dot ${cls}` }, sw);
  } else {
    el("path", { d: "M7,2L15,10M7,10L15,2", class: `stop ${cls}` }, sw);
  }
  item.append(sw, document.createTextNode(label));
  return item;
}

async function init() {
  const [dash, scale] = await Promise.all([getJSON("data/dashboard.json"), getJSON("data/scale.json")]);
  if (dash && dash.n) {
    $("bench-sub").textContent = `The full ResPlan test split, solved with the exact solver and checked independently (run ${dash.run ?? "?"}, ${dash.generated}).`;
    tiles(dash);
    if (dash.J?.hist?.length) { $("hist-fig").hidden = false; histogramChart(dash.J.hist); }
    $("fail-fig").hidden = false;
    failures(dash.failures);
  } else {
    $("bench-empty").hidden = false;
  }
  if (scale && scale.points?.length) {
    $("scale-fig").hidden = false;
    const c = scale.claim;
    $("scale-claim").textContent = c?.N
      ? `CP-SAT picks the zones for a ${c.N}-room floor in ${sec(c.T)}${c.optimal ? ", and proves the choice optimal" : ""}.` : "";
    $("scale-sub").textContent = "To test far beyond a single home, we join several ResPlan flats into one large floor. " +
      "The exact search gives up at the time limit; CP-SAT keeps going.";
    scaleChart(scale);
  } else {
    $("scale-empty").hidden = false;
  }
}

init();
