#!/usr/bin/env python3
"""
Notional previous-election results on new boundaries for NSW 2019->2023, WA 2021->2025 and
SA 2022->2026 — the same reassignment method as scripts/build_notional_2018.py (which handled
Vic 2018->2022).

Booth first preferences and vote types come from each commission's results feed (WAEC results API,
ECSA results API, NSWEC VTR pages; cached under data/<PREV>/raw/). Polling places carry names but no
coordinates, so each venue is located by:
  a) matching its normalised name to an AEC federal polling place in the same state (nearest federal
     election first), accepting only matches inside its own old district or within AEC_MATCH_MAX_KM;
  b) geocoding "<venue>, <state>, Australia" with OpenStreetMap Nominatim (1 request/second, every
     response cached under the raw dir), accepting only results in the right state within
     GEOCODE_MAX_KM of the old district;
  c) still unmatched -> unlocated: its votes are spread over the new districts overlapping its old
     district in proportion to located votes, exactly like build_notional_2018's declaration votes.

Outputs per state pair:
  data/<PREV>/notional_<SCORED>_boundaries.json   new district -> party group -> notional votes
  data/<PREV>/notional_<SCORED>_boundaries.csv   the same, long format
  data/<PREV>/notional_<SCORED>_booths.csv       one row per venue with its location method

Validation (printed): share of votes located by method; per-party state totals conserved; and for
districts whose boundaries did not change, notional primaries must equal the actual result — the key
correctness check.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

from vic_election.config import BOUNDARIES_DIR, DATA_DIR
from vic_election.geo import District, assign_point, fetch_state_districts
from vic_election.http_cache import CachedSession
from vic_election.state_dop import _group
from vic_election.vec_booths import DistrictBooths, notional, remap

UA = {"User-Agent": "SeatProjections/1.0 (hello@seatprojections.au)"}
NOMINATIM = "https://nominatim.openstreetmap.org/search"
AEC_MATCH_MAX_KM = 5.0  # an AEC name match must be inside the old district or this close to it
GEOCODE_MAX_KM = 5.0

SPECS = {
    "NSW2019": {"state": "NSW", "prev_date": "2019-03-23", "scored": "NSW2023", "scored_date": "2023-03-25"},
    "WA2021": {"state": "WA", "prev_date": "2021-03-13", "scored": "WA2025", "scored_date": "2025-03-08"},
    "SA2022": {"state": "SA", "prev_date": "2022-03-19", "scored": "SA2026", "scored_date": "2026-03-21"},
}

# ------------------------------------------------------------- state booth FPVs (official feeds)


def fetch_sa2022(http: CachedSession, raw: Path) -> dict[str, DistrictBooths]:
    """ECSA 2022 results API: booth-level first preferences (HAChange) + candidate/venue lists (HAStatic).

    'Polling Booth' venues are located; mobile/visiting entries and every candidate's
    declarationVotes are spread. Booth formalVotes reconcile exactly with ordinaryVotes."""
    api = "https://apim-ecsa-production.azure-api.net/results-display/"
    static = json.loads(http.bytes(raw / "HAStatic.json", api + "HAStatic/2022-03-19"))
    change = json.loads(http.bytes(raw / "HAChange.json", api + "HAChange/2022-03-19/0"))
    out = {}
    for sd, cd in zip(static["districts"], change["districts"]):
        party = {c["candidateId"]: _group(c["partyId"] or "") for c in sd["candidates"]}
        cands = [(c["candidateName"], c["partyId"] or "") for c in sd["candidates"]]
        types = {p["pollingPlaceName"]: p["pollingPlaceType"] for p in sd["pollingPlaces"]}
        b = DistrictBooths(sd["districtName"], cands)
        by_id = {c["candidateId"]: c["candidateName"] for c in sd["candidates"]}
        for p in cd["pollingPlaces"]:
            votes = {by_id[cand["candidateId"]]: float(cand["formalVotes"] or 0) for cand in p["pollingCandidates"]}
            if types.get(p["pollingPlaceName"]) == "Polling Booth":
                b.centres[p["pollingPlaceName"]] = votes
            else:  # Host / Visiting / Mobile Poll Team -> spread
                b.declaration[p["pollingPlaceName"]] = votes
        decl = {by_id[c["candidateId"]]: float(c["declarationVotes"] or 0) for c in cd["candidates"]}
        b.declaration["Declaration votes"] = decl
        b.source = "ECSA results API (HAStatic/HAChange)"
        out[b.district] = b
    return out


def fetch_wa2021(http: CachedSession, raw: Path) -> dict[str, DistrictBooths]:
    """WAEC 2021 results API: resultsPollingPlace gives venue-level FPVs; 'Polling Places' venues are
    located (except the mobile 'Special Institutions' row), 'Count Centre' rows are spread."""
    api = "https://eis.waec.wa.gov.au/api/sgElections/"
    listing = json.loads(http.bytes(raw / "list.json", api + "sg2021/list"))
    districts = [e for e in listing["electorates"] if e.get("ElelctorateType", e.get("ElectorateType")) == "District"]

    def one(e: dict) -> DistrictBooths:
        res = json.loads(http.bytes(raw / f"{e['ElectorateCode']}.json", api + f"sg2021/{e['ElectorateCode']}/results"))
        rows = res["resultsPollingPlace"]
        cols = [c for c in rows[0] if c not in ("BREAKDOWN_NAME", "BREAKDOWN_GROUP", "Informal", "Total Votes")]
        # key votes by the full 'NAME - PARTY' column: some districts field same-surname candidates
        cands = [(c, c.rsplit(" - ", 1)[1].strip()) for c in cols]
        b = DistrictBooths(e["ElectorateName"], cands)
        for r in rows:
            name, grp = r["BREAKDOWN_NAME"], r["BREAKDOWN_GROUP"]
            votes = {c: float(r[c] or 0) for c in cols}
            if grp == "Polling Places" and not name.lower().startswith(("special institutions", "declared")):
                b.centres[name] = votes
            else:
                b.declaration[f"{grp}: {name}"] = votes
        b.source = "WAEC results API (resultsPollingPlace)"
        return b

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        return {b.district: b for b in pool.map(one, districts)}


def fetch_nsw2019(http: CachedSession, raw: Path) -> dict[str, DistrictBooths]:
    """NSWEC VTR 2019: per-district 'fp_summary' table. 'Voting Centres' and named 'Early Voting
    Centres' are located; 'Declared Facility' rows and the 'Declaration Votes' block are spread."""
    base = "https://pastvtr.elections.nsw.gov.au/"
    listing = http.text(raw / "results.html", base + "SG1901/LA/results")
    slugs = sorted(set(re.findall(r'href="/SG1901/LA/([a-z-]+)/cc/fp_summary"', listing)))

    def one(slug: str) -> DistrictBooths:
        html = http.text(raw / f"{slug}.html", base + f"SG1901/LA/{slug}/cc/fp_summary")
        soup = BeautifulSoup(html, "html.parser")
        district = re.search(r"State Electoral District of ([^<]+)<", html).group(1).strip()
        tab = next(t for t in soup.find_all("table") if "Venue and Vote Types" in t.get_text())
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in tab.find_all("tr")]
        heads = rows[0][1:-3]
        cands = [(h, h.rsplit("(", 1)[-1].rstrip(")")) for h in heads]  # 'NAME (PARTY)' stays unique
        b = DistrictBooths(district, cands)
        section = None
        for r in rows[1:]:
            if not r or not r[0]:
                continue
            if len(r) < len(heads) + 1 or r[0].endswith("Votes") and r[0].startswith("Total") or r[0].startswith("%"):
                if len(r) <= 2 or (r[1] == "" and len(r) <= 3):
                    section = r[0]
                    continue
            if r[0] in ("Voting Centres", "Early Voting Centres", "Declaration Votes"):
                section = r[0]
                continue
            if r[0].startswith("Total") or r[0].startswith("%"):
                continue
            votes = {h: float(v.replace(",", "") or 0) for h, v in zip(heads, r[1:len(heads) + 1])}
            if section in ("Voting Centres", "Early Voting Centres") and "declared facility" not in r[0].lower():
                b.centres[r[0]] = votes
            else:
                b.declaration[f"{section}: {r[0]}"] = votes
        b.source = "NSWEC VTR (fp_summary)"
        return b

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as pool:
        return {b.district: b for b in pool.map(one, slugs)}


