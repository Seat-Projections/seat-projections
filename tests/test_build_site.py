from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_site  # noqa: E402


def resolve_path(href):
    """Resolve a root-absolute or page-relative site path to a filesystem path.
    '/x/' -> site/x/index.html, '/x' -> site/x, '#a' -> None (skip)."""
    path = href.split("#")[0].split("?")[0]
    if not path:
        return None
    p = SITE_DIR / path.lstrip("/") if path.startswith("/") else SITE_DIR / path
    return p / "index.html" if path.endswith("/") else p


def test_internal_links_resolve():
    """Every internal href/src in site HTML resolves to an existing file, and
    each redirect stub points at a real page."""
    import re
    for f in SITE_DIR.rglob("*.html"):
        if "vendor" in f.parts:
            continue
        for attr in re.findall(r'(?:href|src)="([^"]+)"', f.read_text()):
            if attr.startswith(("http", "mailto:", "#", "data:")) or attr == "#":
                continue
            target = resolve_path(attr)
            if target is None:
                continue
            assert target.is_file(), f"{f.name}: {attr} does not resolve"


def test_baseline_2022_seat_tally():
    baseline = build_site.load_baseline()
    assert len(baseline["districts"]) == 88
    assert baseline["seats"] == {"ALP": 56, "LP": 19, "NP": 9, "GRN": 4}
    # every district has a real two-candidate final and a positive margin
    for name, d in baseline["districts"].items():
        assert len(d["final_two"]) == 2, name
        assert d["final_two"][0]["name"] == d["winner"], name
        assert d["margin_pct"] > 0, name
        assert d["formal_votes"] > 0 and d["enrolment"] > 0, name


def test_simplified_districts_share_boundaries():
    """Topology-preserving simplification: neighbouring districts must keep
    identical shared boundary sequences — no gaps or slivers."""
    import json

    geo = json.loads((build_site.VIS / "districts.geojson").read_text())
    feats, outline = build_site.simplify_districts(geo["features"])
    assert len(feats) == 88

    rings = []
    for f in feats:
        coords = f["geometry"]["coordinates"]
        parts = coords if f["geometry"]["type"] == "MultiPolygon" else [coords]
        for part in parts:
            for ring in part:
                assert len(ring) >= 4  # no collapsed rings
                assert ring[0] == ring[-1]
                # output files are written at 4-decimal precision; round here so
                # the outline's rounded vertices compare equal to ring vertices
                rings.append([(round(x, 4), round(y, 4)) for x, y in ring[:-1]])

    verts_of = [set(r) for r in rings]
    edges_of = [{(min(a, b), max(a, b)) for a, b in zip(r, r[1:] + r[:1])} for r in rings]

    # For every pair of rings sharing ≥3 vertices, the cyclic order of their
    # common vertices must agree (same or reversed). If arcs were simplified
    # independently, one side could keep a vertex the other dropped and the
    # orders would diverge. Rings that only touch at ≤2 point-contacts are
    # consistent by definition.
    shared_pairs = 0
    for i in range(len(rings)):
        for j in range(i + 1, len(rings)):
            common = verts_of[i] & verts_of[j]
            if len(common) < 3:
                continue
            shared_pairs += 1
            oi = [p for p in rings[i] if p in common]
            oj = [p for p in rings[j] if p in common]
            for cand in (oj, list(reversed(oj))):
                k = cand.index(oi[0])
                if oi == cand[k:] + cand[:k]:
                    break
            else:
                raise AssertionError((i, j, oi[:5], oj[:5]))
    assert shared_pairs > 50  # sanity: there really are many neighbouring pairs

    all_edges = set().union(*edges_of)
    for loop in outline:
        assert loop[0] == loop[-1] and len(loop) >= 4
        assert all(-40 <= lat <= -33 and 140 <= lon <= 151 for lat, lon in loop)
        # Every outline edge is a district edge: the mask is built from the same
        # simplified arcs, so it coincides vertex-for-vertex with the polygons.
        loop_pts = [(lon, lat) for lat, lon in loop]
        for a, b in zip(loop_pts, loop_pts[1:]):
            assert (min(a, b), max(a, b)) in all_edges, (a, b)


SITE_DIR = Path(__file__).resolve().parent.parent / "site"


def site_pages():
    """Site pages: every *.html under site/, excluding vendored files."""
    return [f for f in sorted(SITE_DIR.rglob("*.html")) if "vendor" not in f.parts]


