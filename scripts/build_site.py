#!/usr/bin/env python3
"""
Builds the static data for the public website (site/data/), served by GitHub Pages at
https://seatprojections.au:

  districts.geojson        88 Legislative Assembly districts (2021 redivision), coordinates rounded
                           to 5 decimals; properties reduced to district name and region
  victoria_outline.json    state outline rings, used to mask the map outside Victoria
  baseline_2022.json       2022 VEC result per district: elected member, final-two (2CP) votes and
                           margin, first preferences per candidate, enrolment, VEC source link,
                           plus statewide seat tally and first-preference shares
  model1_vic2026.json      the models' 2026 forecasts, copied from visualiser/data/ (rebuilt there by
  model2_vic2026.json      scripts/build_visualiser.py --forecasts-only after each model run)
  benchmarks.json          archived model1 runs + forecast backtests (model1/model3/model2 F)
  site.json                REPO_URL, build date, forecast run metadata, downloadable-file register
  downloads/               public copies of the datasets listed on the Methodology page

The HTML/CSS/JS under site/ is hand-written; this script only produces data files.
Serve with:  .venv/bin/python -m http.server 8001 -d site
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIS = ROOT / "visualiser" / "data"
SITE = ROOT / "site"
DATA = SITE / "data"
DOWNLOADS = DATA / "downloads"

# Placeholder until the public repository exists; written into site/data/site.json and read by the
# pages, so switching to the real URL is a one-line change here.
REPO_URL = "https://github.com/Seat-Projections/seat-projections"

ARCHIVE = ROOT / "predictions" / "benchmarking" / "archive"
MODEL1_CANDIDATES = ARCHIVE / "2026-11-09_model1_candidates" / "results.csv"
MODEL2_CANDIDATES = ARCHIVE / "2026-11-09_model2_candidates" / "results.csv"

from build_visualiser import FORECASTS, forecast_doc  # noqa: E402

# Registered VEC party name -> party-group code used across the models
PARTY_GROUP = {
    "Australian Labor Party - Victorian Branch": "ALP",
    "Liberal": "LP",
    "The Nationals": "NP",
    "Australian Greens": "GRN",
    "Pauline Hanson's One Nation": "ON",
    "Independent": "IND",
}
GROUP_ORDER = ("ALP", "LP", "NP", "GRN", "ON", "IND", "OTH")


def group_of(party_name: str) -> str:
    return PARTY_GROUP.get(party_name, "OTH")


def round_coords(obj, digits: int = 5):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, digits) for v in obj]
        return [round_coords(v, digits) for v in obj]
    return obj


# --- Topology-preserving simplification -------------------------------------
# Neighbouring districts share identical vertices in the source, so each ring is
# split into arcs at junction vertices (where the set of rings using the vertex
# changes), each unique arc is simplified once with Douglas-Peucker, and every
# ring is rebuilt from the shared simplified arcs. Neighbours therefore keep
# byte-identical shared boundaries — no gaps or slivers can open between them.
SIMPLIFY_EPS = 0.0025  # ~250 m max deviation; sub-pixel at the map's working zooms
DISPLAY_PREC = 4       # ~11 m coordinate rounding on the display files


def _rings_of(geometry):
    if geometry["type"] == "Polygon":
        return geometry["coordinates"]
    return [r for poly in geometry["coordinates"] for r in poly]


def _douglas_peucker(pts, eps):
    if len(pts) <= 2:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]
        bx, by = pts[b]
        dx, dy = bx - ax, by - ay
        denom = (dx * dx + dy * dy) ** 0.5
        dmax, imax = -1.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = ((px - ax) ** 2 + (py - ay) ** 2) ** 0.5 if denom == 0 else abs(dy * px - dx * py + bx * ay - by * ax) / denom
            if d > dmax:
                dmax, imax = d, i
        if dmax > eps:
            keep[imax] = True
            stack += [(a, imax), (imax, b)]
    return [p for p, k in zip(pts, keep) if k]


def simplify_districts(features):
    """Returns (simplified_features, outline_rings_latlon)."""
    rings = []          # (feature_index, part_index, [pts]) — pts without the closing repeat
    for fi, f in enumerate(features):
        for pi, ring in enumerate(_rings_of(f["geometry"])):
            pts = [tuple(p) for p in ring]
            if pts[0] == pts[-1]:
                pts = pts[:-1]
            rings.append((fi, pi, pts))

    vset, adj = defaultdict(set), defaultdict(set)
    for i, (_, _, pts) in enumerate(rings):
        n = len(pts)
        for j, p in enumerate(pts):
            vset[p].add(i)
            adj[p].add(pts[(j - 1) % n])
            adj[p].add(pts[(j + 1) % n])

    # Junction: degree != 2 in the union graph, or a neighbouring vertex belongs
    # to a different set of rings (a boundary chain starts/ends/merges there).
    junct = {v for v in vset if len(adj[v]) != 2 or any(vset[u] != vset[v] for u in adj[v])}

    def split_ring(pts):
        n = len(pts)
        if not any(p in junct for p in pts):
            return [pts + [pts[0]]]  # closed ring with no junctions (island/exclave)
        s = next(i for i, p in enumerate(pts) if p in junct)
        arcs, cur = [], [pts[s]]
        for k in range(1, n + 1):
            p = pts[(s + k) % n]
            cur.append(p)
            if p in junct:
                arcs.append(cur)
                cur = [p]
        return arcs

    ring_arcs = [split_ring(pts) for _, _, pts in rings]
    canon = lambda a: min(tuple(a), tuple(a[::-1]))
    use_count = Counter()
    for arcs in ring_arcs:
        for a in arcs:
            use_count[canon(a)] += 1
    simplified = {k: _douglas_peucker(list(k), SIMPLIFY_EPS) for k in use_count}

    new_rings = []
    for (fi, pi, pts), arcs in zip(rings, ring_arcs):
        out = []
        for a in arcs:
            s = simplified[canon(a)]
            if a[0] != s[0]:
                s = s[::-1]
            out.extend(s[:-1])
        out.append(out[0])
        # Guard: never emit a collapsed ring; keep the original if too small.
        new_rings.append((fi, pi, pts + [pts[0]] if len(set(out)) < 4 else out))

    # Rebuild features, restoring each original Polygon/MultiPolygon part grouping.
    simp_features = []
    i = 0
    for f in features:
        raw = f["geometry"]["coordinates"]
        parts = raw if f["geometry"]["type"] == "MultiPolygon" else [raw]
        rebuilt = []
        for part in parts:
            n = len(part)
            rebuilt.append([[list(p) for p in r] for _, _, r in new_rings[i:i + n]])
            i += n
        geometry = {"type": f["geometry"]["type"], "coordinates": rebuilt if f["geometry"]["type"] == "MultiPolygon" else rebuilt[0]}
        simp_features.append({"type": "Feature", "properties": f["properties"], "geometry": geometry})

    # State outline: arcs used by exactly one ring bound the state's exterior.
    # They form closed loops, but a vertex can touch several exterior arcs, so
    # chaining needs a consistent planar rule: on arriving at a vertex, leave by
    # the exterior arc next clockwise from the direction back to the previous
    # vertex. That pairs arcs correctly at pinch points instead of guessing.
    import math

    def signed_area(pts):
        return sum(
            pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
            for i in range(len(pts))
        )

    # exterior[i] is the simplified arc; state_left[i] is True when traversing
    # it in its stored direction keeps the district (state interior) on the
    # left — i.e. the arc's direction matches its ring's direction exactly when
    # the ring winds CCW.
    exterior, state_left = [], []
    for (_, _, pts), arcs in zip(rings, ring_arcs):
        ccw = signed_area(pts) > 0
        for a in arcs:
            k = canon(a)
            if use_count[k] == 1:
                s = simplified[k]
                exterior.append(s)
                state_left.append((a[0] == s[0]) == ccw)
    ends = defaultdict(list)
    for ai, a in enumerate(exterior):
        ends[a[0]].append(ai)
        ends[a[-1]].append(ai)

    def next_arc(v, prev, skip):
        back = math.atan2(prev[1] - v[1], prev[0] - v[0])
        best, best_turn = None, None
        for ni in ends[v]:
            if ni == skip:
                continue
            b = exterior[ni]
            nxt = b[1] if b[0] == v else b[-2]
            turn = (back - math.atan2(nxt[1] - v[1], nxt[0] - v[0])) % (2 * math.pi)
            if best_turn is None or turn < best_turn:
                best, best_turn = ni, turn
        return best

    # Face tracing on directed half-edges: at each vertex, leave by the arc
    # next clockwise from the direction back along the incoming arc. Every
    # directed arc use is tracked, and orbits start from either direction, so
    # each orbit is one face of the exterior-edge graph — a bounded face is a
    # connected piece of the state's interior. Dangling chains (bridges) are
    # traversed out and back and elided later; they enclose zero area.
    outline = []
    used_dir = set()
    TAU = 2 * math.pi
    for ai in range(len(exterior)):
        for d0 in (1, -1):
            e0 = (ai, d0)
            if e0 in used_dir:
                continue
            used_dir.add(e0)
            # This orbit keeps its face on one side (left by this convention);
            # emit it only when that side is the district side — pockets on the
            # ocean side of the boundary must not be masked as land.
            keep = state_left[ai] if d0 == 1 else not state_left[ai]
            loop = list(exterior[ai] if d0 == 1 else exterior[ai][::-1])
            last = e0
            while True:
                v, prev = loop[-1], loop[-2]
                back = math.atan2(prev[1] - v[1], prev[0] - v[0])
                best, bt = None, None
                for ni in ends[v]:
                    if ni == last[0]:
                        continue  # never U-turn the incoming arc while others exist
                    b = exterior[ni]
                    if b[0] == v:
                        d, dep = 1, b[1]
                    else:
                        d, dep = -1, b[-2]
                    if (ni, d) in used_dir and (ni, d) != e0:
                        continue
                    turn = (back - math.atan2(dep[1] - v[1], dep[0] - v[0])) % TAU
                    if bt is None or turn < bt:
                        best, bt = (ni, d), turn
                if best is None:
                    # dead end: the only incident arc is the incoming one —
                    # the face continues back along it (bridge edge).
                    rev = (last[0], -last[1])
                    if rev in used_dir or rev == e0:
                        break  # orbit closed / malformed; force-close below
                    best = rev
                elif best == e0:
                    break  # orbit closed
                used_dir.add(best)
                seg = exterior[best[0]] if best[1] == 1 else exterior[best[0]][::-1]
                loop += seg[1:]
                last = best
            if loop[-1] != loop[0]:
                loop.append(loop[0])
            # Drop out-and-back excursions (dangling chains traversed out and
            # back): they are zero-area, so eliding them leaves the mask
            # pixel-identical.
            trail = [loop[0]]
            for p in loop[1:]:
                if len(trail) >= 2 and trail[-2] == p:
                    trail.pop()
                else:
                    trail.append(p)
            if trail and trail[-1] == trail[0]:
                trail = trail[:-1]
            if len(trail) < 3:
                continue  # pure out-and-back spike: encloses nothing
            loop = trail + [trail[0]]
            # No further coarsening: the mask must coincide vertex-for-vertex
            # with the district edges, or it cuts into/uncovers district fill.
            if keep and len(set(loop)) >= 4:
                # normalise orientation so every loop winds the same way
                area = sum(
                    loop[i][0] * loop[i + 1][1] - loop[i + 1][0] * loop[i][1]
                    for i in range(len(loop) - 1)
                )
                if area < 0:
                    loop = loop[::-1]
                outline.append([[round(y, DISPLAY_PREC), round(x, DISPLAY_PREC)] for x, y in loop])

    # The mask polygon is [world, ...outline], so every emitted ring is a hole
    # in the world rect. A ring nested inside another hole is stroked and
    # refilled as an island of mask colour — the small interior pockets bounded
    # by single-use arcs between districts show through the district fills as
    # dark doubled borders. Face interiors are disjoint, so a ring enclosed by
    # another ring can be dropped without changing the state boundary.
    def _point_strictly_inside(px, py, ring):
        inside = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i][0], ring[i][1]
            xj, yj = ring[j][0], ring[j][1]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        return inside

    def _ring_enclosed(inner, outer):
        # Enclosed iff inner's centroid is strictly inside outer: outline rings
        # bound distinct faces, so a centroid inside another ring means the
        # ring lies in that ring's interior (its boundary may share vertices
        # with the enclosing ring, which vertices-only tests mishandle).
        if len(inner) < len(outer):
            cx = sum(p[0] for p in inner[:-1]) / (len(inner) - 1)
            cy = sum(p[1] for p in inner[:-1]) / (len(inner) - 1)
            return _point_strictly_inside(cx, cy, outer)
        return False

    outline = [r for i, r in enumerate(outline)
               if not any(i != j and _ring_enclosed(r, other) for j, other in enumerate(outline))]
    return simp_features, outline


def load_baseline() -> dict:
    """2022 VEC results per district. Two-candidate-preferred finals come from the full-preference
    file (the official count stops at 50%, so its `final_totals` can hold >2 candidates); first
    preferences, enrolment and source links come from the official distribution pages."""
    official = json.loads((ROOT / "data" / "2022" / "distributions" / "official_2022.json").read_text())
    full2cp = json.loads((ROOT / "data" / "2022" / "distributions" / "full_2cp_2022.json").read_text())
    geojson = json.loads((VIS / "districts.geojson").read_text())
    regions = {f["properties"]["district"]: f["properties"]["region"] for f in geojson["features"]}

    districts = {}
    seats = Counter()
    fp_by_group = Counter()
    totals = {"formal": 0, "informal": 0, "enrolment": 0}

    for name, off in official.items():
        full = full2cp[name]
        cand_party = {c["name"]: c["party"] for c in off["candidates"]}
        # The indicative workbooks' first preferences differ from the official count by a handful
        # of votes; the official distribution pages are authoritative for primaries and totals.

        winner = off["declared_winner"]
        winner_party = cand_party[winner]
        winner_group = group_of(winner_party)
        seats[winner_group] += 1

        primary = sorted(
            (
                {
                    "name": c["name"],
                    "party": c["party"],
                    "group": group_of(c["party"]),
                    "votes": off["first_preferences"].get(c["name"], 0),
                }
                for c in off["candidates"]
            ),
            key=lambda c: -c["votes"],
        )
        for c in primary:
            fp_by_group[c["group"]] += c["votes"]

        final = sorted(full["final_totals"].items(), key=lambda kv: -kv[1])
        assert len(final) == 2, name
        final_two = [
            {"name": n, "party": cand_party[n], "group": group_of(cand_party[n]), "votes": v}
            for n, v in final
        ]
        tcp_total = sum(v for _, v in final)
        margin = round(100 * final[0][1] / tcp_total - 50, 2)

        totals["formal"] += off["formal_votes"]
        totals["informal"] += off["informal_votes"]
        totals["enrolment"] += off["enrolment"]

        districts[name] = {
            "region": regions.get(name),
            "winner": winner,
            "winner_party": winner_party,
            "winner_group": winner_group,
            "final_two": final_two,
            "margin_pct": margin,
            "primary": primary,
            "formal_votes": off["formal_votes"],
            "informal_votes": off["informal_votes"],
            "enrolment": off["enrolment"],
            "indicative_2cp": full["source_type"] == "indicative_full_2022",
            "source_url": off["source_url"],
        }

    fp_share = {
        g: round(100 * fp_by_group[g] / totals["formal"], 2) for g in GROUP_ORDER
    }
    return {
        "election": "2022 Victorian state election",
        "districts": districts,
        "seats": dict(seats),
        "fp_share": fp_share,
        "totals": totals,
    }


def results_csv(baseline: dict) -> str:
    """One row per district: winner, runner-up, 2CP margin and headline numbers."""
    rows = []
    for name, d in sorted(baseline["districts"].items()):
        a, b = d["final_two"]
        rows.append(
            {
                "district": name,
                "region": d["region"],
                "winner": d["winner"],
                "winner_party": d["winner_party"],
                "winner_group": d["winner_group"],
                "runner_up": b["name"],
                "runner_up_party": b["party"],
                "winner_2cp_pct": round(100 * a["votes"] / (a["votes"] + b["votes"]), 2),
                "margin_2cp_pct": d["margin_pct"],
                "formal_votes": d["formal_votes"],
                "informal_votes": d["informal_votes"],
                "enrolment": d["enrolment"],
                "source_url": d["source_url"],
            }
        )
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def benchmarks() -> dict:
    def read(path: Path) -> list[dict]:
        with path.open() as f:
            return list(csv.DictReader(f))

    def slim(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            out.append(
                {
                    "model": r["model"],
                    "run": r["run"],
                    "districts": int(r["districts"]),
                    "data_from": r["data_from"],
                    "raw_seat_count": r["raw_seat_count"],
                    "accuracy_pct": r["accuracy_pct"],
                    "brier": r["brier"],
                    "log_loss": r["log_loss"],
                    "final_two_accuracy": r.get("final_two_accuracy") or None,
                    "tcp_margin_mae": r.get("tcp_margin_mae") or None,
                    "predicted_seats": r["predicted_seats"],
                    "actual_seats": r["actual_seats"] or None,
                }
            )
        return out

    # Canonical table: every model x the 5 backtest elections + VIC2026 (unscored, first).
    seats_map = {"VIC2022": 88, "NSW2023": 93, "QLD2024": 93, "WA2025": 59, "SA2026": 47, "VIC2026": 88}
    rows: dict[str, list[dict]] = {"model1": [], "model2": [], "model3": []}
    for r in read(ROOT / "predictions" / "benchmarking" / "forecast_backtests.csv"):
        unscored = r["seats_right"] == ""
        rows[r["model"]].append({
            "model": r["model"], "run": r["run_id"],
            "districts": int(r["districts"]) if r["districts"] else seats_map[r["election"]],
            "data_from": "2026", "raw_seat_count": r["seats_right"],
            "accuracy_pct": str(round(100 * float(r["accuracy"]), 1)) if not unscored else "",
            "brier": r["brier"], "log_loss": r["log_loss"],
            "fp_error": r["t1_mae_pp"] or None,
            "final_two_accuracy": r["final_two_accuracy"] or None,
            "predicted_seats": r["predicted_seats"], "actual_seats": r["actual_seats"] or None,
        })
    return {
        "model1_runs": rows["model1"],
        "forecast_backtests": [r for r in rows["model2"] if "fed" not in r["run"]],
        "forecast_fed_backtests": [r for r in rows["model2"] if "fed" in r["run"]],
        "model3_backtests": rows["model3"],
    }


# Header forecast chips: static HTML written between <!-- forecast-chips -->
# markers in every page's header, regenerated from model2's bloc seat means so
# a new forecast updates the header on the next build.
CHIP_BLOCS = [("COAL", "COA", "var(--lp)"), ("ALP", "ALP", "var(--alp)"),
              ("ON", "ONP", "var(--on)"), ("GRN", "GRN", "var(--grn)"),
              ("IND*", "IND", "var(--ind)")]


def forecast_chips_html(blocs):
    seats = {b["party"]: round(b["seats_mean"]) for b in blocs}
    chips = "\n".join(
        f'        <span class="chip"><i class="dot" style="background:{colour}"></i>{label} {seats[key]}</span>'
        for key, label, colour in CHIP_BLOCS
    )
    return (
        '<span class="chips">\n'
        '        <span class="h-label">2026 forecast</span>\n'
        f"{chips}\n"
        '        <span class="chip">45 to win</span>\n'
        "      </span>"
    )


def write_header_chips(blocs):
    body = forecast_chips_html(blocs)
    open_m, close_m = "<!-- forecast-chips -->", "<!-- /forecast-chips -->"
    for page in SITE.rglob("*.html"):
        if "vendor" in page.parts:
            continue
        text = page.read_text()
        if open_m not in text:
            continue
        start = text.index(open_m) + len(open_m)
        end = text.index(close_m)
        page.write_text(text[:start] + "\n      " + body + "\n      " + text[end:])

# ---------------------------------------------------------------------------
# Static pages: SEO head blocks, headline on /, district pages, sitemap
# ---------------------------------------------------------------------------

DOMAIN = "https://seatprojections.au"

GROUP_COLOUR = {  # hex case matches common.js PARTY colours exactly
    "ALP": "#DE3533", "LP": "#1C4F9C", "NP": "#006644", "COAL": "#1C4F9C",
    "LNP": "#1C4F9C", "GRN": "#10C25B", "ON": "#FF7300", "IND": "#00A3A6",
    "IND*": "#00A3A6", "OTH": "#8E44AD",
}
GROUP_NAME = {
    "ALP": "Labor", "LP": "Liberal", "NP": "Nationals", "COAL": "Coalition",
    "LNP": "Coalition", "GRN": "Greens", "ON": "One Nation", "IND": "Independent",
    "IND*": "Independent", "OTH": "Others",
}
# Registered VEC party names -> short display names (mirrors common.js PARTY_SHORTNAME)
PARTY_SHORTNAME = {
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
}
BLOC_ORDER = ["COAL", "ALP", "ON", "GRN", "IND*"]


def esc(s):
    from html import escape as _e
    return _e(str(s if s is not None else ""), quote=True)


def pct1(x):
    return f"{float(x):.1f}%"


def fmt(n):
    return f"{int(n):,}"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _title_word(word):
    """Title-case one surname word: first letter and any letter after '-' or
    "'" upper, rest lower; 'Mc' names capitalise the following letter too
    ('Mac' names are left alone — MacKenzie vs McKenzie can't be told apart)."""
    out, cap_next = [], True
    for ch in word:
        out.append(ch.upper() if cap_next else ch.lower())
        cap_next = ch in "-'"
    w = "".join(out)
    if len(w) > 2 and w[:2] == "Mc":
        w = "Mc" + w[2].upper() + w[3:]
    return w


def _title_name(n):
    return " ".join(_title_word(w) for w in n.split(" "))


def disp_name(n):
    if "," not in n:
        return _title_name(n)
    sur, given = n.split(",", 1)[0].strip(), n.split(",", 1)[1].strip()
    return f"{given} {_title_name(sur)}" if given else _title_name(sur)


def disp_names(n):
    """Display form of a possibly pooled candidate name ("SURNAME, Given; ...")
    -> comma-separated given-first names; pooled independents get a label."""
    parts = ", ".join(disp_name(part.strip()) for part in n.split(";"))
    return parts


def short_party(full):
    return PARTY_SHORTNAME.get(full, full)


def pcolour(g):
    return GROUP_COLOUR.get(g, GROUP_COLOUR["OTH"])


def strength(p):
    """Map fill opacity for a favourite's win probability (mirrors forecastStyle)."""
    return max(0.15, min(0.85, (p - 0.3) / 0.7 * 0.85))


def pname(g):
    return GROUP_NAME.get(g, g)


def fill_marker(text, name, body):
    open_m, close_m = f"<!-- {name} -->", f"<!-- /{name} -->"
    if open_m not in text:
        return text
    start = text.index(open_m) + len(open_m)
    end = text.index(close_m)
    return text[:start] + body + text[end:]


SPECULATION = ('<script type="speculationrules">{"prerender":[{"where":{"href_matches":"/*",'
               '"not":{"href_matches":"/data/*"}},"eagerness":"moderate"}]}</script>')


def seo_block(title, desc, path, jsonld=None, index=True):
    lines = [f"<title>{esc(title)}</title>",
             f'<meta name="description" content="{esc(desc)}">']
    if index:
        url = DOMAIN + path
        lines += [
            f'<link rel="canonical" href="{url}">',
            '<meta property="og:type" content="website">',
            '<meta property="og:site_name" content="Seat Projections">',
            f'<meta property="og:title" content="{esc(title)}">',
            f'<meta property="og:description" content="{esc(desc)}">',
            f'<meta property="og:url" content="{url}">',
            f'<meta property="og:image" content="{DOMAIN}/assets/og-image.png">',
            '<meta property="og:image:width" content="1200">',
            '<meta property="og:image:height" content="630">',
            '<meta property="og:image:alt" content="Seat Projections: 2026 Victorian seat projections">',
            '<meta property="og:locale" content="en_AU">',
            '<meta name="twitter:card" content="summary_large_image">',
        ]
    else:
        lines.append('<meta name="robots" content="noindex">')
    lines.append(SPECULATION)
    if jsonld is not None:
        lines.append(f'<script type="application/ld+json">{json.dumps(jsonld, separators=(",", ":"))}</script>')
    return "\n".join(lines)


def shared_chrome():
    """Header (with active class cleared) and footer extracted from index.html."""
    text = (SITE / "index.html").read_text()
    header = re.search(r'<header class="site-header">.*?</header>', text, re.S).group(0)
    header = header.replace(' class="active"', "")
    footer = re.search(r'<footer class="site-footer">.*?</footer>', text, re.S).group(0)
    return header, footer


def page_head(meta):
    title, desc, path, jsonld = meta
    return f"""<!DOCTYPE html>
<html lang="en-AU">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{seo_block(title, desc, path, jsonld)}
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preload" href="/assets/fonts/inter-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/assets/fonts/newsreader-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/assets/style.css">
</head>
<body>
"""


def page_tail(extra=""):
    return f"""
<script src="/assets/common.js"></script>
{extra}</body>
</html>
"""


def district_svg(feature, colour, opacity):
    """Inline SVG of one district's (already display-simplified) geometry."""
    geoms = feature["geometry"]["coordinates"]
    if feature["geometry"]["type"] != "MultiPolygon":
        geoms = [geoms]
    rings = [ring for poly in geoms for ring in poly]
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    w, h = 200, 200
    pad = 8
    sx = (w - 2 * pad) / (maxx - minx) if maxx > minx else 1
    sy = (h - 2 * pad) / (maxy - miny) if maxy > miny else 1
    s = min(sx, sy)
    ox = pad + ((w - 2 * pad) - s * (maxx - minx)) / 2
    oy = pad + ((h - 2 * pad) - s * (maxy - miny)) / 2

    def xy(p):
        return f"{ox + (p[0] - minx) * s:.1f},{oy + (maxy - p[1]) * s:.1f}"

    d = " ".join("M" + "L".join(xy(p) for p in ring) + "Z" for ring in rings)
    return (f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="Outline of {esc(feature["properties"]["district"])} district" '
            f'style="display:block;max-width:100%"><path id="dtl-path" d="{d}" fill="{colour}" '
            f'fill-opacity="{opacity:.3f}" stroke="#fff" stroke-width="1"/></svg>')


def pair_block(pr, cand_by_id):
    a, b = pr["a"], pr["b"]
    party = {cid: c["party"] for cid, c in cand_by_id.items()}
    lo, mid, hi = pr["a_tcp"]

    def short(cid):
        return disp_names(str(cand_by_id.get(cid, {"id": cid})["id"]).split(",")[0])

    return f'''
    <div class="pair">
      <b>{esc(short(a))}</b> <span class="muted">{esc(party.get(a, "OTH"))}</span> v
      <b>{esc(short(b))}</b> <span class="muted">{esc(party.get(b, "OTH"))}</span>
      <div class="muted">final two in {round(100 * pr["p"])}% of simulations</div>
      <div class="split"><span style="width:{mid}%;background:{pcolour(party.get(a))}"></span><span style="width:{100 - mid}%;background:{pcolour(party.get(b))}"></span></div>
      <table><tr><th></th><th>2CP median</th><th>p10-p90</th><th>Wins pairing</th></tr>
        <tr><td>{esc(short(a))}</td><td class="num">{pct1(mid)}</td><td class="num">{pct1(lo)}-{pct1(hi)}</td><td class="num">{round(100 * pr["p_a_wins"])}%</td></tr>
        <tr><td>{esc(short(b))}</td><td class="num">{pct1(100 - mid)}</td><td class="num">{pct1(100 - hi)}-{pct1(100 - lo)}</td><td class="num">{round(100 * (1 - pr["p_a_wins"]))}%</td></tr></table>
    </div>'''


def district_page(name, slug_, feature, m2d, m1d, base, run_date, header, footer,
                  snaps=None, model2_doc=None):
    fav = max(m2d["candidates"], key=lambda c: c["p_win"])
    cand_by_id = {c["id"]: c for c in m2d["candidates"]}
    f2 = base["final_two"]
    tot2 = f2[0]["votes"] + f2[1]["votes"]

    cands = "".join(
        f"<tr><td>{esc(disp_names(c['id']))}{'' if c['core'] else ' <span class=muted>minor</span>'}</td>"
        f'<td><span class="swatch" style="background:{pcolour(c["party"])}"></span>{esc(c["party"])}</td>'
        f'<td class="r num">{pct1(c["primary"])}</td>'
        f'<td class="r num">{round(100 * c["p_final_two"])}%</td>'
        f'<td class="r num"><b>{round(100 * c["p_win"])}%</b></td></tr>'
        for c in sorted(m2d["candidates"], key=lambda c: (-round(100 * c["p_win"]), -c["primary"]))
        if c["p_final_two"] > 0 or c["primary"] >= 2 or c["p_win"] > 0)

    pairs = "".join(pair_block(p, cand_by_id) for p in m2d["pairs"][:4])

    b1 = "".join(
        f'<tr><td>{esc(("Independents (pooled): " if c["party"] == "IND*" and ";" in c["name"] else "") + disp_names(c["name"]))}</td>'
        f'<td><span class="swatch" style="background:{pcolour(c["party"])}"></span>{esc(c["party"])}</td>'
        f'<td class="r num">{pct1(c["primary"])}</td>'
        f'<td class="r num"><b>{round(100 * c["p_win"])}%</b></td></tr>'
        for c in sorted(m1d["candidates"], key=lambda c: (-round(100 * c["p_win"]), -c["primary"]))
        if c["p_win"] > 0 or c["p_final_two"] > 0 or c["primary"] >= 2)

    primaries = "".join(
        f"<tr{' class=final' if c['name'] == base['winner'] else ''}>"
        f'<td>{esc(disp_names(c["name"]))}</td>'
        f'<td title="{esc(c["party"])}"><span class="swatch" style="background:{pcolour(c["group"])}"></span>{esc(short_party(c["party"]))}</td>'
        f'<td class="r num">{fmt(c["votes"])}</td><td class="r num">{pct1(100 * c["votes"] / base["formal_votes"])}</td></tr>'
        for c in base["primary"])

    region = esc(feature["properties"]["region"])
    enc = name.replace(" ", "%20")

    body = f"""
<main class="wrap district-body">
  <p class="muted small" style="margin:1.5rem 0 0"><a href="/districts/">Districts</a> &rsaquo; {esc(name)}</p>
  <section class="hero" style="padding-top:0.75rem">
    <span class="eyebrow">District &middot; {region}</span>
    <h1>{esc(name)}</h1>
    <p class="lede">2026 Victorian state election forecast &middot; {region}</p>
  </section>

  <div class="twocol">
    <div>
      <section class="card">
        <div id="dtl-banner" hidden></div>
        <h3>Forecast Model <span class="muted small" style="font-weight:400" id="fc-sub">({esc(run_date)} forecast)</span></h3>
        <table class="dtable"><tr><th>Candidate</th><th>Party</th><th class="r">Primary</th><th class="r">Final two</th><th class="r">Win</th></tr>
        <tbody id="fc-cands">{cands}</tbody></table>
        <h4>Estimated two-candidate preferred</h4>
        <div class="dpanel" id="fc-pairs">{pairs}</div>
        <p class="muted small">Each block is one possible final pair, with the 2CP split across the simulations where that pair was the final two.</p>
      </section>

      {history_card(name, snaps or {}, model2_doc or {"districts": {name: m2d}})}

      <section class="card">
        <h3>Baseline Model</h3>
        <p class="muted small">Replays the 2025 federal result at this district&rsquo;s booths, restricted to parties standing in 2026, no polling.</p>
        <table class="dtable"><tr><th>Candidate(s)</th><th>Party</th><th class="r">Primary</th><th class="r">Win</th></tr>
        {b1}</table>
      </section>
    </div>

    <div>
      <section class="card">
        <div class="dsvg">{district_svg(feature, pcolour(fav["party"]), strength(fav["p_win"]))}</div>
        <div id="dtl-ui" style="margin:0.5rem 0 0.75rem"></div>
        <div class="dpanel">
          <div class="kv"><span>Favourite</span><b id="kv-fav">{esc(disp_names(fav["id"]))} <span class="muted">{esc(fav["party"])}</span></b></div>
          <div class="kv"><span>Win chance</span><b class="num" id="kv-win">{round(100 * fav["p_win"])}%</b></div>
          <div class="kv"><span>Region</span><b>{region}</b></div>
          <div class="kv"><span>2022 winner</span><b>{esc(disp_names(base["winner"]))} <span class="muted">{esc(base["winner_group"])}</span></b></div>
          <div class="kv"><span>2022 2CP margin</span><b class="num">+{base["margin_pct"]:.1f}%</b></div>
        </div>
      </section>

      <section class="card">
        <h3>2022 result</h3>
        <div class="dpanel">
          <h4>Two-candidate preferred</h4>
          <div class="pair">
            <b>{esc(disp_names(f2[0]["name"]))}</b> <span class="muted" title="{esc(f2[0]["party"])}">{esc(short_party(f2[0]["party"]))}</span> v
            <b>{esc(disp_names(f2[1]["name"]))}</b> <span class="muted" title="{esc(f2[1]["party"])}">{esc(short_party(f2[1]["party"]))}</span>
            <div class="split"><span style="width:{100 * f2[0]["votes"] / tot2:.1f}%;background:{pcolour(f2[0]["group"])}"></span><span style="width:{100 * f2[1]["votes"] / tot2:.1f}%;background:{pcolour(f2[1]["group"])}"></span></div>
            <table><tr><th></th><th>Votes</th><th class="r">2CP %</th></tr>
              <tr><td>{esc(disp_names(f2[0]["name"]))}</td><td class="num">{fmt(f2[0]["votes"])}</td><td class="r num">{100 * f2[0]["votes"] / tot2:.1f}%</td></tr>
              <tr><td>{esc(disp_names(f2[1]["name"]))}</td><td class="num">{fmt(f2[1]["votes"])}</td><td class="r num">{100 * f2[1]["votes"] / tot2:.1f}%</td></tr></table>
          </div>
          <h4>First preferences</h4>
          <table class="dtable"><tr><th>Candidate</th><th>Party</th><th class="r">Votes</th><th class="r">%</th></tr>
          {primaries}</table>
          <p style="margin-top:0.75rem"><a href="{esc(base["source_url"])}" target="_blank" rel="noopener">VEC result &amp; distribution &#8599;</a></p>
        </div>
      </section>
    </div>
  </div>

  <div class="caveat">
    <h3>Read before quoting</h3>
    <ul>
      <li><b>The ranges are too narrow.</b> Across five state election backtests, the
        Forecast Model&rsquo;s 80% ranges for the final two candidates contained the actual vote
        share about 59% of the time when it picked the correct final pair. Allow for more
        uncertainty than the ranges suggest.</li>
      <li><b>One Nation is harder to estimate.</b> Its local support and preference flows
        rely on assumptions.</li>
      <li>Full method: <a href="/methodology/">methodology &amp; open data</a>.</li>
    </ul>
  </div>

  <p><a href="/#model2/{enc}">Explore on the interactive forecast map &rarr;</a><br>
     <a href="/2022-results/#{enc}">See the 2022 result on the map &rarr;</a></p>
</main>
"""
    title = f"{name}: 2026 Victorian Election Forecast | Seat Projections"
    desc = (f"{disp_names(fav['id'])} ({fav['party']}) leads {name} with a "
            f"{round(100 * fav['p_win'])}% win chance in the Forecast Model. "
            f"2022: {disp_names(base['winner'])} ({base['winner_group']}), +{base['margin_pct']:.1f}%.")[:160]
    jsonld = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Districts", "item": f"{DOMAIN}/districts/"},
            {"@type": "ListItem", "position": 2, "name": name, "item": f"{DOMAIN}/districts/{slug_}/"},
        ],
    }
    timeline_html = ""
    extra_js = ""
    if snaps:
        tl = json.dumps(district_timeline(name, snaps, model2_doc), separators=(",", ":"))
        tl = tl.replace("<", "\\u003c")
        timeline_html = (f'<script type="application/json" id="district-timeline">{tl}</script>')
        extra_js = '<script src="/assets/district.js" defer></script>\n'
    return (page_head((title, desc, f"/districts/{slug_}/", jsonld))
            + header + body + timeline_html + footer + page_tail(extra_js))


