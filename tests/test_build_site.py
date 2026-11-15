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
    # stubs: meta refresh targets must exist
    for name in STUB_NAMES:
        text = (SITE_DIR / name).read_text()
        target = re.search(r'url=([^"]+)"', text).group(1)
        assert resolve_path(target).is_file(), f"{name} stub -> {target} missing"


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


STUB_NAMES = {"projections.html", "methodology.html", "methodology-model1.html",
              "methodology-model2.html", "results-2022.html"}


def site_pages():
    """Real site pages: every *.html under site/, excluding vendored files and
    the top-level redirect stubs."""
    return [f for f in sorted(SITE_DIR.rglob("*.html"))
            if "vendor" not in f.parts
            and not (f.parent == SITE_DIR and f.name in STUB_NAMES and f.name != "404.html")]


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