def test_all_pages_have_identical_header():
    """Every site page shares the same <header> block, modulo the
    active class on the nav links."""
    import re
    headers = {}
    for f in site_pages():
        text = f.read_text()
        m = re.search(r"<header.*?</header>", text, re.S)
        assert m, f"{f.name} has no <header>"
        headers[str(f.relative_to(SITE_DIR))] = re.sub(r' class="active"', "", m.group(0))
    unique = set(headers.values())
    assert len(unique) == 1, (
        "headers differ beyond the active class: "
        + ", ".join(h for h, v in headers.items() if v not in {list(unique)[0]})
    )


def test_methodology_dropdown_links_exist():
    """Every href inside the methodology nav menu must resolve to a real page."""
    import re
    for f in site_pages():
        text = f.read_text()
        menu = re.search(r'<div class="nav-menu">(.*?)</div>', text, re.S)
        assert menu, f"{f.name} has no nav-menu"
        for href in re.findall(r'href="([^"]+)"', menu.group(1)):
            assert resolve_path(href).is_file(), f"{f.name} links to missing {href}"
    # the two model detail pages exist; the other sections live on the overview
    assert (SITE_DIR / "methodology" / "baseline" / "index.html").exists()
    assert (SITE_DIR / "methodology" / "forecast" / "index.html").exists()


def test_outline_has_no_nested_rings():
    """Outline rings drawn as mask holes must not nest: a ring inside another
    hole is stroked and refilled as an island of mask colour, which shows
    through the district fills as dark doubled borders."""
    import json

    geo = json.loads((build_site.VIS / "districts.geojson").read_text())
    _, outline = build_site.simplify_districts(geo["features"])

    def inside(px, py, ring):
        ins = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
                ins = not ins
            j = i
        return ins

    for i, r in enumerate(outline):
        cx = sum(p[0] for p in r[:-1]) / (len(r) - 1)
        cy = sum(p[1] for p in r[:-1]) / (len(r) - 1)
        for j, other in enumerate(outline):
            if i != j:
                assert not inside(cx, cy, other), f"outline ring {i} is inside ring {j}"


def test_header_forecast_chips_match_model2():
    """Every page's forecast chips equal the rounded model2 bloc seat means."""
    import json, re
    blocs = {b["party"]: round(b["seats_mean"])
             for b in json.loads((SITE_DIR / "data" / "model2_vic2026.json").read_text())["blocs"]}
    expected = [("COA", blocs["COAL"]), ("ALP", blocs["ALP"]), ("ONP", blocs["ON"]),
                ("GRN", blocs["GRN"]), ("IND", blocs["IND*"])]
    for f in site_pages():
        text = f.read_text()
        m = re.search(r"<!-- forecast-chips -->(.*?)<!-- /forecast-chips -->", text, re.S)
        assert m, f"{f.name} missing forecast-chips markers"
        got = re.findall(r"</i>([A-Z*]+) (\d+)</span>", m.group(1))
        assert got == [(k, str(v)) for k, v in expected], (f.name, got)
        assert "45 to win" in m.group(1) and "2026 forecast" in m.group(1)


def test_district_slugs_unique_and_match_js():
    """Python slug() must be unique across the 88 districts and identical to
    common.js's districtSlug (district-page links depend on it)."""
    import re
    model2 = __import__("json").loads((SITE_DIR / "data" / "model2_vic2026.json").read_text())
    slugs = [build_site.slug(n) for n in model2["districts"]]
    assert len(slugs) == len(set(slugs)) == 88
    # JS: s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "")
    def js_slug(s):
        return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))
    for n in model2["districts"]:
        assert build_site.slug(n) == js_slug(n), n
        assert (SITE_DIR / "districts" / js_slug(n) / "index.html").exists(), n


def test_jsonld_blocks_parse():
    """Every application/ld+json script parses as JSON with @context/@type
    (or an @graph of typed nodes)."""
    import json, re
    count = 0
    for f in site_pages():
        for block in re.findall(
                r'<script type="application/ld\+json">(.*?)</script>', f.read_text()):
            doc = json.loads(block)
            assert doc.get("@context") and (doc.get("@type") or doc.get("@graph")), f.name
            count += 1
    assert count >= 90  # 88 breadcrumbs + home graph + dataset


def test_sitemap_matches_canonicals():
    """sitemap.xml lists exactly the canonical URLs of the indexable pages."""
    import re, xml.etree.ElementTree as ET
    canon = set()
    for f in site_pages():
        if f.name == "404.html":
            continue
        m = re.search(r'<link rel="canonical" href="([^"]+)"', f.read_text())
        assert m, f"{f.name} has no canonical"
        canon.add(m.group(1))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    tree = ET.parse(SITE_DIR / "sitemap.xml")
    urls = {loc.text for loc in tree.findall(".//s:loc", ns)}
    assert urls == canon, urls ^ canon