def districts_hub(rows, header, footer):
    trs = "".join(
        f'<tr><td><a href="/districts/{s}/"><b>{esc(n)}</b></a></td>'
        f'<td class="muted col-region">{esc(region)}</td>'
        f'<td><span class="swatch" style="background:{pcolour(wg)}"></span>{esc(wg)}</td>'
        f'<td class="r num">+{margin:.1f}%</td>'
        f'<td><span class="swatch" style="background:{pcolour(fp)}"></span>{esc(fn)} <span class="muted">{esc(fp)}</span></td>'
        f'<td class="r num">{round(100 * fw)}%</td></tr>'
        for n, s, region, wg, margin, fn, fp, fw in rows)
    body = f"""
<main class="wrap">
  <section class="hero">
    <span class="eyebrow">Districts &middot; 88 seats</span>
    <h1>All 88 districts</h1>
    <p class="lede">Every Victorian Legislative Assembly district: the 2022 result and the current
      Forecast Model favourite. Click through for candidates, final pairs and first preferences.</p>
  </section>
  <section class="card" style="overflow-x:auto">
    <table class="dtable"><tr><th>District</th><th class="col-region">Region</th><th>2022 winner</th><th class="r">2CP margin</th><th>2026 favourite</th><th class="r">Win chance</th></tr>
    {trs}</table>
  </section>
</main>
"""
    title = "All 88 Districts: Victorian Election 2026 Forecast | Seat Projections"
    desc = ("Forecasts and 2022 results for all 88 Victorian Legislative Assembly "
            "districts: favourites, win chances, final pairs and first preferences.")[:160]
    return (page_head((title, desc, "/districts/", None))
            + header + body + footer + page_tail())


