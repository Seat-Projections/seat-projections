/* live/ — election-night live blog: polls /data/live_vic2026.json every 60 s
   (paused while the tab is hidden) and re-renders scoreboard, called-seats table
   and the entries feed. Mirrors the Python logic in build_site.write_live. */

const liveFetch = (u) => fetch(u, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null));

function effectiveCalls(entries) {
  const calls = {};
  for (const e of entries) {
    if (e.replace_calls) for (const k of Object.keys(calls)) delete calls[k];
    if (e.district && e.call) calls[e.district] = e;
    for (const c of e.calls || []) calls[c.district] = { ...e, district: c.district, call: c.call };
  }
  return calls;
}

function fmtLiveTime(iso) {
  const d = new Date(iso);
  let h = d.getHours() % 12 || 12;
  return `${h}:${String(d.getMinutes()).padStart(2, "0")}${d.getHours() < 12 ? "am" : "pm"}`;
}

function scoreboardHtml(live, fc) {
  const calls = effectiveCalls(live.entries || []);
  const by = {};
  for (const e of Object.values(calls)) by[e.call] = (by[e.call] || 0) + 1;
  const coal = (by.LP || 0) + (by.NP || 0);
  const bloc = (k) => (fc.blocs[k] ? fc.blocs[k].seats_mean : null);
  const rows = [
    ["Coalition", coal, bloc("COAL"), `Lib ${by.LP || 0} &middot; Nat ${by.NP || 0}`],
    ["Labor", by.ALP || 0, bloc("ALP"), null],
    ["One Nation", by.ON || 0, bloc("ON"), null],
    ["Greens", by.GRN || 0, bloc("GRN"), null],
    ["Independents", by["IND*"] || 0, bloc("IND*"), null],
  ];
  if (by.OTH) rows.push(["Others", by.OTH, null, null]);
  const y = Object.keys(calls).length;
  const correct = Object.entries(calls).filter(([d, e]) => fc.districts[d] && fc.districts[d].fav_party === e.call).length;
  const pct = y ? Math.round(100 * correct / y) : 0;
  const trs = rows.map(([label, called, exp, note]) =>
    `<tr><td>${esc(label)}</td><td class="r num"><b>${called}</b></td>` +
    `<td class="r num">${exp == null ? "&mdash;" : exp.toFixed(1)}</td>` +
    `<td class="muted small">${note || ""}</td></tr>`).join("");
  return `<table class="dtable"><thead><tr><th>Party</th><th class="r">Called</th>` +
    `<th class="r">Forecast</th><th></th></tr></thead><tbody>${trs}</tbody></table>` +
    `<p class="small muted" style="margin:0.5rem 0 0"><b>${y} of 88 seats called.</b> ` +
    `Our forecast favourite won ${correct} of ${y} called seats (${pct}%).</p>`;
}

function callsTableHtml(live, fc) {
  const calls = effectiveCalls(live.entries || []);
  const trs = Object.entries(calls)
    .sort((a, b) => +b[1].id - +a[1].id)
    .map(([d, e]) => {
      const f = fc.districts[d] || {};
      return `<tr><td><a href="/districts/${esc(f.slug || "")}/"><b>${esc(d)}</b></a></td>` +
        `<td><span class="swatch" style="background:${pcolour(e.call)}"></span>${esc(pname(e.call))}</td>` +
        `<td>${esc(f.fav_name || "")} (${esc(pname(f.fav_party || ""))})</td>` +
        `<td class="r num">${Math.round(100 * (f.p_win || 0))}%</td>` +
        `<td>${e.call === f.fav_party ? "&#10003;" : "&#10007;"}</td></tr>`;
    }).join("");
  return `<table class="dtable"><thead><tr><th>District</th><th>Called for</th>` +
    `<th>Our favourite</th><th class="r">Win %</th><th></th></tr></thead><tbody>${trs}</tbody></table>`;
}

function feedHtml(live, fc) {
  const entries = live.entries || [];
  if (!entries.length) {
    return '<p class="muted">Live coverage starts when polls close at 6pm on Saturday 28 November.</p>';
  }
  return [...entries].reverse().map((e) => {
    const meta = [`<b>${esc(fmtLiveTime(e.time))}</b>`];
    if (e.district) {
      const f = fc.districts[e.district] || {};
      meta.push(`<a href="/districts/${esc(f.slug || "")}/">${esc(e.district)}</a>`);
    }
    if (e.call) meta.push(`<span class="swatch" style="background:${pcolour(e.call)}"></span>${esc(pname(e.call))}`);
    const paras = String(e.text).split("\n\n").map((t) => `<p>${esc(t)}</p>`).join("");
    return `<div class="live-entry" id="e${esc(e.id)}"><div class="live-meta">${meta.join(" ")}</div>${paras}</div>`;
  }).join("");
}

let liveTimer = null;

async function refreshLive() {
  const [live, fc] = await Promise.all([
    liveFetch("/data/live_vic2026.json"),
    liveFetch("/data/live_forecast_vic2026.json"),
  ]);
  if (!live || !fc) return;
  document.getElementById("live-score-body").innerHTML = scoreboardHtml(live, fc);
  document.getElementById("live-calls-body").innerHTML = callsTableHtml(live, fc);
  document.getElementById("live-feed").innerHTML = feedHtml(live, fc);
  const u = document.getElementById("live-updated");
  if (u) {
    u.hidden = false;
    document.getElementById("live-updated-t").textContent =
      new Date().toTimeString().slice(0, 5);
  }
}

function liveSchedule() {
  if (liveTimer) clearInterval(liveTimer);
  liveTimer = null;
  if (!document.hidden) liveTimer = setInterval(refreshLive, 60000);
}

document.addEventListener("visibilitychange", liveSchedule);
refreshLive();
liveSchedule();
