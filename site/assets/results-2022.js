"use strict";
/* results-2022.html — 2022 results: seat tally, majority bar, district map, inspect panel, pendulum. */

let BASELINE = null;
let selected = null;
let regionFilter = null;
let districtLayer = null;
let pendulumExpanded = false;

const dispName = (n) => {
  if (!n.includes(",")) return n;
  const [sur, ...rest] = n.split(",");
  const given = rest.join(",").trim();
  const s = sur.trim().toLowerCase().replace(/(^|\s|-)(\w)/g, (m, p, c) => p + c.toUpperCase());
  return given ? `${given} ${s}` : s;
};

function styleFor(feature) {
  const name = feature.properties.district;
  const d = BASELINE.districts[name];
  const sel = selected === name;
  const dim = regionFilter && feature.properties.region !== regionFilter;
  if (!d) return { color: "#94a3b8", weight: 1, fillOpacity: 0.1, fillColor: "#e2e8f0", lineJoin: "round" };
  // Safer seats are darker: opacity rises with the 2CP margin.
  const op = dim ? 0.06 : 0.28 + 0.62 * Math.min(1, d.margin_pct / 20);
  return {
    color: sel ? "#0f172a" : "#334155",
    weight: sel ? 3 : 1,
    lineJoin: "round",
    opacity: dim ? 0.3 : 0.9,
    fillColor: pcolour(d.winner_group),
    fillOpacity: op,
  };
}

function selectDistrict(name, zoom = false) {
  const d = BASELINE.districts[name];
  if (!d) return;
  selected = name;
  districtLayer.setStyle(styleFor);
  if (zoom) {
    let layer;
    districtLayer.eachLayer((l) => { if (l.feature.properties.district === name) layer = l; });
    if (layer) map.flyToBounds(layer.getBounds(), { maxZoom: 11, duration: 0.6 });
  }
  renderPanel(name);
  history.replaceState(null, "", `#${encodeURIComponent(name)}`);
}

const GROUP_NOTE = {
  ALP: "Government", LP: "Opposition", NP: "Coalition partner", GRN: "Crossbench", IND: "None elected",
};

function renderPanel(name) {
  const d = BASELINE.districts[name];
  const el = document.getElementById("dpanel");
  const [a, b] = d.final_two;
  const tot = a.votes + b.votes;
  const aPct = 100 * a.votes / tot;
  el.innerHTML = `
    <p><a class="back-link" id="d-back">← All districts</a></p>
    <h2>${esc(name)}</h2>
    <p><span class="tag hold" style="background:${pcolour(d.winner_group)}">${esc(d.winner_group)} hold</span>
       <span class="tag">${esc(d.region)}</span>${d.indicative_2cp ? '<span class="tag">2CP indicative</span>' : ""}</p>
    <div class="kv"><span>Elected member</span><b>${esc(dispName(d.winner))}</b></div>
    <div class="kv"><span>Party</span><b title="${esc(d.winner_party)}">${esc(shortParty(d.winner_party))}</b></div>
    <div class="kv"><span>2CP margin</span><b class="num">+${d.margin_pct.toFixed(1)}%</b></div>
    <h4>Two-candidate preferred</h4>
    <div class="pair">
      <b>${esc(dispName(a.name))}</b> <span class="muted" title="${esc(a.party)}">${esc(shortParty(a.party))}</span> v
      <b>${esc(dispName(b.name))}</b> <span class="muted" title="${esc(b.party)}">${esc(shortParty(b.party))}</span>
      <div class="split"><span style="width:${aPct}%;background:${pcolour(a.group)}"></span><span style="width:${100 - aPct}%;background:${pcolour(b.group)}"></span></div>
      <table><tr><th></th><th>Votes</th><th class="r">2CP %</th></tr>
      <tr><td>${esc(dispName(a.name))}</td><td class="num">${fmt(a.votes)}</td><td class="r num">${aPct.toFixed(1)}%</td></tr>
      <tr><td>${esc(dispName(b.name))}</td><td class="num">${fmt(b.votes)}</td><td class="r num">${(100 - aPct).toFixed(1)}%</td></tr></table>
      ${d.indicative_2cp ? '<p class="muted small">Full distribution is the VEC&rsquo;s indicative throw (the official count ended when the winner passed 50%).</p>' : ""}
    </div>
    <h4>First preferences</h4>
    <table><tr><th>Candidate</th><th>Party</th><th class="r">Votes</th><th class="r">%</th><th style="width:22%"></th></tr>
      ${d.primary.map((c) => `<tr${c.name === d.winner ? ' class="final"' : ""}>
        <td>${esc(dispName(c.name))}</td>
        <td title="${esc(c.party)}"><span class="swatch" style="background:${pcolour(c.group)}"></span>${esc(shortParty(c.party))}</td>
        <td class="r num">${fmt(c.votes)}</td><td class="r num">${pct1(100 * c.votes / d.formal_votes)}</td>
        <td><span class="bar"><i style="width:${(100 * c.votes / d.formal_votes).toFixed(1)}%;background:${pcolour(c.group)}"></i></span></td></tr>`).join("")}
    </table>
    <h4>Votes</h4>
    <div class="kv"><span>Formal</span><b class="num">${fmt(d.formal_votes)}</b></div>
    <div class="kv"><span>Informal</span><b class="num">${fmt(d.informal_votes)}</b></div>
    <div class="kv"><span>Enrolment</span><b class="num">${fmt(d.enrolment)}</b></div>
    <div class="kv"><span>Region</span><b>${esc(d.region)}</b></div>
    <p style="margin-top:0.75rem"><a href="${esc(d.source_url)}" target="_blank" rel="noopener">VEC result &amp; distribution ↗</a></p>`;
  document.getElementById("d-back").addEventListener("click", () => {
    selected = null;
    districtLayer.setStyle(styleFor);
    history.replaceState(null, "", location.pathname);
    document.getElementById("dpanel").innerHTML = '<p class="muted small">Pick a district on the map or search above.</p>';
  });
}