def write_headline(doc):
    """Fill the static headline markers on / with the Forecast Model's content —
    byte-identical to what projections.js writes for model2, so no layout shift."""
    m = doc["meta"]
    blocs = {b["party"]: b for b in doc["blocs"]}
    parts = {s["party"]: s for s in doc["seats"]}
    coal_note = (f"Liberal {parts['LP']['seats_mean']:.1f} + Nationals {parts['NP']['seats_mean']:.1f}"
                 if "LP" in parts and "NP" in parts else "")

    def bloc_card(g):
        b = blocs[g]
        pmaj = (f"{round(100 * b['p_majority'])}% chance of a majority"
                if b["p_majority"] > 0.005 else "&nbsp;")
        coal = f'<div class="range">{esc(coal_note)}</div>' if g == "COAL" and coal_note else ""
        return ('<div class="card bloc-card" style="border-top-color:' + pcolour(g) + '">\n'
                '      <div class="party-l" style="font-size:0.6875rem;font-weight:600;letter-spacing:0.05em;text-transform:uppercase;color:var(--ink-2)">' + esc(pname(g)) + '</div>\n'
                '      <div style="display:flex;align-items:baseline;gap:0.5rem;margin:0.25rem 0"><b class="num" style="font-size:2.25rem;letter-spacing:-0.02em">' + f"{b['seats_mean']:.1f}" + '</b>\n'
                '        <span class="range num">p10-p90: ' + f"{b['seats_p10']:.0f}" + '-' + f"{b['seats_p90']:.0f}" + '</span></div>\n'
                '      <div class="pmaj">' + pmaj + '</div>\n'
                '      ' + coal + '\n'
                '    </div>')

    order = [g for g in BLOC_ORDER if g in blocs]
    cards = "".join(bloc_card(g) for g in order)
    majbar = "".join(
        '<div class="seg" style="width:' + repr(100 * blocs[g]["seats_mean"] / 88) + '%;background:' + pcolour(g)
        + '" title="' + esc(pname(g)) + ' ' + f"{blocs[g]['seats_mean']:.1f}" + '"></div>'
        for g in order)
    majbar += ('<div class="needle" data-label="' + str(m["majority"]) + ' to govern" style="left:'
               + repr(100 * m["majority"] / 88) + '%"></div>')
    legend = "".join(
        '<span><span class="swatch" style="background:' + pcolour(g) + '"></span>' + esc(pname(g))
        + ' <b class="num">' + f"{blocs[g]['seats_mean']:.1f}" + '</b></span>' for g in order)

    commit = f' · commit {m["git_commit"][:7]}' if m.get("git_commit") else ""
    caveat = (f'<b>Run:</b> {esc(m["run_id"])}, forecast dated {esc((m.get("timestamp") or "")[:10])}'
              + (f', commit <span class="mono">{esc(m["git_commit"][:7])}</span>' if m.get("git_commit") else "") + ".")

    page = SITE / "index.html"
    text = page.read_text()
    for name, body in [
        ("run-desc", esc(m["description"])),
        ("run-meta", f'{fmt(m["runs"])} simulations · run {esc(m["run_id"])} · {(m.get("timestamp") or "")[:10]}{commit}'),
        ("caveat-meta", caveat),
        ("map-sub", "(Forecast Model)"),
        ("bloc-cards", cards),
        ("majbar", majbar),
        ("maj-legend", legend),
    ]:
        text = fill_marker(text, name, body)
    page.write_text(text)


