"use strict";
/* projections.html — 2026 forecast: bloc headline, favourite-party map, per-district panel. */

const MODEL_TITLE = { model1: "Baseline Model", model2: "Forecast Model (state baseline)", model2fed: "Forecast Model (federal baseline)" };
const BLOC_ORDER = ["COAL", "ALP", "ON", "GRN", "IND*"];

let view = "model2";
let forecasts = {};
let regionFilter = null;
let selected = null;
let districtLayer = null;
let snapDate = null;           // null = latest forecast
let tl = null;                 // shared timeline-slider widget
let approx = false;            // slider strictly between marks
const snapDocs = {};           // view -> {date -> forecast doc}

const TIMELINE_VIEWS = new Set(["model2", "model2fed"]);
const fc = () => (TIMELINE_VIEWS.has(view) && snapDate && snapDocs[view]?.[snapDate]) || forecasts[view];
const nameOf = (d, id) => (d.candidates.find((c) => c.id === id)?.name) || id;
const shortOf = (d, id) => dispName(nameOf(d, id).split(",")[0]);

const loadForecast = async (model) => (forecasts[model] ||= await fetch(`/data/${model}_vic2026.json`).then((r) => {
  if (!r.ok) throw new Error(`data/${model}_vic2026.json missing; run scripts/build_site.py`);
  return r.json();
}));

const loadSnapshot = async (date) => ((snapDocs[view] ||= {})[date] ||= await fetch(`/data/snapshots/${view}/${date}.json`).then((r) => {
  if (!r.ok) throw new Error(`data/snapshots/${view}/${date}.json missing; run scripts/build_site.py`);
  return r.json();
}));

function favourite(name) {
  if (timeline && tl) {
    const row = blendedRow(name);
    return row ? row.reduce((a, c) => (c.p_win > a.p_win ? c : a)) : null;
  }
  const d = fc() && fc().districts[name];
  return d ? d.candidates.reduce((a, c) => (c.p_win > a.p_win ? c : a)) : null;
}

function forecastStyle(feature) {
  const name = feature.properties.district;
  const sel = selected === name;
  const dim = regionFilter && feature.properties.region !== regionFilter;
  const fav = favourite(name);
  // Darker = the favourite is more likely to win; faint below ~30%.
  const strength = fav ? Math.max(0.15, Math.min(0.85, (fav.p_win - 0.3) / 0.7 * 0.85)) : 0;
  return {
    color: sel ? "#0f172a" : "#334155",
    weight: sel ? 3 : 1,
    lineJoin: "round",
    opacity: dim ? 0.3 : 0.9,
    fillColor: fav ? pcolour(fav.party) : "#cbd5e1",
    fillOpacity: dim ? 0.05 : strength,
  };
}

function forecastTooltip(layer) {
  const name = layer.feature.properties.district;
  if (timeline && tl) {
    const row = blendedRow(name);
    if (!row) return `<b>${esc(name)}</b>`;
    const top = [...row].sort((a, b) => b.p_win - a.p_win).filter((c) => c.p_win >= 0.01).slice(0, 3);
    const approxMark = approx ? "≈" : "";
    return `<b>${esc(name)}</b><br>${top.map((c) => `<span class="swatch" style="background:${pcolour(c.party)}"></span>${esc(pname(c.party))} ${approxMark}${Math.round(100 * c.p_win)}%`).join("<br>")}`;
  }
  const d = fc() && fc().districts[name];
  if (!d) return `<b>${esc(name)}</b>`;
  const top = [...d.candidates].sort((a, b) => b.p_win - a.p_win).filter((c) => c.p_win >= 0.01).slice(0, 3);
  return `<b>${esc(name)}</b><br>${top.map((c) => `<span class="swatch" style="background:${pcolour(c.party)}"></span>${esc(pname(c.party))} ${Math.round(100 * c.p_win)}%`).join("<br>")}`;
}

/* ---------- headline ---------- */