# ------------------------------------------------------------- AEC polling-place catalogue

ABBREV = {"cntr": "centre", "ctr": "centre", "ctre": "centre", "ps": "public", "pub": "public",
          "prim": "primary", "sch": "school", "shs": "high", "hs": "high", "coll": "college",
          "comm": "community", "mem": "memorial", "snr": "senior", "sr": "senior", "jnr": "junior",
          "nth": "north", "sth": "south", "n": "north", "s": "south", "e": "east", "w": "west",
          "uc": "uniting", "ucc": "uniting", "ang": "anglican", "cath": "catholic", "bapt": "baptist",
          "presb": "presbyterian", "luth": "lutheran", "hosp": "hospital", "rec": "recreation",
          "prsch": "preschool", "kinder": "kindergarten", "hall": "hall", "dist": "district",
          "inst": "institute", "sport": "sports", "golf": "golf", "bowl": "bowling", "schls": "schools"}


def name_tokens(name: str) -> frozenset:
    toks = re.sub(r"[^a-z0-9 ]", " ", name.lower()).split()
    return frozenset(ABBREV.get(t, t) for t in toks)


def load_aec_places(state: str) -> dict[int, list[dict]]:
    """Federal polling places in `state` per available year, with coordinates."""
    out = {}
    for year, event in ((2019, 24310), (2022, 27966), (2025, 31496)):
        path = DATA_DIR / "federal" / str(year) / "general" / f"GeneralPollingPlacesDownload-{event}.csv"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            next(f)  # banner line
            places = []
            for r in csv.DictReader(f):
                if r["PremisesStateAb"] != state:
                    continue
                try:
                    lat, lon = float(r["Latitude"]), float(r["Longitude"])
                except ValueError:
                    continue
                places.append({"name": r["PollingPlaceNm"], "premises": r["PremisesNm"],
                               "address": " ".join(x for x in (r["PremisesAddress1"], r["PremisesAddress2"], r["PremisesAddress3"]) if x),
                               "suburb": r["PremisesSuburb"], "postcode": r["PremisesPostCode"],
                               "lat": lat, "lon": lon, "tokens": name_tokens(r["PollingPlaceNm"] + " " + r["PremisesNm"]),
                               "name_tokens": name_tokens(r["PollingPlaceNm"])})
        out[year] = places
    return out