def home_jsonld():
    return {"@context": "https://schema.org", "@graph": [
        {"@type": "WebSite", "name": "Seat Projections", "url": DOMAIN + "/"},
        {"@type": "Organization", "name": "Seat Projections", "url": DOMAIN + "/",
         "logo": f"{DOMAIN}/assets/logo.svg", "email": "hello@seatprojections.au"},
    ]}


def dataset_jsonld(downloads):
    enc = {"csv": "text/csv", "json": "application/json", "geojson": "application/geo+json"}
    return {
        "@context": "https://schema.org", "@type": "Dataset",
        "name": "Victorian Election 2026: Seat Projections data",
        "description": ("Forecast Model and Baseline Model seat probabilities for all 88 Victorian "
                        "districts, 2022 official results, polling register and district boundaries."),
        "url": f"{DOMAIN}/methodology/",
        "license": "https://creativecommons.org/licenses/by-sa/4.0/",
        "creator": {"@type": "Organization", "name": "Seat Projections", "url": DOMAIN + "/"},
        "isAccessibleForFree": True,
        "keywords": ["Victorian election 2026", "seat projections", "preferential voting", "IRV"],
        "temporalCoverage": "2022/2026",
        "spatialCoverage": {"@type": "Place", "name": "Victoria, Australia"},
        "distribution": [
            {"@type": "DataDownload", "name": d["file"],
             "contentUrl": f"{DOMAIN}/data/downloads/{d['file']}",
             "encodingFormat": enc.get(d["file"].rsplit(".", 1)[-1], "application/octet-stream")}
            for d in downloads],
    }


