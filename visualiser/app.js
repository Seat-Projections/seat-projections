"use strict";

const COLOURS = {
  ALP: "#e13940", LP: "#1c4f9c", NP: "#00704a", LNP: "#1c4f9c", COAL: "#1c4f9c", GRN: "#10a64a", GVIC: "#10a64a", ON: "#f36c21",
  IND: "#20a39e", FFP: "#7b3fa0", FFPA: "#7b3fa0", CYA: "#e6b800", LTP: "#d4a017", HMP: "#5b8c2a", VNS: "#c2185b", SAL: "#c2185b",
  AJP: "#2e7d32", CEC: "#795548", GRPF: "#8d6e63", SOPA: "#607d8b",
};
const GROUP_LABEL = { ALP: "Labor", COAL: "Coalition", GRN: "Greens", ON: "One Nation", IND: "Independent", OTH: "Other" };
const SCALE_MAX = { ON: 30, ALP: 60, COAL: 70, GRN: 50, IND: 40 };
const DECL_LABEL = { ABSENT: "Absent", POSTAL: "Postal", PRE_POLL: "Declaration pre-poll", PROVISIONAL: "Provisional" };

const colour = (ab) => COLOURS[ab] || "#9e9e9e";
const fmt = (n) => (n ?? 0).toLocaleString("en-AU");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const panel = document.getElementById("panel");
const divisionCache = new Map();
let flowsPromise = null;
const loadFlows = () => (flowsPromise ||= fetch("data/district_flows.json").then((r) => r.json()));

// zoomSnap 0.5: fewer intermediate redraws per trackpad/wheel gesture than 0.25, still a snug fit to Victoria
const map = L.map("map", { preferCanvas: true, minZoom: 6, zoomSnap: 0.5 }).setView([-37.0, 145.0], 7);
const SOURCES = " · Results: AEC · Boundaries: Electoral Boundaries Commission (Vic)";
const basemaps = {
  OpenStreetMap: L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' + SOURCES, maxZoom: 19,
  }),
  "OpenStreetMap (Humanitarian)": L.tileLayer("https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, tiles by HOT' + SOURCES, maxZoom: 19,
  }),
  "No basemap": L.layerGroup(),
};
basemaps.OpenStreetMap.addTo(map);
L.control.layers(basemaps, null, { position: "topright" }).addTo(map);

let booths = [], districtLayer, selectedDistrict = null;
const boothLayer = L.layerGroup().addTo(map);
const markers = new Map();
const legend = L.control({ position: "bottomleft" });
legend.onAdd = () => L.DomUtil.create("div", "legend");
legend.addTo(map);

function interpolate(hex, t) {
  const c = parseInt(hex.slice(1), 16), base = [247, 247, 247];
  const rgb = [(c >> 16) & 255, (c >> 8) & 255, c & 255].map((v, i) => Math.round(base[i] + (v - base[i]) * t));
  return `rgb(${rgb.join(",")})`;
}

function boothColour(b, mode) {
  if (mode === "lead") return colour(b.lead);
  return interpolate(colour(mode), Math.min(1, (b.share[mode] || 0) / SCALE_MAX[mode]));
}

function updateLegend(mode) {
  const div = legend.getContainer();
  if (mode === "lead") {
    const present = [...new Set(booths.filter((b) => b.district).map((b) => b.lead))].filter(Boolean);
    div.innerHTML = "<b>Leading party at booth</b><br>" + present.sort().map((ab) => `<span class="swatch" style="background:${colour(ab)}"></span>${esc(ab)}`).join("<br>");
  } else {
    div.innerHTML = `<b>${GROUP_LABEL[mode]} first-preference %</b><br><div class="ramp" style="background:linear-gradient(to right, ${interpolate(colour(mode), 0)}, ${colour(mode)})"></div>0%<span style="float:right">${SCALE_MAX[mode]}%+</span>`;
  }
  div.innerHTML += '<br><span class="muted">Dot size = ordinary formal votes · dark outline = pre-poll centre<br>faded, dashed = not counted in its district (far outside its own federal division)</span>';
}

function renderBooths() {
  const mode = document.getElementById("colour-by").value;
  const showPpvc = document.getElementById("show-ppvc").checked;
  boothLayer.clearLayers();
  markers.clear();
  for (const b of booths) {
    if (!b.district || b.lat == null) continue;
    const ppvc = b.type === "Pre-poll voting centre";
    if (ppvc && !showPpvc) continue;
    const m = L.circleMarker([b.lat, b.lon], {
      radius: Math.max(3, Math.min(11, Math.sqrt(b.votes) / 7)),
      fillColor: boothColour(b, mode), fillOpacity: b.counted ? 0.9 : 0.3,
      color: ppvc || !b.counted ? "#111" : "#fff", weight: ppvc || !b.counted ? 1.5 : 0.8, dashArray: b.counted ? null : "3 3",
    });
    m.bindTooltip(`${esc(b.name)}<br><span class="muted">${esc(b.district)} · ${fmt(b.votes)} votes</span>`);
    m.on("click", (e) => { L.DomEvent.stopPropagation(e); showBooth(b); });
    m.addTo(boothLayer);
    markers.set(b.id, m);
  }
  updateLegend(mode);
}