def test_pooled_names_render_cleanly():
    """Pooled IND* candidates must render as 'Independents (pooled): Given
    Surname, ...' — no raw 'SURNAME, Given' or ';' separators in name cells."""
    import re
    kew = (SITE_DIR / "districts" / "kew" / "index.html").read_text()
    assert "Independents (pooled): Man Liang, Sophie Torney, Finlay Davis" in kew
    for f in SITE_DIR.glob("districts/*/index.html"):
        text = f.read_text()
        for cell in re.findall(r"(?:<td>|<b>)([^<]+)(?:</td>|</b>)", text):
            cell = __import__("html").unescape(cell)
            assert ";" not in cell, (f.name, cell)
            assert not re.search(r"[A-Z]{2,}, [A-Z]", cell), (f.name, cell)
            # no all-caps surnames (>=3 consecutive capitals) in name text;
            # party codes are wrapped in <span>/<td class> and don't reach <b>/<td>
            assert not re.search(r"\b[A-Z]{4,}\b", cell), (f.name, cell)


def test_name_casing():
    """disp_name handles Mc / O' / hyphen surnames and leaves given names."""
    dn = build_site.disp_name
    assert dn("MCCURDY, Tim") == "Tim McCurdy"
    assert dn("O'HALLORAN, Paul") == "Paul O'Halloran"
    assert dn("NORTON-SMITH, Jane") == "Jane Norton-Smith"
    assert dn("MACKALLAH, Chloe") == "Chloe Mackallah"  # Mac names not guessed
    assert dn("MCRAE MCLEOD, Marley") == "Marley McRae McLeod"
    assert dn("WILSON") == "Wilson"  # bare surname (pair headings)
    assert dn("CUPPER, Ali") == "Ali Cupper"


def test_snapshot_index_consistent():
    import json
    idx = json.loads((SITE_DIR / "data/snapshots/index.json").read_text())
    dates = [s["date"] for s in idx["snapshots"]]
    assert dates == sorted(dates)
    for s in idx["snapshots"]:
        f = SITE_DIR / "data/snapshots/model2" / f"{s['date']}.json"
        assert f.is_file(), f"missing {f}"
        doc = json.loads(f.read_text())
        assert doc["meta"]["as_of"] == s["date"] and doc["meta"]["generated"] == s["generated"]
    latest = json.loads((SITE_DIR / "data/model2_vic2026.json").read_text())
    lb = {b["party"]: {k: b[k] for k in ("seats_mean", "seats_p10", "seats_p90", "p_majority")}
          for b in latest["blocs"]}
    assert idx["latest"]["blocs"] == lb


def test_snapshots_respect_poll_cutoff_and_retrospective():
    import csv, json
    from datetime import date, timedelta
    end_by_label = {}
    for r in csv.DictReader(open(SITE_DIR.parent / "data/2026/polls_vic2026.csv")):
        end_by_label[f"{r['pollster']} {r['fieldwork_end']}"] = date.fromisoformat(r["fieldwork_end"])
    idx = json.loads((SITE_DIR / "data/snapshots/index.json").read_text())
    today = date.today()
    for s in idx["snapshots"]:
        d = date.fromisoformat(s["date"])
        for label in s["polls_used"]:
            assert end_by_label[label] + timedelta(days=2) <= d, f"{s['date']}: {label} too new"
        assert s["retrospective"] == (d < today)


def test_robots_disallows_snapshots_sitemap_clean():
    robots = (SITE_DIR / "robots.txt").read_text()
    assert "Disallow: /data/snapshots/" in robots
    sitemap = (SITE_DIR / "sitemap.xml").read_text()
    assert "snapshots" not in sitemap


def test_district_history_cards():
    import json
    idx = json.loads((SITE_DIR / "data/snapshots/index.json").read_text())
    n = len(idx["snapshots"])
    count = 0
    for f in SITE_DIR.glob("districts/*/index.html"):
        html = f.read_text()
        assert "How the forecast has moved" in html
        assert html.count('href="/#model2/') >= n + 1  # one per snapshot + Latest
        count += 1
    assert count == 88


def test_map_timeline_shape():
    import json
    tl = json.loads((SITE_DIR / "data/snapshots/map_timeline.json").read_text())
    dates = [p["date"] for p in tl["points"]]
    assert dates == sorted(dates) and tl["points"][-1].get("latest")
    n = len(dates)
    latest = json.loads((SITE_DIR / "data/model2_vic2026.json").read_text())
    for name, d in tl["districts"].items():
        assert len(d["p"]) == n and all(len(row) == len(d["cands"]) for row in d["p"])
        # latest point equals model2 p_win rounded to 3dp
        lc = {c["id"]: round(c["p_win"], 3) for c in latest["districts"][name]["candidates"]}
        for (cid, _), pv in zip(d["cands"], d["p"][-1]):
            assert pv == lc.get(cid, 0.0)
