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