function shareBars(share) {
  return Object.keys(GROUP_LABEL).map((g) => {
    const v = share[g] || 0;
    return `<tr><td><span class="swatch" style="background:${colour(g === "OTH" ? "" : g)}"></span>${GROUP_LABEL[g]}</td><td>${v.toFixed(1)}%</td><td style="width:55%"><span class="bar" style="width:${v}%;background:${colour(g === "OTH" ? "" : g)}"></span></td></tr>`;
  }).join("");
}

function overview() {
  const counted = booths.filter((b) => b.counted);
  const hidden = booths.filter((b) => !b.district);
  panel.innerHTML = `
    <h2>Victoria</h2>
    <p class="muted">88 Legislative Assembly districts (2021 redivision, used in 2022 and 2026). ${fmt(counted.length)} of ${fmt(booths.length)} 2025 federal polling places
      (${fmt(counted.reduce((a, b) => a + b.votes, 0))} votes) are counted in the district they sit in; booths far outside their own federal division are shown faded and not counted.</p>
    <p>Click a <b>dot</b> for that polling place's 2025 results, or a <b>district</b> for a summary and its collated preference flows.</p>
    <details><summary>Not shown on the map (${hidden.length})</summary>
      <p class="muted">Mobile and hospital teams have no fixed location; EAV (electronically assisted voting) centres are not geographic. Their votes are part of the division totals only.</p>
      <table><tr><th>Polling place</th><th>Division</th><th>Votes</th></tr>
      ${hidden.sort((a, b) => b.votes - a.votes).map((b) => `<tr><td><a class="link" data-booth="${b.id}">${esc(b.name)}</a></td><td>${esc(b.div)}</td><td>${fmt(b.votes)}</td></tr>`).join("")}</table>
    </details>
    <p class="muted">Ordinary votes at polling places are about 76% of the formal vote. Absent, postal, declaration pre-poll and provisional votes are only published per federal division; each booth panel shows its division's totals.</p>`;
  bindLinks();
}

function bindLinks() {
  panel.querySelectorAll("[data-booth]").forEach((a) => a.addEventListener("click", () => {
    const b = booths.find((x) => x.id === +a.dataset.booth);
    if (b) showBooth(b, true);
  }));
  panel.querySelectorAll("[data-district]").forEach((a) => a.addEventListener("click", () => selectDistrict(a.dataset.district, true)));
}

async function loadDivision(divId) {
  if (!divisionCache.has(divId)) divisionCache.set(divId, fetch(`data/divisions/${divId}.json`).then((r) => r.json()));
  return divisionCache.get(divId);
}

function fpTable(fp, total) {
  return `<table><tr><th>Candidate</th><th>Party</th><th>Votes</th><th>%</th><th>Swing</th><th></th></tr>${fp.map((c) => `
    <tr><td>${esc(c.name)}${c.elected ? " ✓" : ""}</td><td title="${esc(c.party)}"><span class="swatch" style="background:${colour(c.ab)}"></span>${esc(c.ab)}</td>
    <td>${fmt(c.votes)}</td><td>${c.pct.toFixed(1)}</td><td class="${+c.swing < 0 ? "neg" : "pos"}">${c.swing ? (+c.swing > 0 ? "+" : "") + c.swing : ""}</td>
    <td style="width:22%"><span class="bar" style="width:${c.pct}%;background:${colour(c.ab)}"></span></td></tr>`).join("")}
    <tr><td><b>Total formal</b></td><td></td><td><b>${fmt(total)}</b></td><td></td><td></td><td></td></tr></table>`;
}

function flowsTable(flows) {
  if (!flows) return '<p class="muted">Not published.</p>';
  const f = flows.finalists;
  return `<div class="scroll"><table><tr><th>From</th>${f.map((x) => `<th><span class="swatch" style="background:${colour(x.ab)}"></span>${esc(x.name.split(",")[0])} (${esc(x.ab)})</th>`).join("")}</tr>
    ${flows.rows.map((r) => `<tr><td>${esc(r.from)}${r.ab ? ` <span class="muted">${esc(r.ab)}</span>` : ""}</td>${r.votes.map((v, i) => `<td>${fmt(v)} <span class="muted">${r.pct[i].toFixed(1)}%</span></td>`).join("")}</tr>`).join("")}
  </table></div><p class="muted">How each candidate's ballots at this location split between the division's final two.</p>`;
}