function renderHeadline() {
  const m = fc().meta;
  document.getElementById("run-desc").textContent = m.description;
  const commit = m.git_commit ? ` · commit ${m.git_commit.slice(0, 7)}` : "";
  document.getElementById("run-meta").textContent =
    `${fmt(m.runs)} simulations · run ${m.run_id} · ${(m.timestamp || "").slice(0, 10)}${commit}`;
  document.getElementById("caveat-meta").innerHTML =
    `<b>Run:</b> ${esc(m.run_id)}, forecast dated ${esc((m.timestamp || "").slice(0, 10))}${m.git_commit ? `, commit <span class="mono">${esc(m.git_commit.slice(0, 7))}</span>` : ""}.`;
  document.getElementById("map-sub").textContent = `(${MODEL_TITLE[view]})`;

  const blocs = Object.fromEntries(fc().blocs.map((b) => [b.party, b]));
  const parts = Object.fromEntries(fc().seats.map((s) => [s.party, s]));
  const coalNote = parts.LP && parts.NP ? `Liberal ${parts.LP.seats_mean.toFixed(1)} + Nationals ${parts.NP.seats_mean.toFixed(1)}` : "";
  document.getElementById("bloc-cards").innerHTML = BLOC_ORDER.filter((g) => blocs[g]).map((g) => {
    const b = blocs[g];
    return `<div class="card bloc-card" style="border-top-color:${pcolour(g)}">
      <div class="party-l" style="font-size:0.6875rem;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;color:var(--ink-2)">${esc(pname(g))}</div>
      <div style="display:flex;align-items:baseline;gap:0.5rem;margin:0.25rem 0"><b class="num" style="font-size:2.25rem;letter-spacing:-0.02em">${b.seats_mean.toFixed(1)}</b>
        <span class="range num">p10-p90: ${Math.round(b.seats_p10)}-${Math.round(b.seats_p90)}</span></div>
      <div class="pmaj">${b.p_majority > 0.005 ? `${Math.round(100 * b.p_majority)}% chance of a majority` : "&nbsp;"}</div>
      ${g === "COAL" && coalNote ? `<div class="range">${esc(coalNote)}</div>` : ""}
    </div>`;
  }).join("");

  const order = BLOC_ORDER.filter((g) => blocs[g]);
  document.getElementById("majbar").innerHTML =
    order.map((g) => `<div class="seg" style="width:${100 * blocs[g].seats_mean / 88}%;background:${pcolour(g)}" title="${esc(pname(g))} ${blocs[g].seats_mean.toFixed(1)}"></div>`).join("")
    + `<div class="needle" data-label="${m.majority} to govern" style="left:${100 * m.majority / 88}%"></div>`;
  document.getElementById("maj-legend").innerHTML =
    order.map((g) => `<span><span class="swatch" style="background:${pcolour(g)}"></span>${esc(pname(g))} <b class="num">${blocs[g].seats_mean.toFixed(1)}</b></span>`).join("");
}

/* ---------- statewide panel (default) ---------- */

function overview() {
  const m = fc().meta;
  const banner = snapBannerHTML();
  const close = Object.entries(fc().districts)
    .map(([n, d]) => [n, favourite(n)])
    .filter(([, f]) => f && f.p_win < 0.6)
    .sort((a, b) => a[1].p_win - b[1].p_win);
  document.getElementById("panel-title").textContent = "Victoria overview";
  document.getElementById("dpanel").innerHTML = `
    ${banner}
    ${m.polls ? `<h4>Primary vote and expected seats</h4>
      <table><tr><th>Party</th><th class="r">Primary</th><th class="r">Expected seats</th></tr>
      ${Object.entries(m.polls).map(([k, v]) => {
        const seats = k === "OTH"
          ? fc().blocs.filter((b) => !["COAL", "ALP", "ON", "GRN"].includes(b.party)).reduce((a, b) => a + b.seats_mean, 0)
          : (fc().blocs.find((b) => b.party === (k === "LNP" ? "COAL" : k)) || { seats_mean: 0 }).seats_mean;
        return `<tr><td><span class="swatch" style="background:${pcolour(k)}"></span>${esc({ LNP: "Coalition", OTH: "Others" }[k] || pname(k))}</td><td class="r num">${pct1(v)}</td><td class="r num"><b>${seats.toFixed(1)}</b></td></tr>`;
      }).join("")}</table>
      <p class="muted small">Primary = polling average used by the Forecast Model. Expected seats = mean across ${fmt(m.runs)} simulations (${m.majority} needed for a majority).</p>
      <p class="muted small">Each pollster&rsquo;s latest eligible poll within 35 days of the newest: ${esc((m.polls_used || []).join("; "))}. Source: electiontracker.au.</p>` : ""}
    <h4>Closest seats (${close.length} with no candidate above 60%)</h4>
    <table><tr><th>District</th><th>Favourite</th><th class="r">Chance</th></tr>
      ${close.map(([n, f]) => `<tr><td><a class="back-link" data-d="${esc(n)}">${esc(n)}</a></td>
        <td><span class="swatch" style="background:${pcolour(f.party)}"></span>${esc(pname(f.party))}</td>
        <td class="r num">${Math.round(100 * f.p_win)}%</td></tr>`).join("")}</table>
    <p class="muted small">Click a district for its count stage by stage and the estimated two-candidate result.</p>`;
  bindDistrictLinks();
}