function renderPendulum() {
  const rows = Object.entries(BASELINE.districts)
    .filter(([, d]) => !regionFilter || d.region === regionFilter)
    .map(([name, d]) => ({ name, ...d }))
    .sort((x, y) => x.margin_pct - y.margin_pct);
  const shown = pendulumExpanded ? rows : rows.slice(0, 10);
  const tbody = document.querySelector("#pendulum-table tbody");
  tbody.innerHTML = shown.map((d) => {
    const ru = d.final_two[1];
    return `<tr>
      <td><a class="back-link" data-d="${esc(d.name)}"><b>${esc(d.name)}</b></a></td>
      <td><span class="swatch" style="background:${pcolour(d.winner_group)}"></span>${esc(d.winner_group)}</td>
      <td class="r num"><b>+${d.margin_pct.toFixed(1)}%</b></td>
      <td title="${esc(ru.party)}"><span class="swatch" style="background:${pcolour(ru.group)}"></span>${esc(shortParty(ru.party))}</td>
      <td class="muted col-region">${esc(d.region)}</td></tr>`;
  }).join("");
  tbody.querySelectorAll("[data-d]").forEach((a) => a.addEventListener("click", () => {
    selectDistrict(a.dataset.d, true);
    document.getElementById("map").scrollIntoView({ behavior: "smooth", block: "center" });
  }));
  const btn = document.getElementById("pendulum-toggle");
  btn.textContent = pendulumExpanded ? "Show closest 10" : `Show all ${rows.length}`;
  btn.style.display = rows.length <= 10 ? "none" : "";
}

function renderChips() {
  const regions = [...new Set(Object.values(BASELINE.districts).map((d) => d.region))].sort();
  const box = document.getElementById("region-chips");
  const mk = (label, value) => {
    const b = document.createElement("button");
    b.className = "fchip" + (value === regionFilter ? " on" : "");
    b.textContent = label;
    b.addEventListener("click", () => {
      regionFilter = value === regionFilter ? null : value;
      renderChips();
      districtLayer.setStyle(styleFor);
      renderPendulum();
    });
    box.appendChild(b);
  };
  box.innerHTML = "";
  mk("All regions", null);
  regions.forEach((r) => mk(r.replace(/ Metropolitan| Victoria/, (m) => (m.includes("Victoria") ? " Vic" : " Metro")), r));
}