function dopTable(dop) {
  if (!dop) return '<p class="muted">Not published.</p>';
  return `<div class="scroll"><table><tr><th>Count</th>${dop.cands.map((c) => `<th title="${esc(c.name)}"><span class="swatch" style="background:${colour(c.ab)}"></span>${esc(c.name.split(",")[0])}</th>`).join("")}</tr>
    ${dop.counts.map((k) => `<tr><td>${k.n === 0 ? "First prefs" : `${k.n}: excl. ${esc((k.excluded || "").split(",")[0])}`}</td>${k.pref.map((v, i) => `<td class="${v === 0 && k.n > 0 ? "excluded" : ""}">${fmt(v)}${k.xfer[i] ? `<br><span class="${k.xfer[i] < 0 ? "neg" : "pos"}">${k.xfer[i] > 0 ? "+" : ""}${fmt(k.xfer[i])}</span>` : ""}</td>`).join("")}</tr>`).join("")}
  </table></div><p class="muted">The division's count replayed on this location's ballots (it follows the division's exclusion order).</p>`;
}

function declarationSection(decl, division) {
  const kinds = Object.keys(decl);
  if (!kinds.length) return "";
  const totals = kinds.map((k) => decl[k].dop.counts[0].pref.reduce((a, b) => a + b, 0));
  return `<details><summary>${esc(division)} — votes not located at a booth (${fmt(totals.reduce((a, b) => a + b, 0))})</summary>
    <p class="muted">Published per federal division only, so they cannot be placed on the map.</p>
    <table><tr><th>Type</th><th>Formal votes</th></tr>${kinds.map((k, i) => `<tr><td>${DECL_LABEL[k] || k}</td><td>${fmt(totals[i])}</td></tr>`).join("")}</table>
    ${kinds.map((k) => `<details><summary>${DECL_LABEL[k] || k}: distribution of preferences</summary>${dopTable(decl[k].dop)}</details>`).join("")}
  </details>`;
}

async function showBooth(b, pan = false) {
  if (pan && b.lat != null && b.district) map.setView([b.lat, b.lon], Math.max(map.getZoom(), 12));
  panel.innerHTML = `<h2>${esc(b.name)}</h2><p class="muted">Loading…</p>`;
  const div = await loadDivision(b.divId);
  const d = div.booths[b.id];
  const tcpTotal = d.tcp.reduce((a, c) => a + c.votes, 0) || 1;
  panel.innerHTML = `
    <p><a class="link" id="back">← Victoria</a></p>
    <h2>${esc(b.name)}</h2>
    <p><span class="tag">${esc(b.type)}</span><span class="tag">Federal: ${esc(b.div)}</span>
      ${b.district ? `<span class="tag">State: <a class="link" data-district="${esc(b.district)}">${esc(b.district)}</a>${b.method === "nearest" ? " (nearest)" : ""}</span>` : '<span class="tag">Not in a state district</span>'}
      ${b.district && !b.counted ? `<span class="tag warn">Not counted in ${esc(b.district)}: ${b.method === "nearest" ? "outside the district boundary" : `${b.divKm} km outside its federal division, so its voters live elsewhere`}</span>` : ""}</p>
    <details open><summary>Overview</summary>
      <p>${esc(d.address)}</p>
      <table><tr><td>Ordinary formal votes</td><td>${fmt(b.votes)}</td></tr><tr><td>Informal votes</td><td>${fmt(d.informal)}</td></tr>
      ${b.lat != null ? `<tr><td>Location</td><td>${b.lat.toFixed(5)}, ${b.lon.toFixed(5)}</td></tr>` : ""}</table>
      <h3>Vote share by party group</h3><table>${shareBars(b.share)}</table>
    </details>
    <details open><summary>First preferences</summary>${fpTable(d.fp, b.votes)}</details>
    <details><summary>Two-candidate preferred</summary>
      <table><tr><th>Candidate</th><th>Party</th><th>Votes</th><th>%</th><th>Swing</th></tr>
      ${d.tcp.map((c) => `<tr><td>${esc(c.name)}</td><td><span class="swatch" style="background:${colour(c.ab)}"></span>${esc(c.ab)}</td><td>${fmt(c.votes)}</td><td>${(100 * c.votes / tcpTotal).toFixed(1)}</td><td>${esc(c.swing)}</td></tr>`).join("")}</table>
    </details>
    <details><summary>Two-party preferred (Labor v Coalition)</summary>
      ${d.tpp ? `<table><tr><td>Labor</td><td>${fmt(d.tpp.alp)}</td><td>${d.tpp.alpPct}%</td></tr><tr><td>Coalition</td><td>${fmt(d.tpp.coal)}</td><td>${d.tpp.coalPct}%</td></tr><tr><td>Swing to Labor</td><td></td><td>${esc(d.tpp.swing)}</td></tr></table>` : '<p class="muted">Not published.</p>'}
    </details>
    <details><summary>Preference flows to the final two</summary>${flowsTable(d.flows)}</details>
    <details><summary>Full distribution of preferences</summary>${dopTable(d.dop)}</details>
    ${declarationSection(div.declaration, b.div)}`;
  document.getElementById("back").addEventListener("click", () => { clearDistrict(); overview(); });
  bindLinks();
  const m = markers.get(b.id);
  if (m) m.openTooltip();
}

// ---------------------------------------------------------------- forecast views (model1, model2)

