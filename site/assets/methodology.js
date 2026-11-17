"use strict";
/* methodology pages — each block renders only if its element is on the page:
   stat strip (overview), f-sims (count engine), bench-table (benchmarks),
   polls-card (model 2), dl-table (open data). */

const $id = (id) => document.getElementById(id);

async function init() {
  const benchTables = document.querySelectorAll("table.dtable[data-bench]");
  const need = {
    bench: $id("st-runs") || $id("st-seats") || benchTables.length,
    site: $id("st-sims") || $id("f-sims") || $id("polls-card") || $id("dl-table") || $id("st-runs"),
  };
  const [site, bench] = await Promise.all([
    need.site ? siteJson() : null,
    need.bench ? fetch("/data/benchmarks.json").then((r) => r.json()) : null,
  ]);

  const isScored = (r) => r.raw_seat_count !== "" && r.raw_seat_count != null;

  if ($id("st-runs") || $id("st-seats")) {
    const scoredRuns = [...bench.model1_runs, ...bench.forecast_backtests].filter(isScored);
    if ($id("st-runs")) $id("st-runs").textContent = scoredRuns.length;
    if ($id("st-seats")) $id("st-seats").textContent = fmt(scoredRuns.reduce((a, r) => a + r.districts, 0));
  }
  if ($id("st-sims")) $id("st-sims").textContent = fmt(Math.max(...Object.values(site.models).map((m) => m.runs)));
  if ($id("f-sims")) $id("f-sims").textContent =
    `${fmt(site.models.model2.runs)} runs (model 2) · ${fmt(site.models.model1.runs)} runs (model 1)`;

  if (benchTables.length) {
    const row = (r, full) => `<tr${isScored(r) ? "" : ' class="dim"'}>
      <td>${esc(r.run)}</td>
      <td>${isScored(r) ? `${r.raw_seat_count} / ${r.districts}` : (r.run.startsWith("VIC2026") ? `forecast · ${r.districts} districts` : "pending (not yet run)")}</td>
      <td class="r num">${isScored(r) ? `${(+r.accuracy_pct).toFixed(1)}%` : "N/A"}</td>
      <td class="r num">${isScored(r) ? (+r.brier).toFixed(3) : "N/A"}</td>
      <td class="r num">${isScored(r) ? (+r.log_loss).toFixed(3) : "N/A"}</td>${full ? `
      <td class="r num">${r.fp_error ? (+r.fp_error).toFixed(2) : "N/A"}</td>
      <td class="r num">${r.final_two_accuracy ? `${(100 * +r.final_two_accuracy).toFixed(1)}%` : "N/A"}</td>` : ""}</tr>`;
    const lists = { model1: bench.model1_runs, model2: bench.forecast_backtests };
    benchTables.forEach((t) => {
      const key = t.dataset.bench;
      const runs = lists[key] || [];
      const full = t.querySelectorAll("thead th").length > 5;
      t.querySelector("tbody").innerHTML = runs.map((r) => row(r, full)).join("");
    });
  }

  if ($id("polls-card")) {
    const mp = site.models.model2;
    if (mp.polls) {
      $id("polls-card").innerHTML = `
        <h4 style="font-size:0.6875rem;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;color:var(--ink-2);margin:0 0 0.5rem">Average in the current forecast (${esc((mp.timestamp || "").slice(0, 10))})</h4>
        <table class="dtable"><thead><tr><th>Party</th><th class="r">Primary %</th></tr></thead><tbody>
        ${Object.entries(mp.polls).map(([k, v]) => `<tr><td><span class="swatch" style="background:${pcolour(k)}"></span>${esc({ LNP: "Coalition", OTH: "Others" }[k] || pname(k))}</td><td class="r num">${pct1(v)}</td></tr>`).join("")}
        </tbody></table>
        <p class="small muted" style="margin:0.5rem 0 0">Polls used: ${esc((mp.polls_used || []).join(", "))}.</p>`;
    }
  }

  if ($id("dl-table")) {
    document.querySelector("#dl-table tbody").innerHTML = site.downloads.map((d) => `<tr>
      <td><span class="mono small">${esc(d.file)}</span></td>
      <td class="r num">${d.size_kb >= 1024 ? `${(d.size_kb / 1024).toFixed(1)} MB` : `${d.size_kb} KB`}</td>
      <td class="muted">${esc(d.description)}</td>
      <td class="r"><a class="dl-btn" href="/data/downloads/${esc(d.file)}">Download</a></td></tr>`).join("");
  }
}

init().catch((e) => { const el = $id("st-runs"); if (el) el.textContent = "Unavailable"; console.error(e); });