async function init() {
  const [baseline, districts, outline, site] = await Promise.all([
    fetch("data/baseline_2022.json").then((r) => r.json()),
    fetch("data/districts.geojson").then((r) => r.json()),
    fetch("data/victoria_outline.json").then((r) => r.json()),
    siteJson().catch(() => null),
  ]);
  BASELINE = baseline;
  const seats = baseline.seats;
  document.getElementById("turnout").textContent = pct1(100 * (baseline.totals.formal + baseline.totals.informal) / baseline.totals.enrolment);
  document.getElementById("formal").textContent = fmt(baseline.totals.formal);

  // Seat cards
  const cards = [
    ["ALP", seats.ALP || 0, `${pct1(baseline.fp_share.ALP)} statewide first preferences`],
    ["LP", seats.LP || 0, `${pct1(baseline.fp_share.LP)} first preferences`],
    ["NP", seats.NP || 0, `${pct1(baseline.fp_share.NP)} first preferences`],
    ["GRN", seats.GRN || 0, `${pct1(baseline.fp_share.GRN)} first preferences`],
    ["IND", seats.IND || 0, `${pct1(baseline.fp_share.IND)} first preferences`],
  ];
  document.getElementById("seat-cards").innerHTML = cards.map(([g, n, note]) => `
    <div class="card seat-card" style="border-top-color:${pcolour(g)}">
      <div class="party-l">${esc(pname(g))} (${esc(g === "LP" ? "LIB" : g === "NP" ? "NAT" : g)})</div>
      <div class="seats"><b class="num">${n}</b><span class="num">${pct1(100 * n / 88)} of seats</span></div>
      <div class="note">${esc(GROUP_NOTE[g] || "")} · ${esc(note)}</div>
    </div>`).join("");

  // Majority bar
  const order = ["ALP", "LP", "NP", "GRN"];
  document.getElementById("majbar").innerHTML =
    order.map((g) => `<div class="seg" style="width:${100 * (seats[g] || 0) / 88}%;background:${pcolour(g)}"></div>`).join("")
    + `<div class="needle" data-label="45 to govern" style="left:${100 * 45 / 88}%"></div>`;
  document.getElementById("maj-legend").innerHTML =
    order.map((g) => `<span><span class="swatch" style="background:${pcolour(g)}"></span>${esc(pname(g))} <b class="num">${seats[g] || 0}</b></span>`).join("");

  // Map: no tiles — districts over the page background, world outside Victoria masked.
  const map = L.map("map", { preferCanvas: true, zoomSnap: 0.5, attributionControl: false, maxZoom: 14 });
  window.map = map;
  map.createPane("mask").style.zIndex = 350;
  const world = [[-85, -180], [-85, 180], [85, 180], [85, -180]];
  L.polygon([world, ...outline], {
    pane: "mask", color: "#0f172a", weight: 2.5, fillColor: "#eef1f5", fillOpacity: 1, interactive: false, smoothFactor: 0,
    renderer: L.canvas({ pane: "mask" }),
  }).addTo(map);
  districtLayer = L.geoJSON(districts, {
    smoothFactor: 0,
    style: styleFor,
    onEachFeature: (f, layer) => {
      const d = BASELINE.districts[f.properties.district];
      layer.bindTooltip(`<b>${esc(f.properties.district)}</b><br><span class="swatch" style="background:${pcolour(d.winner_group)}"></span>${esc(d.winner_group)} +${d.margin_pct.toFixed(1)}%`, { sticky: true });
      layer.on("click", () => selectDistrict(f.properties.district));
    },
  }).addTo(map);
  const vic = districtLayer.getBounds();
  map.fitBounds(vic);
  map.setMinZoom(map.getZoom());
  map.setMaxBounds(vic.pad(0.2));
  map.options.maxBoundsViscosity = 1.0;

  document.getElementById("map-legend").innerHTML =
    ["ALP", "LP", "NP", "GRN"].map((g) => `<span><span class="swatch" style="background:${pcolour(g)}"></span>${esc(pname(g))}</span>`).join("")
    + '<span class="muted">Darker = safer seat</span>';

  document.getElementById("district-list").innerHTML =
    Object.keys(BASELINE.districts).sort().map((n) => `<option value="${esc(n)}">`).join("");
  document.getElementById("search").addEventListener("change", (e) => {
    if (BASELINE.districts[e.target.value]) selectDistrict(e.target.value, true);
  });
  document.getElementById("pendulum-toggle").addEventListener("click", () => {
    pendulumExpanded = !pendulumExpanded;
    renderPendulum();
  });

  renderChips();
  renderPendulum();

  const h = decodeURIComponent(location.hash.slice(1));
  if (h && BASELINE.districts[h]) selectDistrict(h);
}

init().catch((e) => {
  document.getElementById("dpanel").innerHTML = `<p class="neg">Failed to load data: ${esc(e)}. Run scripts/build_site.py and serve site/ over HTTP.</p>`;
});