let view = "booths";
const forecasts = {};
const fc = () => forecasts[view];
const MODEL_TITLE = { model1: "Model 1", model2: "Model 2" };
const loadForecast = async (model) => (forecasts[model] ||= await fetch(`data/${model}_vic2026.json`).then((r) => {
  if (!r.ok) throw new Error(`data/${model}_vic2026.json missing: run the model, then scripts/build_visualiser.py --forecasts-only`);
  return r.json();
}));
// Display names: model2 forecasts candidates (ids are names); model1 forecasts parties (ids are party codes, names attached)
const nameOf = (d, id) => (d.candidates.find((c) => c.id === id)?.name) || candName(id);
const shortOf = (d, id) => {
  const n = nameOf(d, id);
  return n.includes(";") ? `${partyName(d.candidates.find((c) => c.id === id)?.party || id)}s` : surname(n);
};
const PARTY_NAME = { ALP: "Labor", LP: "Liberal", NP: "Nationals", COAL: "Coalition", GRN: "Greens", ON: "One Nation", "IND*": "Independent" };
const m2colour = (p) => colour(p === "IND*" ? "IND" : p);
const partyName = (p) => PARTY_NAME[p] || p;
const candName = (id) => (id === "ONE NATION" ? "One Nation candidate" : id);
const surname = (id) => (id === "ONE NATION" ? "One Nation" : id.split(",")[0]);
const pct1 = (x) => `${(+x).toFixed(1)}%`;

function favourite(name) {
  const d = fc() && fc().districts[name];
  return d ? d.candidates.reduce((a, c) => (c.p_win > a.p_win ? c : a)) : null;
}

function forecastStyle(feature) {
  const name = feature.properties.district, sel = selectedDistrict === name, fav = favourite(name);
  // Shade by how likely the favourite is to win: faint below 50%, solid near 100%
  const strength = fav ? Math.max(0.15, Math.min(0.85, (fav.p_win - 0.3) / 0.7 * 0.85)) : 0;
  return { color: sel ? "#111827" : "#374151", weight: sel ? 4 : 1.2, opacity: 1, fill: true,
           fillColor: fav ? m2colour(fav.party) : "#ccc", fillOpacity: strength };
}

function forecastTooltip(layer) {
  const name = layer.feature.properties.district, d = fc() && fc().districts[name];
  if (!d) return `<b>${esc(name)}</b>`;
  const top = [...d.candidates].sort((a, b) => b.p_win - a.p_win).filter((c) => c.p_win >= 0.01).slice(0, 3);
  return `<b>${esc(name)}</b><br>${top.map((c) => `<span class="swatch" style="background:${m2colour(c.party)}"></span>${esc(partyName(c.party))} ${Math.round(100 * c.p_win)}%`).join("<br>")}`;
}

function forecastLegend() {
  const div = legend.getContainer();
  const parties = [...new Set(Object.keys(fc().districts).map((n) => favourite(n).party))];
  div.innerHTML = `<b>${MODEL_TITLE[view]}: favourite to win</b><br>` + parties.map((p) => `<span class="swatch" style="background:${m2colour(p)}"></span>${esc(partyName(p))}`).join("<br>")
    + '<br><span class="muted">Darker = more likely. Placeholder parameters; not a final forecast.</span>';
}

function seatsTable() {
  // Liberals and Nationals as one Coalition: summed run by run, so the range and majority chance are for the combined total
  const rows = fc().blocs || fc().seats;
  const parts = Object.fromEntries(fc().seats.map((s) => [s.party, s]));
  const coalParts = ["LP", "NP"].filter((p) => parts[p]).map((p) => `${partyName(p)} ${parts[p].seats_mean.toFixed(1)}`).join(" + ");
  return `<table><tr><th>Party</th><th>Mean</th><th>p10–p90</th><th>Majority</th></tr>
    ${rows.map((s) => `<tr><td><span class="swatch" style="background:${m2colour(s.party)}"></span>${esc(partyName(s.party))}${s.party === "COAL" && coalParts ? `<br><span class="muted">${esc(coalParts)}</span>` : ""}</td>
      <td>${s.seats_mean.toFixed(1)}</td><td>${s.seats_p10}–${s.seats_p90}</td><td>${Math.round(100 * s.p_majority)}%</td></tr>`).join("")}</table>
    <p class="muted">Coalition = Liberal + National seats added up in each simulation; Majority = chance of ${fc().meta.majority}+ seats.</p>`;
}