def write_seo(downloads, blocs):
    """Fill <!-- seo --> markers on the hand-written pages."""
    seats = {b["party"]: round(b["seats_mean"]) for b in blocs}
    pmaj = {b["party"]: b["p_majority"] for b in blocs}
    home_desc = (f"Forecast Model: Coalition {seats['COAL']} seats ({round(100 * pmaj['COAL'])}% chance "
                 f"of a majority), Labor {seats['ALP']}, One Nation {seats['ON']}, Greens {seats['GRN']}: "
                 "preferential-count projections for all 88 districts.")
    pages = {
        "index.html": ("Victorian Election 2026 Forecast & Seat Projections | Seat Projections",
                       home_desc, "/", home_jsonld()),
        "2022-results/index.html": ("2022 Victorian Election Results by District | Seat Projections",
                                    "Official 2022 Victorian state election results for all 88 districts: "
                                    "elected members, two-candidate margins and first preferences.",
                                    "/2022-results/", None),
        "methodology/index.html": ("Methodology & Open Data | Seat Projections",
                                   "How past election results and current polls become seat projections "
                                   "for Victoria. Explore the models, past performance, data and code.",
                                   "/methodology/", dataset_jsonld(downloads)),
        "methodology/baseline/index.html": ("Baseline Model: Methodology | Seat Projections",
                                            "The Baseline Model: 2025 federal polling-place votes replayed "
                                            "into state districts with fitted preference flows, no polling.",
                                            "/methodology/baseline/", None),
        "methodology/forecast/index.html": ("Forecast Model: Methodology | Seat Projections",
                                            "How the Forecast Model combines past state results, current polls "
                                            "and local candidates to estimate each candidate's chance of winning.",
                                            "/methodology/forecast/", None),
        "404.html": ("Page not found | Seat Projections",
                     "The page you were looking for does not exist.", None, None),
    }
    for rel, (title, desc, path, jsonld) in pages.items():
        p = SITE / rel
        idx = rel != "404.html"
        p.write_text(fill_marker(p.read_text(), "seo", seo_block(title, desc, path or "", jsonld, index=idx)))