function bindDistrictLinks() {
  document.querySelectorAll("[data-d]").forEach((a) => a.addEventListener("click", () => selectDistrict(a.dataset.d, true)));
}

/* ---------- district panel ---------- */

function stagesTable(d) {
  const cands = d.candidates.map((c) => c.id);
  const party = Object.fromEntries(d.candidates.map((c) => [c.id, c.party]));
  const first = Object.fromEntries(d.candidates.map((c) => [c.id, c.primary]));
  const out = new Set();
  const head = `<tr><th>Stage</th>${cands.map((c) => `<th title="${esc(nameOf(d, c))} (${esc(pname(party[c]))})"><span class="swatch" style="background:${pcolour(party[c])}"></span>${esc(shortOf(d, c))}</th>`).join("")}</tr>`;
  const firstRow = `<tr><td>First prefs</td>${cands.map((c) => `<td class="num">${pct1(first[c])}</td>`).join("")}</tr>`;
  const rows = d.central.stages.map((s, i) => {
    const gone = new Set(s.excluded);
    const last = i === d.central.stages.length - 1;
    const cells = cands.map((c) => {
      if (gone.has(c)) { out.add(c); return '<td class="out">out</td>'; }
      if (out.has(c)) return '<td class="out"></td>';
      const t = s.transfers[c] || 0;
      return `<td class="num">${pct1(s.totals[c])}${t ? `<br><span class="pos">+${t.toFixed(1)}</span>` : ""}</td>`;
    }).join("");
    const label = s.excluded.length > 1 ? `${s.excluded.length} minor candidates` : `${esc(shortOf(d, s.excluded[0]))} <span class="muted">${esc(pname(party[s.excluded[0]]))}</span>`;
    return `<tr class="${last ? "final" : ""}"><td>${i + 1}. ${label} excluded (${s.pile.toFixed(1)})</td>${cells}</tr>`;
  }).join("");
  return `<div class="scroll"><table>${head}${firstRow}${rows}</table></div>`;
}

function pairBlock(pr, party, d) {
  const [a, b] = [pr.a, pr.b];
  const [lo, mid, hi] = pr.a_tcp;
  return `<div class="pair">
    <b>${esc(dispName(nameOf(d, a)))}</b> <span class="muted">${esc(pname(party[a]))}</span> v
    <b>${esc(dispName(nameOf(d, b)))}</b> <span class="muted">${esc(pname(party[b]))}</span>
    <div class="muted">final two in ${Math.round(100 * pr.p)}% of simulations</div>
    <div class="split"><span style="width:${mid}%;background:${pcolour(party[a])}"></span><span style="width:${100 - mid}%;background:${pcolour(party[b])}"></span></div>
    <table><tr><th></th><th>2CP median</th><th>p10-p90</th><th>Wins pairing</th></tr>
      <tr><td>${esc(shortOf(d, a))}</td><td class="num">${pct1(mid)}</td><td class="num">${pct1(lo)}-${pct1(hi)}</td><td class="num">${Math.round(100 * pr.p_a_wins)}%</td></tr>
      <tr><td>${esc(shortOf(d, b))}</td><td class="num">${pct1(100 - mid)}</td><td class="num">${pct1(100 - hi)}-${pct1(100 - lo)}</td><td class="num">${Math.round(100 * (1 - pr.p_a_wins))}%</td></tr></table>
  </div>`;
}