function forecastOverview() {
  const m = fc().meta, maj = m.majority;
  const close = Object.entries(fc().districts).map(([n, d]) => [n, favourite(n), d]).filter(([, f]) => f.p_win < 0.6).sort((a, b) => a[1].p_win - b[1].p_win);
  panel.innerHTML = `
    <h2>Victoria 2026 — ${MODEL_TITLE[view]} forecast</h2>
    <p class="muted">${esc(m.description)} ${fmt(m.runs)} simulations on the declared 2026 candidates. Parameters are placeholders: treat this as a working forecast, not a final one.</p>
    <details open><summary>Seats (${maj} for a majority)</summary>
      ${seatsTable()}
    </details>
    ${m.polls ? `<details><summary>Polling average used</summary><table>${Object.entries(m.polls).map(([k, v]) => `<tr><td>${esc({ LNP: "Coalition", OTH: "Others" }[k] || partyName(k))}</td><td>${pct1(v)}</td></tr>`).join("")}</table>
      <p class="muted">Each pollster's latest poll within 35 days of the newest: ${esc((m.polls_used || []).join("; "))}.</p></details>` : ""}
    <details open><summary>Closest seats (${close.length} with no candidate above 60%)</summary>
      <table><tr><th>District</th><th>Favourite</th><th>Chance</th></tr>
      ${close.map(([n, f]) => `<tr><td><a class="link" data-district="${esc(n)}">${esc(n)}</a></td><td><span class="swatch" style="background:${m2colour(f.party)}"></span>${esc(partyName(f.party))}</td><td>${Math.round(100 * f.p_win)}%</td></tr>`).join("")}</table>
    </details>
    <p class="muted">Click a district for its stage-by-stage count and the estimated two-candidate result. Run: ${esc(m.run_id)}, ${esc((m.timestamp || "").slice(0, 10))}, commit ${esc((m.git_commit || "").slice(0, 7))}.</p>`;
  bindLinks();
}

function stagesTable(d) {
  const cands = d.candidates.map((c) => c.id);
  const party = Object.fromEntries(d.candidates.map((c) => [c.id, c.party]));
  const first = Object.fromEntries(d.candidates.map((c) => [c.id, c.primary]));
  const out = new Set();
  const head = `<tr><th>Stage</th>${cands.map((c) => `<th title="${esc(nameOf(d, c))} (${esc(partyName(party[c]))})"><span class="swatch" style="background:${m2colour(party[c])}"></span>${esc(shortOf(d, c))}</th>`).join("")}</tr>`;
  const firstRow = `<tr><td>First preferences</td>${cands.map((c) => `<td>${pct1(first[c])}</td>`).join("")}</tr>`;
  const rows = d.central.stages.map((s, i) => {
    const gone = new Set(s.excluded);
    const last = i === d.central.stages.length - 1;
    const cells = cands.map((c) => {
      if (gone.has(c)) { out.add(c); return '<td class="gone">out</td>'; }
      if (out.has(c)) return '<td class="out"></td>';
      const t = s.transfers[c] || 0;
      return `<td>${pct1(s.totals[c])}${t ? `<br><span class="pos">+${t.toFixed(1)}</span>` : ""}</td>`;
    }).join("");
    const label = s.excluded.length > 1 ? `${s.excluded.length} minor candidates` : `${esc(shortOf(d, s.excluded[0]))} <span class="muted">${esc(partyName(party[s.excluded[0]]))}</span>`;
    const exh = s.transfers.EXH ? ` <span class="muted">(${s.transfers.EXH.toFixed(1)} exhausted)</span>` : "";
    return `<tr class="${last ? "final" : ""}"><td>${i + 1}. ${label} excluded (${s.pile.toFixed(1)})${exh}</td>${cells}</tr>`;
  }).join("");
  return `<div class="scroll"><table class="stages">${head}${firstRow}${rows}</table></div>`;
}

function pairBlock(pr, party, d) {
  const [a, b] = [pr.a, pr.b];
  const [lo, mid, hi] = pr.a_tcp;
  return `<div class="pair">
    <b>${esc(nameOf(d, a))}</b> <span class="muted">${esc(partyName(party[a]))}</span> v <b>${esc(nameOf(d, b))}</b> <span class="muted">${esc(partyName(party[b]))}</span>
    <span class="muted"> — final two in ${Math.round(100 * pr.p)}% of simulations</span>
    <div class="split"><span style="width:${mid}%;background:${m2colour(party[a])}"></span><span style="width:${100 - mid}%;background:${m2colour(party[b])}"></span></div>
    <table><tr><th></th><th>2CP (median)</th><th>p10–p90</th><th>Wins this pairing</th></tr>
      <tr><td>${esc(shortOf(d, a))}</td><td>${pct1(mid)}</td><td>${pct1(lo)}–${pct1(hi)}</td><td>${Math.round(100 * pr.p_a_wins)}%</td></tr>
      <tr><td>${esc(shortOf(d, b))}</td><td>${pct1(100 - mid)}</td><td>${pct1(100 - hi)}–${pct1(100 - lo)}</td><td>${Math.round(100 * (1 - pr.p_a_wins))}%</td></tr></table>
  </div>`;
}

function showForecastDistrict(name) {
  const d = fc().districts[name];
  if (!d) { panel.innerHTML = `<p class="neg">No forecast for ${esc(name)}.</p>`; return; }
  const party = Object.fromEntries(d.candidates.map((c) => [c.id, c.party]));
  const [w1, w2] = Object.keys(d.central.final);
  const centralFinal = d.central.final;
  panel.innerHTML = `
    <p><a class="link" id="back">← Victoria</a></p>
    <h2>${esc(name)} — 2026 forecast <span class="tag">${MODEL_TITLE[view]}</span></h2>
    <details open><summary>Chance of winning</summary>
      <table><tr><th>Candidate</th><th>Party</th><th>Primary</th><th>Final two</th><th>Win</th><th></th></tr>
      ${d.candidates.filter((c) => c.p_final_two > 0 || c.primary >= 2).map((c) => `<tr><td>${esc(nameOf(d, c.id))}${c.core ? "" : ' <span class="muted">minor</span>'}</td>
        <td><span class="swatch" style="background:${m2colour(c.party)}"></span>${esc(c.party)}</td><td>${pct1(c.primary)}</td><td>${Math.round(100 * c.p_final_two)}%</td>
        <td><b>${Math.round(100 * c.p_win)}%</b></td><td style="width:22%"><span class="bar" style="width:${100 * c.p_win}%;background:${m2colour(c.party)}"></span></td></tr>`).join("")}</table>
      <p class="muted">${view === "model1"
        ? `Primary = 2025 federal vote at this district's booths, restricted to the parties standing in 2026.${d.field && Object.keys(d.field.dropped).length ? ` Handed on by preference (no 2026 candidate): ${esc(Object.entries(d.field.dropped).map(([p, v]) => `${p} ${fmt(v)}`).join(", "))}.` : ""}${d.field && d.field.no_federal_vote.length ? ` Standing in 2026 with no federal vote here (so none in this model): ${esc(d.field.no_federal_vote.join(", "))}.` : ""}`
        : "Primary = mean simulated first-preference share for each declared 2026 candidate."}</p>
    </details>
    <details open><summary>Estimated two-candidate preferred</summary>
      ${d.pairs.map((p) => pairBlock(p, party, d)).join("")}
      <p class="muted">Each block is one possible final pair, with the 2CP split across the simulations where that pair was the final two.</p>
    </details>
    <details open><summary>Count stage by stage (central scenario)</summary>
      ${stagesTable(d)}
      <p class="muted">Mean primaries and central preference flows, every candidate excluded in turn (lowest first). Each cell is the running total
        (% of formal votes) with the votes received at that stage. Result: <b>${esc(shortOf(d, w1))} ${pct1(centralFinal[w1])}</b> v <b>${esc(shortOf(d, w2))} ${pct1(centralFinal[w2])}</b>.</p>
    </details>
    <details><summary>Who goes out, across simulations</summary>
      <table><tr><th>Order the serious candidates are excluded</th><th>Share</th></tr>
      ${d.orders.map((o) => `<tr><td>${o.order.map((c) => `<span class="swatch" style="background:${m2colour(party[c])}"></span>${esc(shortOf(d, c))}`).join(" → ")}</td><td>${Math.round(100 * o.p)}%</td></tr>`).join("")}</table>
      <p class="muted">${view === "model1" ? "The last two exclusions in each simulated count." : "Only core candidates are listed (minor candidates' votes are distributed first)."} The exclusion order decides three-way seats.</p>
    </details>`;
  document.getElementById("back").addEventListener("click", () => { clearDistrict(); forecastOverview(); });
}

async function setView(v) {
  view = v;
  const booth = v === "booths";
  document.getElementById("booth-controls").classList.toggle("hidden", !booth);
  document.getElementById("title").innerHTML = booth ? "2025 federal polling places &middot; Victorian state districts" : `2026 Victorian state election &middot; ${MODEL_TITLE[v]} forecast`;
  if (!booth) {
    try { await loadForecast(v); } catch (err) { panel.innerHTML = `<p class="neg">${esc(err.message)}</p>`; return; }
  }
  booth ? boothLayer.addTo(map) : map.removeLayer(boothLayer);
  districtLayer.setStyle(currentStyle);
  if (booth) updateLegend(document.getElementById("colour-by").value); else forecastLegend();
  if (selectedDistrict) selectDistrict(selectedDistrict); else (booth ? overview() : forecastOverview());
}

const currentStyle = (f) => (view === "booths" ? districtStyle(f) : forecastStyle(f));

function districtStyle(feature) {
  const sel = selectedDistrict === feature.properties.district;
  // Unselected districts are outline-only: filling 88 polygons on every redraw is a large share of zoom cost,
  // and canvas hit-testing (hover/click) works on the geometry, so no fill is needed to stay clickable.
  return { color: sel ? "#111827" : "#1f2937", weight: sel ? 4 : 2, opacity: sel ? 1 : 0.8, fill: sel, fillColor: "#60a5fa", fillOpacity: 0.15 };
}

// Hide everything outside Victoria: one opaque world-sized polygon with the state outline cut out as holes.
// Drawn on its own canvas (an SVG path with tens of thousands of points is rebuilt on every zoom and was the
// main source of dropped frames); the stroke draws the state border, the world edge is never on screen.
function maskOutsideVictoria(outline) {
  map.createPane("mask").style.zIndex = 350; // above tiles (200), below districts and booths (400)
  const world = [[-85, -180], [-85, 180], [85, 180], [85, -180]];
  L.polygon([world, ...outline], {
    pane: "mask", color: "#111827", weight: 3, fillColor: "#eef1f5", fillOpacity: 1, interactive: false,
    renderer: L.canvas({ pane: "mask" }),
  }).addTo(map);
}

function clearDistrict() {
  selectedDistrict = null;
  districtLayer.setStyle(currentStyle);
}

// Colour key for a flow-matrix group: independents (possibly disambiguated, e.g. "IND* RYAN") use the IND colour
const groupColour = (key, individual) => colour(individual ? "IND" : key);

function flowColumnHeader(c) {
  const names = c.individual ? `<br><span class="muted">${esc(c.candidates.map((s) => s.split(",")[0]).join(", "))}</span>` : "";
  const merged = c.merged ? ` <span class="merged">⚠ ${c.candidates.length} merged</span>` : "";
  return `<th title="${esc(c.candidates.join("\n"))}"><span class="swatch" style="background:${groupColour(c.key, c.individual)}"></span>${esc(c.key)}${merged}${names}</th>`;
}

function flowRowLabel(r) {
  if (r.key === "FIRST") return `<td title="${esc(r.candidates.join("\n"))}"><i>Finalists' own votes</i></td>`;
  let extra = "";
  if (r.individual) {
    extra = r.merged
      ? ` <span class="merged">⚠ ${r.candidates.length} merged</span><br><span class="muted">${esc(r.candidates.join("; "))}</span>`
      : `<br><span class="muted">${esc(r.candidates[0] || "")}</span>`;
  }
  return `<td title="${esc(r.candidates.join("\n"))}"><span class="swatch" style="background:${groupColour(r.key, r.individual)}"></span>${esc(r.label)}${r.individual ? "" : ` <span class="muted">${esc(r.key)}</span>`}${extra}</td>`;
}

