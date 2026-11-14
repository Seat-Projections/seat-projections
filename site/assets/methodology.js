"use strict";
/* methodology.html — renders benchmark, polls and downloads tables from site/data/. */

async function init() {
  const [site, bench] = await Promise.all([
    siteJson(),
    fetch("data/benchmarks.json").then((r) => r.json()),
  ]);

  const isScored = (r) => r.raw_seat_count !== "" && r.raw_seat_count != null;
  const scoredRuns = [...bench.model1_runs, ...bench.model2_replays].filter(isScored);
  document.getElementById("st-runs").textContent = scoredRuns.length;
  document.getElementById("st-seats").textContent = fmt(scoredRuns.reduce((a, r) => a + r.districts, 0));
  document.getElementById("st-sims").textContent = fmt(Math.max(...Object.values(site.models).map((m) => m.runs)));
  document.getElementById("f-sims").textContent =
    `${fmt(site.models.model2.runs)} runs (model 2) · ${fmt(site.models.model1.runs)} runs (model 1)`;

  const row = (r, modelLabel) => `<tr${isScored(r) ? "" : ' class="dim"'}>
    <td>${esc(modelLabel)}</td><td>${esc(r.run)}</td>
    <td>${isScored(r) ? `${r.raw_seat_count} / ${r.districts}` : `forecast · ${r.districts} districts`}</td>
    <td class="r num">${isScored(r) ? `${(+r.accuracy_pct).toFixed(1)}%` : "—"}</td>
    <td class="r num">${isScored(r) ? (+r.brier).toFixed(3) : "—"}</td>
    <td class="r num">${isScored(r) ? (+r.log_loss).toFixed(3) : "—"}</td>
    <td class="r num">${r.final_two_accuracy ? `${(100 * +r.final_two_accuracy).toFixed(1)}%` : "—"}</td>
    <td class="r num">${r.tcp_margin_mae ? (+r.tcp_margin_mae).toFixed(2) : "—"}</td></tr>`;

  const m2 = [...bench.model2_replays].sort((a, b) => a.run.localeCompare(b.run));
  const m1 = [...bench.model1_runs].sort((a, b) => a.run.localeCompare(b.run));
  document.querySelector("#bench-table tbody").innerHTML =
    m2.map((r) => row(r, "model2")).join("") + m1.map((r) => row(r, "model1")).join("");

  const mp = site.models.model2;
  if (mp.polls) {
    document.getElementById("polls-card").innerHTML = `
      <h4 style="font-size:0.6875rem;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;color:var(--ink-2);margin:0 0 0.5rem">Average in the current forecast (${esc((mp.timestamp || "").slice(0, 10))})</h4>
      <table class="dtable"><thead><tr><th>Party</th><th class="r">Primary %</th></tr></thead><tbody>
      ${Object.entries(mp.polls).map(([k, v]) => `<tr><td><span class="swatch" style="background:${pcolour(k)}"></span>${esc({ LNP: "Coalition", OTH: "Others" }[k] || pname(k))}</td><td class="r num">${pct1(v)}</td></tr>`).join("")}
      </tbody></table>
      <p class="small muted" style="margin:0.5rem 0 0">Polls used: ${esc((mp.polls_used || []).join("; "))}.</p>`;
  }

  document.querySelector("#dl-table tbody").innerHTML = site.downloads.map((d) => `<tr>
    <td><span class="mono small">${esc(d.file)}</span></td>
    <td class="r num">${d.size_kb >= 1024 ? `${(d.size_kb / 1024).toFixed(1)} MB` : `${d.size_kb} KB`}</td>
    <td class="muted">${esc(d.description)}</td>
    <td class="r"><a class="dl-btn" href="data/downloads/${esc(d.file)}">Download</a></td></tr>`).join("");
}

init().catch((e) => { document.getElementById("st-runs").textContent = "—"; console.error(e); });