function showDistrict(name) {
  const d = fc().districts[name];
  if (!d) { document.getElementById("dpanel").innerHTML = `<p class="neg">No forecast for ${esc(name)}.</p>`; return; }
  document.getElementById("panel-title").textContent = name;
  const party = Object.fromEntries(d.candidates.map((c) => [c.id, c.party]));
  const [w1, w2] = Object.keys(d.central.final);
  document.getElementById("dpanel").innerHTML = `
    ${snapBannerHTML()}
    <p><a class="back-link" id="d-back">← Victoria overview</a> ·
       <a href="/districts/${districtSlug(name)}/">District page →</a></p>
    <h4>Chance of winning</h4>
    <table><tr><th>Candidate</th><th>Party</th><th class="r">Primary</th><th class="r">Final two</th><th class="r">Win</th><th style="width:18%"></th></tr>
      ${d.candidates.filter((c) => c.p_final_two > 0 || c.primary >= 2).sort((a, b) => Math.round(100 * b.p_win) - Math.round(100 * a.p_win) || b.primary - a.primary).map((c) => `<tr>
        <td>${esc(dispName(nameOf(d, c.id)))}${c.core ? "" : ' <span class="muted">minor</span>'}</td>
        <td><span class="swatch" style="background:${pcolour(c.party)}"></span>${esc(c.party)}</td>
        <td class="r num">${pct1(c.primary)}</td><td class="r num">${Math.round(100 * c.p_final_two)}%</td>
        <td class="r num"><b>${Math.round(100 * c.p_win)}%</b></td>
        <td><span class="bar"><i style="width:${(100 * c.p_win).toFixed(0)}%;background:${pcolour(c.party)}"></i></span></td></tr>`).join("")}</table>
    <p class="muted small">${view === "model1"
      ? `Primary = 2025 federal vote at this district&rsquo;s booths, restricted to parties standing in 2026.${d.field && Object.keys(d.field.dropped).length ? ` Handed on by preference (no 2026 candidate): ${esc(Object.entries(d.field.dropped).map(([p, v]) => `${p} ${fmt(v)}`).join(", "))}.` : ""}${d.field && d.field.no_federal_vote.length ? ` Standing in 2026 with no federal vote here: ${esc(d.field.no_federal_vote.join(", "))}.` : ""}`
      : "Primary = mean simulated first-preference share for each declared 2026 candidate."}</p>
    <h4>Estimated two-candidate preferred</h4>
    ${d.pairs.map((p) => pairBlock(p, party, d)).join("")}
    <p class="muted small">Each block is one possible final pair, with the 2CP split across the simulations where that pair was the final two.</p>
    <h4>Count stage by stage (central scenario)</h4>
    ${stagesTable(d)}
    <p class="muted small">Mean primaries and central preference flows, every candidate excluded in turn (lowest first).
      Result: <b>${esc(shortOf(d, w1))} ${pct1(d.central.final[w1])}</b> v <b>${esc(shortOf(d, w2))} ${pct1(d.central.final[w2])}</b>.</p>
    <details><summary>Who goes out, across simulations</summary>
      <table><tr><th>Exclusion order of the serious candidates</th><th class="r">Share</th></tr>
      ${d.orders.map((o) => `<tr><td>${o.order.map((c) => `<span class="swatch" style="background:${pcolour(party[c])}"></span>${esc(shortOf(d, c))}`).join(" → ")}</td><td class="r num">${Math.round(100 * o.p)}%</td></tr>`).join("")}</table>
      <p class="muted small">${view === "model1" ? "The last two exclusions in each simulated count." : "Only core candidates are listed (minor candidates&rsquo; votes are distributed first)."}</p>
    </details>`;
  document.getElementById("d-back").addEventListener("click", clearDistrict);
}

function selectDistrict(name, zoom = false) {
  if (!fc().districts[name]) return;
  selected = name;
  districtLayer.setStyle(forecastStyle);
  if (zoom) {
    let layer;
    districtLayer.eachLayer((l) => { if (l.feature.properties.district === name) layer = l; });
    if (layer) map.flyToBounds(layer.getBounds(), { maxZoom: 11, duration: 0.6 });
  }
  showDistrict(name);
  syncHash();
}

function clearDistrict() {
  selected = null;
  districtLayer.setStyle(forecastStyle);
  syncHash();
  overview();
}

function syncHash() {
  let h = `#${view}`;
  if (selected) h += `/${encodeURIComponent(selected)}`;
  if (TIMELINE_VIEWS.has(view) && snapDate) h += `@${snapDate}`;
  history.replaceState(null, "", h);
}

