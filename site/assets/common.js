"use strict";
/* Shared helpers + party metadata for seatprojections.au pages. */

const PARTY = {
  ALP:  { name: "Labor",        colour: "#DE3533" },
  LP:   { name: "Liberal",      colour: "#1C4F9C" },
  NP:   { name: "Nationals",    colour: "#006644" },
  COAL: { name: "Coalition",    colour: "#1C4F9C" },
  LNP:  { name: "Coalition",    colour: "#1C4F9C" },
  GRN:  { name: "Greens",       colour: "#10C25B" },
  ON:   { name: "One Nation",   colour: "#FF7300" },
  IND:  { name: "Independent",  colour: "#00A3A6" },
  "IND*": { name: "Independent", colour: "#00A3A6" },
  OTH:  { name: "Others",       colour: "#8E44AD" },
};
// Extra 2022 party groups shown in per-district tables get the "others" colour.
const PARTY_SHORT = { "Australian Labor Party - Victorian Branch": "ALP", "Liberal": "LP", "The Nationals": "NP", "Australian Greens": "GRN", "Pauline Hanson's One Nation": "ON", "Independent": "IND" };

// Short display names for registered VEC party names (full name stays available via title=).
const PARTY_SHORTNAME = {
  "Australian Labor Party - Victorian Branch": "Labor",
  "Liberal": "Liberal",
  "The Nationals": "Nationals",
  "Australian Greens": "Greens",
  "Pauline Hanson's One Nation": "One Nation",
  "Independent": "Independent",
  "Victorian Socialists": "Victorian Socialists",
  "Family First Victoria": "Family First",
  "Animal Justice Party": "Animal Justice",
  "Freedom Party of Victoria": "Freedom Party",
  "Liberal Democrats": "Libertarian",
  "Labour DLP": "Labour DLP",
  "Derryn Hinch's Justice Party": "Justice Party",
  "New Democrats": "New Democrats",
  "Fiona Patten's Reason Party": "Reason",
  "Shooters, Fishers & Farmers Vic": "Shooters, Fishers & Farmers",
  "Legalise Cannabis Victoria": "Legalise Cannabis",
  "Angry Victorians Party": "Angry Victorians",
  "Health Australia Party": "Health Australia",
  "Transport Matters": "Transport Matters",
  "Companions and Pets Party": "Companions & Pets",
};
const shortParty = (full) => PARTY_SHORTNAME[full] || full;

const districtSlug = (s) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
const pcolour = (g) => (PARTY[g] || PARTY.OTH).colour;
const pname = (g) => (PARTY[g] || { name: g }).name;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => (n ?? 0).toLocaleString("en-AU");
const pct1 = (x) => `${(+x).toFixed(1)}%`;

let SITE_JSON = null;
async function siteJson() {
  return (SITE_JSON ||= await fetch("/data/site.json").then((r) => r.json()));
}

// Fill every [data-repo] element with the repo URL once site.json is loaded.
async function fillRepoLinks() {
  try {
    const s = await siteJson();
    document.querySelectorAll("a[data-repo]").forEach((a) => { a.href = s.repo_url + (a.dataset.repo || ""); });
    document.querySelectorAll("[data-build-date]").forEach((el) => { el.textContent = s.build_date; });
  } catch { /* repo links stay href="#" if site.json is unavailable */ }
}
document.addEventListener("DOMContentLoaded", fillRepoLinks);

/* ---------- shared forecast-history timeline slider ---------- */
/* Continuous real-day scale across mark "points" ([{date, retrospective?} | {date, latest:true}]).
   Builds its own DOM inside `container`. Callbacks:
     opts.onBlend(t, markIndex, frac)  — every rAF-throttled input (frac 0 at/on a mark)
     opts.onMark(markIndex)            — when the floor mark (figures shown) changes
     opts.noteText                     — caption under the ticks
   Returns { get t, markIndex(), setDay(t), setMark(i), dayOf(i) }. */
const TL_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const fmtSnapDate = (d) => {
  const [y, m, day] = d.split("-").map(Number);
  return `${day} ${TL_MONTHS[m - 1]} ${y}`;
};
const fmtSnapShort = (d) => `${Number(d.split("-")[2])} ${TL_MONTHS[Number(d.split("-")[1]) - 1]}`;

