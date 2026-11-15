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
  benchmarks.json          archived benchmark results (model1 forecast runs, model2 B1 replays)
  site.json                REPO_URL, build date, forecast run metadata, downloadable-file register
  downloads/               public copies of the datasets listed on the Methodology page

The HTML/CSS/JS under site/ is hand-written; this script only produces data files.
Serve with:  .venv/bin/python -m http.server 8001 -d site
"""
from __future__ import annotations

import csv
import json
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

    return {
        "model1_runs": slim(read(MODEL1_CANDIDATES)),
        "model2_replays": slim(read(MODEL2_CANDIDATES)),
    }


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
    for model in ("model1", "model2"):
        src = VIS / f"{model}_vic2026.json"
        doc = json.loads(src.read_text())
        model_meta[model] = doc["meta"]
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
            "Model 1 forecast: per-district win and final-two probabilities (VIC2026 (2025) run)",
        ),
        (
            "model1_statewide_blocs.csv",
            ROOT / "predictions" / "modelling" / "model1" / "output" / "VIC2026 (2025)" / "statewide_blocs.csv",
            "Model 1 forecast: statewide seat distribution per bloc",
        ),
        (
            "model2_seat_probabilities.csv",
            ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 (2022)" / "seat_probabilities.csv",
            "Model 2 forecast: per-district win and final-two probabilities (VIC2026 (2022) run)",
        ),
        (
            "model2_statewide_blocs.csv",
            ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 (2022)" / "statewide_blocs.csv",
            "Model 2 forecast: statewide seat distribution per bloc",
        ),
        (
            "candidates_vic2026.csv",
            ROOT / "data" / "2026" / "candidates_vic2026.csv",
            "Declared 2026 candidates by district and ballot position (VEC nominations; names and parties only)",
        ),
        (
            "polls_vic2026.csv",
            ROOT / "data" / "2026" / "polls_vic2026.csv",
            "2026 Victorian polling register used for the model2 average (from electiontracker.au)",
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

    for path in sorted(DATA.rglob("*")):
        if path.is_file():
            print(f"{path.relative_to(SITE)}  {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