function renderChips(regions) {
  const box = document.getElementById("region-chips");
  box.innerHTML = "";
  const mk = (label, value) => {
    const b = document.createElement("button");
    b.className = "fchip" + (value === regionFilter ? " on" : "");
    b.textContent = label;
    b.addEventListener("click", () => {
      regionFilter = value === regionFilter ? null : value;
      renderChips(regions);
      districtLayer.setStyle(forecastStyle);
    });
    box.appendChild(b);
  };
  mk("All regions", null);
  regions.forEach((r) => mk(r.replace(/ Metropolitan| Victoria/, (m) => (m.includes("Victoria") ? " Vic" : " Metro")), r));
}

function renderLegend() {
  const parties = [...new Set(Object.keys(fc().districts).map((n) => favourite(n).party))]
    .sort((a, b) => BLOC_ORDER.indexOf(a) - BLOC_ORDER.indexOf(b));
  document.getElementById("map-legend").innerHTML =
    parties.map((p) => `<span><span class="swatch" style="background:${pcolour(p)}"></span>${esc(pname(p))}</span>`).join("")
    + '<span class="muted">Darker = more likely</span>';
}

/* ---------- forecast history (snapshots) ---------- */

function snapBannerHTML() {
  if (!TIMELINE_VIEWS.has(view) || !snapDate) return "";
  const m = fc().meta;
  if (m.retrospective) {
    return `<div class="snap-banner"><b>Retrospective estimate for polls to ${esc(fmtSnapDate(snapDate))}</b>. Generated ${esc(fmtSnapDate(m.generated))} using only polls published by that date (fieldwork ended &ge;2 days earlier). Candidate list and model settings are the final November versions, so this is not a forecast we published on ${esc(fmtSnapDate(snapDate))}.</div>`;
  }
  return `<div class="snap-banner"><b>Forecast as published on ${esc(fmtSnapDate(snapDate))}</b></div>`;
}

function updateSnapBanner() {
  const hero = document.getElementById("snap-banner");
  if (!hero) return;
  const b = snapBannerHTML();
  hero.innerHTML = b;
  hero.hidden = !b;
}

let benchPromise = null;

function updateFedBanner() {
  const el = document.getElementById("fed-banner");
  if (!el) return;
  el.hidden = view !== "model2fed";
  if (view !== "model2fed") { el.innerHTML = ""; return; }
  benchPromise ||= fetch("/data/benchmarks.json").then((r) => r.json());
  benchPromise.then((b) => {
    if (view !== "model2fed") return;
    const sum = (rows) => rows.filter((r) => r.raw_seat_count !== "")
      .reduce((a, r) => ({ se: a.se + +r.raw_seat_count, d: a.d + +r.districts }), { se: 0, d: 0 });
    const fed = sum(b.forecast_fed_backtests), st = sum(b.forecast_backtests);
    el.innerHTML = `<div class="snap-banner"><b>You are viewing the Forecast Model with a federal baseline.</b>
      It scored worse than the default forecast on past elections (${fed.se} of ${fed.d} seats right,
      against ${st.se}), so treat it as a comparison only.
      <a href="/#model2">Back to the main forecast</a> &middot;
      <a href="/methodology/forecast/#benchmarks">Benchmark details</a></div>`;
  });
}

/* ---------- blended map timeline (shared widget in common.js) ---------- */

let timeline = null;          // current view's map timeline
const timelines = {};         // view -> /data/snapshots/.../map_timeline.json

/* Interpolated p_win per candidate for one district at the slider position. */
function blendedRow(name) {
  const td = timeline && timeline.districts[name];
  if (!td || !tl) return null;
  const pds = tl.pdays;
  const t = tl.t;
  let i = pds.length - 1;
  if (t < pds[i]) { i = 0; while (pds[i + 1] < t) i++; }
  const j = Math.min(i + 1, pds.length - 1);
  const span = pds[j] - pds[i];
  const f = span ? (t - pds[i]) / span : 0;
  return td.cands.map((c, k) => ({ id: c[0], party: c[1], p_win: td.p[i][k] + (td.p[j][k] - td.p[i][k]) * f }));
}

/* Cards/bar/panels always show a real mark (most recent at or before the slider);
   refetch/re-render only when that mark changes. */
async function onTimelineMark(mark) {
  const p = timeline.points[mark];
  snapDate = p.latest ? null : p.date;
  if (snapDate) await loadSnapshot(snapDate);
  renderHeadline();
  renderLegend();
  if (selected && fc().districts[selected]) showDistrict(selected);
  else overview();
  syncHash();
  updateSnapBanner();
}