function flowMatrix(m) {
  if (!m.total) return '<p class="muted">No polling places counted.</p>';
  return `<div class="scroll"><table class="flows">
    <tr><th>From \\ to</th>${m.columns.map(flowColumnHeader).join("")}<th>Votes</th></tr>
    ${m.rows.map((r) => `<tr class="${r.key === "FIRST" ? "first" : ""}">${flowRowLabel(r)}${r.votes.map((v, i) => v == null
      ? '<td class="na" title="Not in the final two where these votes were counted">—</td>'
      : `<td>${fmt(v)}<br><span class="muted">${r.pct[i].toFixed(1)}%</span></td>`).join("")}<td>${fmt(r.total)}</td></tr>`).join("")}
    <tr class="total"><td><b>Total (2CP)</b></td>${m.columns.map((c) => `<td><b>${fmt(c.votes)}</b><br><span class="muted">${c.pct.toFixed(1)}%</span></td>`).join("")}<td><b>${fmt(m.total)}</b></td></tr>
  </table></div>`;
}

function flowSection(f) {
  if (!f || !f.total) return '<p class="muted">No polling places counted in this district.</p>';
  const pairNote = f.pairs.length > 1
    ? `<p class="note">These booths come from ${f.pairs.length} different final-two pairings (${f.pairs.map((p) => `${esc(p.pair)}: ${p.share.toFixed(1)}%`).join(", ")}).
       The combined matrix adds them all up; each pairing is also shown on its own below.</p>` : "";
  return `
    <p class="muted">${f.booths} polling places, ${fmt(f.total)} ordinary votes (${f.pre_poll_share.toFixed(1)}% at pre-poll centres). Votes are summed across booths,
      so every booth and federal division counts in proportion to its votes.</p>
    <table><tr><th>Federal division</th><th>Booths</th><th>Votes</th><th>Share</th><th>Final two</th></tr>
      ${f.divisions.map((d) => `<tr><td>${esc(d.division)}</td><td>${d.booths}</td><td>${fmt(d.votes)}</td><td>${d.share.toFixed(1)}%</td><td>${esc(d.pair)}</td></tr>`).join("")}</table>
    ${pairNote}
    <h3>All booths combined</h3>
    ${flowMatrix(f)}
    ${Object.entries(f.by_pair || {}).map(([p, m]) => `<details><summary>Final two: ${esc(p)} (${fmt(m.total)} votes)</summary>${flowMatrix(m)}</details>`).join("")}
    <p class="muted">Each row shows where one group's ballots went between the final two. <b>*</b> Independents are individual candidates, pooled into one
      group for now; <span class="merged">⚠ n merged</span> marks where several different independents were combined. <b>—</b> means that party was not in the
      final two at any booth where the row's votes were counted. Declaration votes and booths far outside their own division are not included.</p>`;
}