GENERIC = frozenset("""school public primary high centre center community hall senior junior memorial
church catholic uniting anglican lutheran baptist presbyterian methodist college campus club sports sport
recreation resource citizens sea rescue surf life saving district area of the and st saint voting polling
pre pp early booth place state free office rooms chambers shire council town city gardens park view""".split())


def distinctive(tokens: frozenset) -> frozenset:
    return tokens - GENERIC


def aec_name_match(venue: str, old: District, places_by_year: dict[int, list[dict]], years: list[int]) -> dict | None:
    """Best AEC polling place matching the venue name, inside the old district or within
    AEC_MATCH_MAX_KM of it. Score = token Jaccard + a bonus when the venue's distinctive tokens are
    contained in the place's ('Prospect' -> 'Prospect Primary School'). Ambiguous ties -> next year."""
    vt = name_tokens(venue)
    dv = distinctive(vt)
    for year in years:
        scored = []
        for p in places_by_year.get(year, []):
            pt = p["name_tokens"]
            dp = distinctive(pt)
            if dv and not (dv & dp):
                continue
            j = len(vt & pt) / len(vt | pt) if vt | pt else 0
            contains = bool(dv) and dv <= dp
            score = j + 0.25 * contains
            if score < 0.55:
                continue
            inside = old.contains(p["lon"], p["lat"])
            dist = 0.0 if inside else old.distance(p["lon"], p["lat"])
            if inside or dist <= AEC_MATCH_MAX_KM:
                scored.append((score, -dist, p))
        if not scored:
            continue
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        top = scored[0]
        if len(scored) > 1 and abs(scored[1][0] - top[0]) < 1e-9:
            continue  # ambiguous: same-score candidates
        return top[2]
    return None