async function setView(v, keepDistrict, date) {
  view = v;
  document.getElementById("btn-model1").classList.toggle("on", v === "model1");
  document.getElementById("btn-model2").classList.toggle("on", v === "model2");
  const snapUI = document.getElementById("snap-ui");
  await loadForecast(v);
  timeline = TIMELINE_VIEWS.has(v) ? timelines[v] : null;
  if (snapUI) snapUI.hidden = !timeline;
  if (timeline && snapUI) {
    tl = timelineSlider(snapUI, timeline.points, {
      noteText: "Marks are model runs; the map blends between them.",
      onBlend: (t, mark, frac) => { approx = frac > 0; districtLayer.setStyle(forecastStyle); },
      onMark: onTimelineMark,
    });
    const i = date ? timeline.points.findIndex((p) => p.date === date) : -1;
    if (i >= 0) tl.setMark(i); else tl.setDay(tl.totalDays);
  } else {
    tl = null;
    snapDate = null;
  }
  updateFedBanner();
  renderHeadline();
  districtLayer.setStyle(forecastStyle);
  renderLegend();
  if (keepDistrict && fc().districts[keepDistrict]) selectDistrict(keepDistrict);
  else { selected = null; overview(); syncHash(); }
}

async function init() {
  const [districts, outline] = await Promise.all([
    fetch("/data/districts.geojson").then((r) => r.json()),
    fetch("/data/victoria_outline.json").then((r) => r.json()),
  ]);
  const map = L.map("pmap", { preferCanvas: true, zoomSnap: 0.5, attributionControl: false, maxZoom: 14 });
  window.map = map;
  map.createPane("mask").style.zIndex = 350;
  const world = [[-85, -180], [-85, 180], [85, 180], [85, -180]];
  L.polygon([world, ...outline], {
    pane: "mask", color: "#0f172a", weight: 2.5, fillColor: "#eef1f5", fillOpacity: 1, interactive: false, smoothFactor: 0,
    renderer: L.canvas({ pane: "mask" }),
  }).addTo(map);
  districtLayer = L.geoJSON(districts, {
    smoothFactor: 0,
    style: forecastStyle,
    onEachFeature: (f, layer) => {
      layer.bindTooltip(() => forecastTooltip(layer), { sticky: true });
      layer.on("click", () => selectDistrict(f.properties.district));
    },
  }).addTo(map);
  const vic = districtLayer.getBounds();
  map.fitBounds(vic);
  map.setMinZoom(map.getZoom());
  map.setMaxBounds(vic.pad(0.2));
  map.options.maxBoundsViscosity = 1.0;

  renderChips([...new Set(districts.features.map((f) => f.properties.region))].sort());
  document.getElementById("district-list").innerHTML =
    districts.features.map((f) => `<option value="${esc(f.properties.district)}">`).join("");
  document.getElementById("search").addEventListener("change", (e) => {
    if (fc() && fc().districts[e.target.value]) selectDistrict(e.target.value, true);
  });
  document.getElementById("btn-model1").addEventListener("click", () => setView("model1", selected));
  document.getElementById("btn-model2").addEventListener("click", () => setView("model2", selected));

  timelines.model2 = await fetch("/data/snapshots/map_timeline.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  timelines.model2fed = await fetch("/data/snapshots/model2fed/map_timeline.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);

  // #model2, #model2@2026-10-13, #model2/Kew, #model2fed, #model2fed/Kew, #Kew, #model1...
  const m = location.hash.match(/^#(model2fed|model[12])?(?:\/([^@/]+))?(?:@(\d{4}-\d{2}-\d{2}))?$/)
    || location.hash.match(/^#([^@/]+)$/);
  let [, vm, dist, date] = m || [];
  if (vm && !vm.startsWith("model")) { dist = vm; vm = "model2"; }
  if (vm === "model1") await setView("model1", dist ? decodeURIComponent(dist) : null);
  else if (vm === "model2fed") await setView("model2fed", dist ? decodeURIComponent(dist) : null, date);
  else await setView("model2", dist ? decodeURIComponent(dist) : null, date);
}

init().catch((e) => {
  document.getElementById("dpanel").innerHTML = `<p class="neg">Failed to load data: ${esc(e)}. Run scripts/build_site.py and serve site/ over HTTP.</p>`;
});