function timelineSlider(container, points, opts = {}) {
  const dayOf = (iso) => Date.parse(`${iso}T00:00:00Z`) / 864e5;
  const pdays = points.map((p) => dayOf(p.date) - dayOf(points[0].date));
  const total = pdays[pdays.length - 1] || 0;
  let t = total;
  let shownMark = pdays.length - 1;

  container.innerHTML = `
    <div class="tl-head">
      <span class="small tl-label" style="font-weight:600"></span>
      <span class="muted small"><a href="/methodology/forecast/#history">How snapshots work</a></span>
    </div>
    <div class="tl-track">
      <input type="range" class="tl-range" min="0" max="${total}" value="${total}" step="any" aria-label="Forecast timeline">
      <div class="snap-notches"></div>
      <div class="snap-ticks"></div>
    </div>
    <p class="muted small" style="margin-top:0.35rem">${esc(opts.noteText || "Marks are model runs; the map blends between them.")}</p>`;
  const slider = container.querySelector(".tl-range");
  const label = container.querySelector(".tl-label");

  const compact = () => container.classList.toggle("tl-compact", container.clientWidth < 560);
  compact();
  if (window.ResizeObserver) new ResizeObserver(compact).observe(container);

  const pct = (i) => `${(100 * pdays[i] / total).toFixed(3)}%`;
  const tight = (i) => (i < points.length - 1 && pdays[i + 1] - pdays[i] < total * 0.09 ? " thin" : "");
  container.querySelector(".snap-notches").innerHTML =
    points.map((p, i) => `<span class="notch${p.latest ? " latest" : ""}" style="left:${pct(i)}"></span>`).join("");
  container.querySelector(".snap-ticks").innerHTML =
    points.map((p, i) => `<span class="tl${tight(i)}" style="left:${pct(i)}">${p.latest ? "Latest" : esc(fmtSnapShort(p.date))}</span>`).join("");

  const markAt = (x) => {
    let i = 0;
    while (i < pdays.length - 1 && pdays[i + 1] <= x + 1e-9) i++;
    return i;
  };

  function render() {
    const mark = markAt(t);
    const approx = t < total - 1e-9 && Math.abs(pdays[mark] - t) > 0.01;
    if (approx) {
      const cur = new Date((dayOf(points[0].date) + t) * 864e5).toISOString().slice(0, 10);
      const next = points[mark + 1].latest ? "Latest" : fmtSnapShort(points[mark + 1].date);
      const figs = points[mark].latest ? "Latest" : fmtSnapShort(points[mark].date);
      label.textContent = `${fmtSnapDate(cur)}: map blended between ${figs} and ${next} runs; figures show ${figs}`;
    } else {
      label.textContent = points[mark].latest ? `Latest · ${fmtSnapDate(points[mark].date)}` : `Polls to ${fmtSnapDate(points[mark].date)}`;
    }
    let frac = 0;
    if (mark < pdays.length - 1 && t > pdays[mark]) {
      frac = (t - pdays[mark]) / (pdays[mark + 1] - pdays[mark]);
    }
    if (mark !== shownMark) {
      shownMark = mark;
      if (opts.onMark) opts.onMark(mark);
    }
    if (opts.onBlend) opts.onBlend(t, mark, approx ? frac : 0);
  }

  let pending = false;
  slider.addEventListener("input", () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => {
      pending = false;
      t = Number(slider.value);
      render();
    });
  });
  render();  // set the label to Latest

  return {
    get t() { return t; },
    get pdays() { return pdays; },
    totalDays: total,
    markIndex() { return markAt(t); },
    setDay(x) { t = x; slider.value = x; render(); },
    setMark(i) { t = pdays[i]; slider.value = pdays[i]; render(); },
  };
}

/* "SURNAME, Given" / "SURNAME, Given; ..." -> "Given Surname, ..." (matches build_site disp_names). */
const dispName = (n) => {
  if (!n || !n.includes(",")) return n;
  const [sur, ...rest] = n.split(",");
  const given = rest.join(",").trim();
  const s = sur.trim().toLowerCase().replace(/(^|\s|-)(\w)/g, (m, p, c) => p + c.toUpperCase());
  return given ? `${given} ${s}` : s;
};