STATE_NAMES = {"NSW": "New South Wales", "WA": "Western Australia", "SA": "South Australia"}


def _nominatim(q: str, cache_dir: Path) -> list:
    key = hashlib.sha1(q.encode()).hexdigest()[:16]
    path = cache_dir / f"nominatim_{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    url = NOMINATIM + "?" + urllib.parse.urlencode({"q": q, "format": "jsonv2", "addressdetails": 1, "limit": 5, "countrycodes": "au"})
    try:
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read())
    except Exception:
        data = []
    path.write_text(json.dumps(data))
    time.sleep(1.1)
    return data


def nominatim_geocode(venue: str, old: District, state: str, cache_dir: Path) -> dict | None:
    """Try several phrasings ('<venue>, <state>'; '<venue>, <old district>'; without type words) and
    accept hits in the right state inside the old district or within GEOCODE_MAX_KM of it."""
    st_name = STATE_NAMES.get(state, state)
    stripped = " ".join(t for t in re.sub(r"[^A-Za-z0-9 ]", " ", venue).split()
                        if t.lower() not in GENERIC and t.lower() not in {"ps", "shs", "hs"})
    queries = [f"{venue}, {st_name}, Australia",
               f"{venue}, {old.name}, {st_name}, Australia",
               f"{stripped}, {old.name}, {st_name}, Australia",
               f"{stripped}, {st_name}, Australia"]
    for q in dict.fromkeys(q for q in queries if q.strip(", ")):
        for hit in _nominatim(q, cache_dir):
            st = (hit.get("address") or {}).get("state", "")
            if st_name.lower() not in st.lower() and state.lower() not in st.lower():
                continue
            lat, lon = float(hit["lat"]), float(hit["lon"])
            if old.contains(lon, lat) or old.distance(lon, lat) <= GEOCODE_MAX_KM:
                return {"lat": lat, "lon": lon}
    return None


# ------------------------------------------------------------- driver