async function selectDistrict(name, zoom = false) {
  selectedDistrict = name;
  districtLayer.setStyle(currentStyle);
  let layer;
  districtLayer.eachLayer((l) => { if (l.feature.properties.district === name) layer = l; });
  if (!layer) return;
  if (zoom) map.fitBounds(layer.getBounds(), { maxZoom: 13 });
  if (view !== "booths") return showForecastDistrict(name);
  const p = layer.feature.properties;
  const here = booths.filter((b) => b.district === name).sort((a, b) => b.votes - a.votes);
  const counted = here.filter((b) => b.counted), notCounted = here.filter((b) => !b.counted);
  const v = p.vec2022;
  const finalTotal = v.final.reduce((a, c) => a + c.votes, 0);
  const boothRows = (list) => list.map((b) => `<tr><td><a class="link" data-booth="${b.id}">${esc(b.name)}</a></td><td>${esc(b.div)}</td><td>${fmt(b.votes)}</td><td>${b.share.ON.toFixed(1)}</td></tr>`).join("");
  panel.innerHTML = `
    <p><a class="link" id="back">← Victoria</a></p>
    <h2>${esc(name)}</h2>
    <p><span class="tag">${esc(p.region)} Region</span><span class="tag">${p.booths} polling places counted</span></p>
    <details open><summary>2025 federal vote at polling places in this district</summary>
      <p class="muted">${fmt(p.votes)} ordinary formal votes at the counted booths (declaration votes excluded).</p>
      <table>${shareBars(p.share)}</table>
    </details>
    <details open><summary>Preference flows (2025 federal, collated)</summary><div id="flows"><p class="muted">Loading…</p></div></details>
    <details><summary>2022 state result (VEC)</summary>
      <p>Elected: <b>${esc(v.winner)}</b> <span class="muted">${esc(v.party)}</span></p>
      <table><tr><th>Final count</th><th>Votes</th><th>%</th></tr>${v.final.map((c) => `<tr><td>${esc(c.name)} <span class="muted">${esc(c.party)}</span></td><td>${fmt(c.votes)}</td><td>${(100 * c.votes / finalTotal).toFixed(1)}</td></tr>`).join("")}</table>
      <p class="muted">${fmt(v.formal)} formal votes.</p>
    </details>
    <details><summary>Polling places counted (${counted.length})</summary>
      <table><tr><th>Polling place</th><th>Federal division</th><th>Votes</th><th>ON %</th></tr>${boothRows(counted)}</table>
    </details>
    ${notCounted.length ? `<details><summary>Located here but not counted (${notCounted.length})</summary>
      <p class="muted">These booths sit inside ${esc(name)} but serve voters of a federal division whose boundary is more than 1 km away (mostly pre-poll centres and CBD booths), so their voters live elsewhere.</p>
      <table><tr><th>Polling place</th><th>Federal division</th><th>Votes</th><th>ON %</th></tr>${boothRows(notCounted)}</table>
    </details>` : ""}`;
  document.getElementById("back").addEventListener("click", () => { clearDistrict(); overview(); });
  bindLinks();
  const flows = await loadFlows();
  const target = document.getElementById("flows");
  if (target && selectedDistrict === name) target.innerHTML = flowSection(flows.districts[name]);
}