SNAPSHOT_RUNS = ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 snapshots"
SNAPSHOT_RUNS_FED = ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 fed snapshots"

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def load_snapshot_docs(runs_dir=SNAPSHOT_RUNS, model="model2"):
    """Forecast Model history docs {date: doc} from output/<snapshot dir>/<date>/."""
    docs = {}
    if runs_dir.exists():
        for d in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
            doc = forecast_doc(d, FORECASTS[model][1])
            doc["meta"]["description"] = doc["meta"]["description"].replace(
                "Model 2", "Forecast Model")
            docs[d.name] = doc
    return docs


def _bloc_summary(doc):
    return {b["party"]: {k: b[k] for k in ("seats_mean", "seats_p10", "seats_p90", "p_majority")}
            for b in doc["blocs"]}


def write_snapshots(snaps, model2_doc, subdir="model2"):
    """site/data/snapshots/<subdir>/<date>.json + the shared index.json (state baseline only)."""
    snap_dir = DATA / "snapshots" / subdir
    snap_dir.mkdir(parents=True, exist_ok=True)
    for old in snap_dir.glob("*.json"):
        old.unlink()
    entries = []
    for date, doc in snaps.items():
        (snap_dir / f"{date}.json").write_text(json.dumps(doc, separators=(",", ":")))
        m = doc["meta"]
        entries.append({"date": date, "generated": m["generated"],
                        "retrospective": m["retrospective"],
                        "polls": m["polls"], "polls_used": m["polls_used"],
                        "blocs": _bloc_summary(doc)})
    if subdir == "model2":
        index = {"snapshots": entries,
                 "latest": {"generated": model2_doc["meta"]["timestamp"][:10],
                            "polls_used": model2_doc["meta"]["polls_used"],
                            "blocs": _bloc_summary(model2_doc)}}
        (DATA / "snapshots" / "index.json").write_text(json.dumps(index, separators=(",", ":")))
    write_map_timeline(snaps, model2_doc, snap_dir / "map_timeline.json" if subdir != "model2" else None)