def build(prev_run: str, refresh: bool = False, geocode: bool = True) -> dict:
    spec = SPECS[prev_run]
    state = spec["state"]
    year_dir = DATA_DIR / prev_run
    raw = year_dir / "raw" / "notional"
    raw.mkdir(parents=True, exist_ok=True)
    http = CachedSession(refresh)
    results = {"SA2022": fetch_sa2022, "WA2021": fetch_wa2021, "NSW2019": fetch_nsw2019}[prev_run](http, raw)

    bounds = BOUNDARIES_DIR / "states"
    old_districts = fetch_state_districts(bounds, state, spec["prev_date"])
    new_districts = fetch_state_districts(bounds, state, spec["scored_date"])
    # canonicalise result keys to the boundary names (e.g. ECSA 'MacKillop' vs Geoscape 'Mackillop')
    canon = {re.sub(r"[^a-z]", "", d.name.lower()): d.name for d in old_districts}
    results = {canon.get(re.sub(r"[^a-z]", "", k.lower()), k): b for k, b in results.items()}
    missing_old = [k for k in results if k not in canon.values()]
    if missing_old:
        raise SystemExit(f"{prev_run}: no old district boundary for {missing_old}")
    old_by_name = {d.name.lower(): d for d in old_districts}

    places_by_year = load_aec_places(state)
    years = sorted(places_by_year, key=lambda y: abs(y - int(prev_run[-4:])))
    locations, methods = {}, {}
    nom_dir = raw / "nominatim"
    nom_dir.mkdir(exist_ok=True)
    for old_name, b in results.items():
        old = old_by_name.get(old_name.lower())
        if old is None:  # fuzzy name match to boundary names
            old = next(d for d in old_districts if d.name.lower().replace(" ", "") == old_name.lower().replace(" ", ""))
        for centre in b.centres:
            centre_votes = sum(b.centres[centre].values())
            hit = aec_name_match(centre, old, places_by_year, years)
            if hit is not None:
                method = "aec-name"
            elif not geocode or centre_votes < 50:
                # <50-formal-vote booths: not worth a geocode lookup; spread like declaration votes
                method = "unlocated-small" if geocode else "unlocated"
            else:
                hit = nominatim_geocode(centre, old, state, nom_dir)
                method = "nominatim" if hit is not None else "unlocated"
            if hit:
                locations[(old_name, centre)] = (hit["lon"], hit["lat"], method)
            methods[(old_name, centre)] = method

    mapping = remap(results, locations, old_districts, new_districts)
    # districts with no located venue still need spread weights: sample the old polygon and share by
    # which new districts its area falls in (same role as the located-vote weights elsewhere)
    name2new = {d.name.lower(): d for d in new_districts}
    for old in old_districts:
        key = next((k for k in results if k.lower() == old.name.lower()), None)
        if key is None or mapping["weights"].get(key):
            continue
        x0, y0, x1, y1 = old.bbox
        step = min(x1 - x0, y1 - y0) / 60 or 0.01
        hits = Counter()
        x = x0
        while x <= x1:
            y = y0
            while y <= y1:
                if old.contains(x, y):
                    new = assign_point(new_districts, x, y)[0]
                    if new:
                        hits[new] += 1
                y += step
            x += step
        tot = sum(hits.values()) or 1
        mapping["weights"][key] = {n: v / tot for n, v in hits.items()}
    groups = {old: {name: _group(party) for name, party in b.candidates} for old, b in results.items()}
    notion = notional(results, groups, mapping)

    # ---- actual previous-election primaries (for the <1%-changed hybrid + validation) ----
    actual_path = year_dir / "distributions" / f"dop_{prev_run}.json"
    actual = json.loads(actual_path.read_text()) if actual_path.exists() else {}
    act_shares, act_totals, act_votes = {}, Counter(), {}
    for d, t in actual.items():
        party = {c["candidate_id"]: c["party"] for c in t["candidates"]}
        g = Counter()
        for c, v in t["first_preferences"].items():
            g[party[c]] += v
        act_votes[d.lower()] = g
        tot = sum(g.values())
        act_shares[d.lower()] = {p: 100 * v / tot for p, v in g.items()}
        act_totals.update(g)

    # Vote-based "unchanged" test: for a same-named old/new pair, change = max(share of the old
    # district's located booth votes landing outside the new district polygon, share of the new
    # district's located booth votes arriving from outside the old district polygon). <1% -> unchanged.
    new_by_lower = {d.name.lower(): d for d in new_districts}
    loc_votes = Counter()          # (old, new) -> located votes strictly inside the new polygon
    old_loc_tot = Counter()
    for (o, c), (lon, lat, _m) in locations.items():
        v = sum(results[o].centres[c].values())
        old_loc_tot[o] += v
        for nd in new_districts:
            if nd.contains(lon, lat):
                loc_votes[(o, nd.name)] += v
    unchanged, changed, change_pct = [], [], {}
    for o in results:
        nw = new_by_lower.get(o.lower())
        if nw is None or old_loc_tot[o] == 0:
            changed.append(o.lower())
            continue
        inside = loc_votes[(o, nw.name)]
        out_share = 1 - inside / old_loc_tot[o]
        in_tot = sum(loc_votes[(o2, nw.name)] for o2 in results)
        in_share = 1 - inside / in_tot if in_tot else 1
        change_pct[o.lower()] = max(out_share, in_share)
        (unchanged if change_pct[o.lower()] < 0.01 else changed).append(o.lower())
    hybrid = dict(notion)
    for d in unchanged:
        nk = next((k for k in notion if k.lower() == d), None)
        if nk is not None and d in act_votes:
            hybrid[nk] = act_votes[d]

    # outputs
    located_by = Counter()
    votes_by = Counter()
    tot_votes = 0.0
    unlocated_votes = {(o, c): v for o, c, v, _ in mapping["unlocated"]}
    for (o, c), m in methods.items():
        v = sum(results[o].centres[c].values())
        tot_votes += v
        located_by[m] += 1
        if m not in ("unlocated", "unlocated-small"):
            votes_by[m] += v
    located_votes = tot_votes - sum(unlocated_votes.values())
    small_votes = sum(v for (o, c), m in methods.items() if m == "unlocated-small"
                      for v in [sum(results[o].centres[c].values())])

    meta = {"method": "previous-election booth first preferences located by AEC name match then "
                      "Nominatim; unlocated booths and declaration/early/postal votes spread over the "
                      "new districts overlapping each old district by located-vote share; districts whose "
                      "boundaries changed <1% keep their actual previous-election primaries",
            "prev_run": prev_run, "scored_run": spec["scored"],
            "venue_counts": dict(located_by), "located_venue_votes": round(located_votes),
            "total_venue_votes": round(tot_votes), "located_share": round(located_votes / tot_votes, 4),
            "unchanged_districts_actual_primaries": len(unchanged),
            "remapped_districts": len(changed),
            "small_unlocated_votes": round(small_votes),
            "vote_share_change_pct": {d: round(100 * v, 2) for d, v in sorted(change_pct.items())}}
    out = {"meta": meta, "districts": {d: {p: round(v, 1) for p, v in c.most_common()} for d, c in sorted(hybrid.items())}}
    (year_dir / f"notional_{spec['scored']}_boundaries.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    with (year_dir / f"notional_{spec['scored']}_boundaries.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "party_group", "notional_votes"])
        for d, c in sorted(hybrid.items()):
            for p, v in c.most_common():
                w.writerow([d, p, round(v, 1)])
    with (year_dir / f"notional_{spec['scored']}_booths.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["old_district", "venue", "votes", "method", "lat", "lon"])
        for (o, c), m in sorted(methods.items()):
            loc = locations.get((o, c))
            w.writerow([o, c, round(sum(results[o].centres[c].values())), m,
                        "" if not loc else loc[1], "" if not loc else loc[0]])

    # ---- validation ----
    report = {"run": prev_run, "located_share": meta["located_share"], "venue_counts": meta["venue_counts"],
              "unchanged_districts": len(unchanged), "unchanged_list": sorted(unchanged),
              "remapped_districts": len(changed),
              "small_unlocated_votes": round(small_votes)}
    if actual:
        not_totals = Counter()
        for d, c in hybrid.items():
            not_totals.update(c)
        diffs = {p: round(not_totals.get(p, 0) - act_totals.get(p, 0), 1) for p in set(act_totals) | set(not_totals)}
        report["party_total_diffs_votes"] = diffs
        # notional-vs-actual residual for the unchanged group (noise ignored by the >=99% rule)
        res = []
        for d in unchanged:
            nk = next(k for k in notion if k.lower() == d)
            ad = act_shares.get(d, {})
            ntot = sum(notion[nk].values())
            for p, v in notion[nk].items():
                res.append(abs(100 * v / ntot - ad.get(p, 0)))
        report["unchanged_max_diff_pp"] = round(max(res), 4) if res else None
    print(json.dumps(report, indent=1))
    return report


def main() -> None:
    import sys
    runs = sys.argv[1:] or list(SPECS)
    for r in runs:
        build(r)


if __name__ == "__main__":
    main()