async function init() {
  const [districts, boothData, outline] = await Promise.all([
    fetch("data/districts.geojson").then((r) => r.json()),
    fetch("data/booths.json").then((r) => r.json()),
    fetch("data/victoria_outline.json").then((r) => r.json()),
  ]);
  booths = boothData;
  maskOutsideVictoria(outline);
  districtLayer = L.geoJSON(districts, {
    style: currentStyle,
    onEachFeature: (f, layer) => {
      layer.bindTooltip((l) => (view !== "booths" ? forecastTooltip(l) : `<b>${esc(f.properties.district)}</b><br><span class="muted">${esc(f.properties.region)}</span>`), { sticky: true });
      layer.on("click", () => selectDistrict(f.properties.district));
    },
  }).addTo(map);
  const vic = districtLayer.getBounds();
  map.fitBounds(vic);
  map.setMinZoom(map.getZoom());
  map.setMaxBounds(vic.pad(0.15));
  map.options.maxBoundsViscosity = 1.0;
  renderBooths();
  overview();

  const list = document.getElementById("search-list");
  list.innerHTML = [...districts.features.map((f) => f.properties.district).map((n) => `<option value="${esc(n)} (district)">`),
    ...booths.map((b) => `<option value="${esc(b.name)} — ${esc(b.div)}">`)].join("");
  document.getElementById("search").addEventListener("change", (e) => {
    const q = e.target.value;
    if (q.endsWith(" (district)")) return selectDistrict(q.replace(" (district)", ""), true);
    const b = booths.find((x) => `${x.name} — ${x.div}` === q);
    if (b) showBooth(b, true);
  });
  document.getElementById("colour-by").addEventListener("change", renderBooths);
  document.getElementById("show-ppvc").addEventListener("change", renderBooths);
  const viewSelect = document.getElementById("view");
  viewSelect.addEventListener("change", () => setView(viewSelect.value));
  // Deep links: #model1 / #model2 open a forecast view, #model2/<District> also selects a district
  const m = location.hash.match(/^#(model[12])(?:\/(.+))?$/);
  if (m) {
    viewSelect.value = m[1];
    setView(m[1]).then(() => { if (m[2]) selectDistrict(decodeURIComponent(m[2]), true); });
  }
}

init().catch((err) => { panel.innerHTML = `<p class="neg">Failed to load data: ${esc(err)}. Run scripts/build_visualiser.py and serve this folder over HTTP.</p>`; });