def write_map_timeline(snaps, model2_doc, path=None):
    """Compact per-district p_win series for the map timeline slider."""
    docs = list(snaps.items()) + [(model2_doc["meta"]["timestamp"][:10], model2_doc)]
    points = [{"date": d, "retrospective": doc["meta"].get("retrospective", False)}
              for d, doc in docs]
    points[-1] = {"date": model2_doc["meta"]["timestamp"][:10], "latest": True}
    districts = {}
    for name in model2_doc["districts"]:
        ids = {c["id"] for doc_c in (d["districts"][name]["candidates"] for _, d in docs)
               for c in doc_c if c["p_win"] >= 0.005}
        cands, party = [], {}
        for _, doc in docs:
            for c in doc["districts"][name]["candidates"]:
                if c["id"] in ids:
                    party[c["id"]] = c["party"]
        cands = [[cid, party[cid]] for cid in sorted(ids)]
        p = [[round(next((c["p_win"] for c in doc["districts"][name]["candidates"]
                          if c["id"] == cid), 0.0), 3) for cid, _ in cands]
             for _, doc in docs]
        districts[name] = {"cands": cands, "p": p}
    out = {"points": points, "districts": districts}
    (path or (DATA / "snapshots" / "map_timeline.json")).write_text(json.dumps(out, separators=(",", ":")))


def history_card(name, snaps, model2_doc):
    """'How the forecast has moved': win % for the latest top-3 candidates per snapshot."""
    if not snaps:
        return ""
    enc = name.replace(" ", "%20")
    top3 = [c for c in sorted(model2_doc["districts"][name]["candidates"],
                              key=lambda c: -c["p_win"])[:3]]
    head = "<th>Polls to</th>" + "".join(
        f'<th class="r"><span class="swatch" style="background:{pcolour(c["party"])}"></span>'
        f'{esc(disp_names(c["id"]))}</th>' for c in top3)

    def win(doc, cid):
        c = next((c for c in doc["districts"][name]["candidates"] if c["id"] == cid), None)
        return f"{round(100 * c['p_win'])}%" if c else "N/A"

    rows = "".join(
        f'<tr data-date="{d}"><td><a href="/#model2/{enc}@{d}">{int(d[8:])} {MONTHS[int(d[5:7]) - 1]}</a></td>'
        + "".join(f'<td class="r num">{win(doc, c["id"])}</td>' for c in top3) + "</tr>"
        for d, doc in snaps.items())
    rows += (f'<tr data-latest><td><a href="/#model2/{enc}"><b>Latest</b></a></td>'
             + "".join(f'<td class="r num"><b>{win(model2_doc, c["id"])}</b></td>' for c in top3)
             + "</tr>")
    gen = next(reversed(snaps.values()))["meta"]["generated"]
    return f"""
      <section class="card" id="dtl-hist">
        <h3>How the forecast has moved</h3>
        <table class="dtable"><tr>{head}</tr>{rows}</table>
        <p class="muted small">Retrospective rows were generated on {int(gen[8:])} {MONTHS[int(gen[5:7]) - 1]} {gen[:4]} using only polls
          published by each date. The candidate list and model settings are the final November
          versions. <a href="/methodology/forecast/#history">Forecast history &rarr;</a></p>
      </section>"""


def district_timeline(name, snaps, model2_doc):
    """Inline per-point candidate/pair data for the district-page timeline slider."""
    docs = list(snaps.items()) + [("latest", model2_doc)]

    def shown(c):
        return c["p_final_two"] > 0 or c["primary"] >= 2 or c["p_win"] > 0

    ids, party = [], {}
    for c in sorted(model2_doc["districts"][name]["candidates"],
                    key=lambda c: (-round(100 * c["p_win"]), -c["primary"])):
        if shown(c):
            ids.append(c["id"])
            party[c["id"]] = c["party"]
    for _, doc in docs:
        for c in sorted(doc["districts"][name]["candidates"], key=lambda c: -c["p_win"]):
            if shown(c) and c["id"] not in party:
                ids.append(c["id"])
                party[c["id"]] = c["party"]
    cands = [{"id": i, "party": party[i]} for i in ids]
    points = [{"date": d, "retrospective": doc["meta"]["retrospective"],
               "generated": doc["meta"]["generated"]} for d, doc in docs[:-1]]
    points.append({"date": model2_doc["meta"]["timestamp"][:10], "latest": True})
    rows = []
    for _, doc in docs:
        d = doc["districts"][name]
        byid = {c["id"]: c for c in d["candidates"]}
        rows.append({
            "c": [[round(byid[i]["primary"], 1), round(byid[i]["p_final_two"], 3),
                   round(byid[i]["p_win"], 3)] if i in byid else [0.0, 0, 0] for i in ids],
            "pairs": [{"p": p["p"], "a": p["a"], "b": p["b"],
                       "a_tcp": p["a_tcp"], "p_a_wins": p["p_a_wins"]}
                      for p in d["pairs"][:4]],
        })
    return {"points": points, "district": {"cands": cands, "rows": rows}}


