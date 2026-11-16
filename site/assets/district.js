"use strict";
/* district page — forecast-history timeline: outline blends between snapshot
   marks; the tables/figures always show a real mark. Data is inline in
   #district-timeline (written by build_site.py). */

const DTL = JSON.parse(document.getElementById("district-timeline").textContent);
const POINTS = DTL.points;
const CANDS = DTL.district.cands;
const ROWS = DTL.district.rows;
const N = POINTS.length - 1; // index of Latest
const dpath = document.getElementById("dtl-path");
const strength = (p) => Math.max(0.15, Math.min(0.85, (p - 0.3) / 0.7 * 0.85));
const nameOf = (id) => dispName(id);
const shortOf = (id) => dispName(id.split(",")[0]);

/* Interpolated [primary, p_final_two, p_win] per candidate at (mark, frac). */
function blendC(i, frac) {
  const a = ROWS[i].c;
  const b = ROWS[Math.min(i + 1, N)].c;
  return a.map((row, k) => row.map((v, j) => v + (b[k][j] - v) * frac));
}

function paintOutline(c) {
  const fav = c.reduce((best, row, k) => (row[2] > best[2] ? row : best), c[0]);
  const k = c.indexOf(fav);
  dpath.setAttribute("fill", pcolour(CANDS[k].party));
  dpath.setAttribute("fill-opacity", strength(fav[2]).toFixed(3));
}

function bannerHTML(i) {
  const p = POINTS[i];
  if (p.latest) return "";
  if (p.retrospective) {
    return `<div class="snap-banner"><b>Retrospective estimate for polls to ${esc(fmtSnapDate(p.date))}</b> — generated ${esc(fmtSnapDate(p.generated))} using only polls published by that date (fieldwork ended &ge;2 days earlier). Candidate list and model settings are the final November versions, so this is not a forecast we published on ${esc(fmtSnapDate(p.date))}.</div>`;
  }
  return `<div class="snap-banner"><b>Forecast as published on ${esc(fmtSnapDate(p.date))}</b></div>`;
}

function pairHTML(pr) {
  const party = Object.fromEntries(CANDS.map((c) => [c.id, c.party]));
  const [lo, mid, hi] = pr.a_tcp;
  return `<div class="pair">
    <b>${esc(nameOf(pr.a))}</b> <span class="muted">${esc(pname(party[pr.a]))}</span> v
    <b>${esc(nameOf(pr.b))}</b> <span class="muted">${esc(pname(party[pr.b]))}</span>
    <div class="muted">final two in ${Math.round(100 * pr.p)}% of simulations</div>
    <div class="split"><span style="width:${mid}%;background:${pcolour(party[pr.a])}"></span><span style="width:${100 - mid}%;background:${pcolour(party[pr.b])}"></span></div>
    <table><tr><th></th><th>2CP median</th><th>p10&#8211;p90</th><th>Wins pairing</th></tr>
      <tr><td>${esc(shortOf(pr.a))}</td><td class="num">${pct1(mid)}</td><td class="num">${pct1(lo)}&#8211;${pct1(hi)}</td><td class="num">${Math.round(100 * pr.p_a_wins)}%</td></tr>
      <tr><td>${esc(shortOf(pr.b))}</td><td class="num">${pct1(100 - mid)}</td><td class="num">${pct1(100 - hi)}&#8211;${pct1(100 - lo)}</td><td class="num">${Math.round(100 * (1 - pr.p_a_wins))}%</td></tr></table>
  </div>`;
}

function showMark(i) {
  const p = POINTS[i];
  const row = ROWS[i].c;
  const ordered = CANDS.map((c, k) => ({ ...c, v: row[k] }))
    .filter((c) => c.v[1] > 0 || c.v[0] >= 2 || c.v[2] > 0)
    .sort((a, b) => Math.round(100 * b.v[2]) - Math.round(100 * a.v[2]) || b.v[0] - a.v[0]);
  document.getElementById("fc-cands").innerHTML = ordered.map((c) => {
    const [primary, pft, pw] = c.v;
    return `<tr><td>${esc(nameOf(c.id))}</td>
      <td><span class="swatch" style="background:${pcolour(c.party)}"></span>${esc(c.party)}</td>
      <td class="r num">${pct1(primary)}</td><td class="r num">${Math.round(100 * pft)}%</td>
      <td class="r num"><b>${Math.round(100 * pw)}%</b></td></tr>`;
  }).join("");
  document.getElementById("fc-pairs").innerHTML = ROWS[i].pairs.map(pairHTML).join("");
  const favK = row.reduce((best, v, k) => (v[2] > row[best][2] ? k : best), 0);
  document.getElementById("kv-fav").innerHTML =
    `${esc(nameOf(CANDS[favK].id))} <span class="muted">${esc(CANDS[favK].party)}</span>`;
  document.getElementById("kv-win").textContent = `${Math.round(100 * row[favK][2])}%`;
  document.getElementById("fc-sub").innerHTML =
    `&mdash; ${esc(fmtSnapDate(p.date))} ${p.latest ? "forecast" : "snapshot"}`;
  const banner = document.getElementById("dtl-banner");
  banner.innerHTML = bannerHTML(i);
  banner.hidden = p.latest;
  document.querySelectorAll("#dtl-hist tr[data-date], #dtl-hist tr[data-latest]").forEach((tr) =>
    tr.classList.toggle("hist-cur", p.latest ? tr.hasAttribute("data-latest") : tr.dataset.date === p.date));
  history.replaceState(null, "", p.latest ? location.pathname : `#${p.date}`);
  paintOutline(row);
}

const widget = timelineSlider(document.getElementById("dtl-ui"), POINTS, {
  noteText: "Marks are model runs; the outline blends between them.",
  onBlend: (t, i, frac) => paintOutline(blendC(i, frac)),
  onMark: showMark,
});

/* #2026-10-13 opens on that mark; unknown dates fall back to Latest. */
const hm = location.hash.match(/^#(\d{4}-\d{2}-\d{2})$/);
if (hm) {
  const i = POINTS.findIndex((p) => p.date === hm[1]);
  if (i >= 0) widget.setMark(i);
}
showMark(widget.markIndex());  // initial figures + outline (Latest by default)