def write_district_pages(simp_features, baseline, model1_doc, model2_doc, snaps=None):
    header, footer = shared_chrome()
    feats = {f["properties"]["district"]: f for f in simp_features}
    run_date = (model2_doc["meta"].get("timestamp") or "")[:10]
    dist_dir = SITE / "districts"
    rows = []
    for name in sorted(model2_doc["districts"], key=slug):
        s = slug(name)
        m2d = model2_doc["districts"][name]
        base = baseline["districts"][name]
        fav = max(m2d["candidates"], key=lambda c: c["p_win"])
        rows.append((name, s, feats[name]["properties"]["region"], base["winner_group"],
                     base["margin_pct"], disp_names(fav["id"]), fav["party"], fav["p_win"]))
        d = dist_dir / s
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            district_page(name, s, feats[name], m2d, model1_doc["districts"][name],
                          base, run_date, header, footer, snaps=snaps,
                          model2_doc=model2_doc))
    (dist_dir / "index.html").write_text(districts_hub(rows, header, footer))


def write_sitemap():
    date = json.loads((DATA / "model2_vic2026.json").read_text())["meta"]["timestamp"][:10]
    urls = ["/", "/2022-results/", "/methodology/", "/methodology/baseline/",
            "/methodology/forecast/", "/districts/"]
    urls += [f"/districts/{p.parent.name}/"
             for p in sorted((SITE / "districts").rglob("index.html"))
             if p.parent.name != "districts"]
    body = "".join(
        f"  <url><loc>{DOMAIN}{u}</loc><lastmod>{date}</lastmod></url>\n" for u in urls)
    (SITE / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + body + "</urlset>\n")
    (SITE / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nDisallow: /data/snapshots/\n\n"
        "Sitemap: https://seatprojections.au/sitemap.xml\n")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)

    baseline = load_baseline()
    (DATA / "baseline_2022.json").write_text(json.dumps(baseline, separators=(",", ":")))

    geojson = json.loads((VIS / "districts.geojson").read_text())
    slim_features = [
        {
            "type": "Feature",
            "properties": {
                "district": f["properties"]["district"],
                "region": f["properties"]["region"],
            },
            "geometry": f["geometry"],
        }
        for f in geojson["features"]
    ]
    # Downloadable dataset keeps full resolution; the display copy is simplified.
    (DOWNLOADS / "districts.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": [
            {**f, "geometry": round_coords(f["geometry"])} for f in slim_features
        ]}, separators=(",", ":"))
    )
    simp_features, outline = simplify_districts(slim_features)
    simp_features = [{**f, "geometry": round_coords(f["geometry"], DISPLAY_PREC)} for f in simp_features]
    geo_text = json.dumps({"type": "FeatureCollection", "features": simp_features}, separators=(",", ":"))
    (DATA / "districts.geojson").write_text(geo_text)
    (DATA / "victoria_outline.json").write_text(json.dumps(outline, separators=(",", ":")))

    model_meta = {}
    model2_doc = None
    for model in ("model1", "model2", "model2fed"):
        src = VIS / f"{model}_vic2026.json"
        doc = json.loads(src.read_text())
        model_meta[model] = doc["meta"]
        model_meta[model]["description"] = model_meta[model]["description"].replace(
            "Model 1", "Baseline Model").replace("Model 2", "Forecast Model")
        if model == "model2":
            model2_doc = doc
        elif model == "model1":
            model1_doc = doc
        (DATA / src.name).write_text(json.dumps(doc, separators=(",", ":")))

    (DATA / "benchmarks.json").write_text(json.dumps(benchmarks(), separators=(",", ":")))

    # Downloads register: (output filename, source or generator, description)
    copies = [
        (
            "vic2022_district_results.csv",
            None,
            "2022 district results: elected member, final two, 2CP margin, enrolment (derived from VEC distributions)",
        ),
        (
            "model1_seat_probabilities.csv",
            ROOT / "predictions" / "modelling" / "model1" / "output" / "VIC2026 (2025)" / "seat_probabilities.csv",
            "Baseline Model: per-district win and final-two probabilities (VIC2026 (2025) run)",
        ),
        (
            "model1_statewide_blocs.csv",
            ROOT / "predictions" / "modelling" / "model1" / "output" / "VIC2026 (2025)" / "statewide_blocs.csv",
            "Baseline Model: statewide seat distribution per bloc",
        ),
        (
            "model2_seat_probabilities.csv",
            ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 (2022)" / "seat_probabilities.csv",
            "Forecast Model: per-district win and final-two probabilities (VIC2026 (2022) run)",
        ),
        (
            "model2_statewide_blocs.csv",
            ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 (2022)" / "statewide_blocs.csv",
            "Forecast Model: statewide seat distribution per bloc",
        ),
        (
            "model2fed_seat_probabilities.csv",
            ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 (fed2025)" / "seat_probabilities.csv",
            "Forecast Model, federal baseline: per-district win and final-two probabilities (VIC2026 (fed2025) run)",
        ),
        (
            "model2fed_statewide_blocs.csv",
            ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 (fed2025)" / "statewide_blocs.csv",
            "Forecast Model, federal baseline: statewide seat distribution per bloc",
        ),
        (
            "candidates_vic2026.csv",
            ROOT / "data" / "2026" / "candidates_vic2026.csv",
            "Declared 2026 candidates by district and ballot position (VEC nominations; names and parties only)",
        ),
        (
            "polls_vic2026.csv",
            ROOT / "data" / "2026" / "polls_vic2026.csv",
            "2026 Victorian polling register used for the forecast model average (from electiontracker.au)",
        ),
    ]
    (DOWNLOADS / "vic2022_district_results.csv").write_text(results_csv(baseline))
    for fname, src, _desc in copies:
        if src is not None:
            shutil.copyfile(src, DOWNLOADS / fname)

    downloads = [
        {
            "file": fname,
            "size_kb": round((DOWNLOADS / fname).stat().st_size / 1024, 1),
            "description": desc,
        }
        for fname, _src, desc in [("districts.geojson", None, "88 Legislative Assembly district boundaries, 2021 redivision (Electoral Boundaries Commission)")] + copies
    ]

    site = {
        "brand": "Seat Projections",
        "domain": "seatprojections.au",
        "repo_url": REPO_URL,
        "build_date": model_meta["model2"]["timestamp"][:10],
        "models": model_meta,
        "downloads": downloads,
    }
    (DATA / "site.json").write_text(json.dumps(site, indent=1) + "\n")

    snaps = load_snapshot_docs()
    write_snapshots(snaps, model2_doc)
    fed_doc = json.loads((VIS / "model2fed_vic2026.json").read_text())
    write_snapshots(load_snapshot_docs(SNAPSHOT_RUNS_FED, "model2fed"), fed_doc, subdir="model2fed")
    write_header_chips(model2_doc["blocs"])
    write_headline(model2_doc)
    write_seo(downloads, model2_doc["blocs"])
    write_district_pages(simp_features, baseline, model1_doc, model2_doc, snaps)
    write_sitemap()

    for path in sorted(DATA.rglob("*")):
        if path.is_file():
            print(f"{path.relative_to(SITE)}  {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
