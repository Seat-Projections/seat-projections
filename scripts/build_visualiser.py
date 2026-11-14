#!/usr/bin/env python3
"""
Builds the static data for the booth visualiser (visualiser/data/):

  districts.geojson          88 Legislative Assembly districts (simplified for display) + per-district stats
  victoria_outline.json      state outline rings, used to mask the map outside Victoria
  booths.json                every 2025 federal polling place in Victoria: location, assigned district, vote shares
  divisions/{divisionId}.json  full per-booth detail (first preferences, 2CP, 2PP, preference flows,
                             distribution of preferences) plus the division's unlocated declaration votes
  district_flows.json        collated party-level preference-flow matrix for each district (vic_election.booth_flows)
  model1_vic2026.json,       each model's 2026 forecast per district (win/final-two probabilities, stage-by-stage
  model2_vic2026.json        central count, likely final pairs with 2CP ranges); `--forecasts-only` rebuilds just these

Also writes data/federal/2025/booth_districts_VIC.csv (polling place -> state district).
District statistics and flows use the same booths: those inside the district and inside (or within 1 km of)
their own federal division. Run scripts/fetch_aec.py first.
Serve with:  .venv/bin/python -m http.server 8000 -d visualiser
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict

from vic_election.aec import read_aec_csv as rows
from vic_election.booth_flows import assign_booths, build_district_flows, load_polling_places
from vic_election.config import AEC_EVENTS, FEDERAL_BOUNDARIES_DIR, ROOT, VIC_DISTRICTS_DIR, federal_data_dir, vec_distributions_path
from vic_election.geo import fetch_national_divisions, fetch_vic_districts, simplify_ring, state_outline, to_geojson

YEAR, STATE = 2025, "VIC"
EVENT = AEC_EVENTS[YEAR]
FED = federal_data_dir(YEAR)
OUT = ROOT / "visualiser" / "data"
COALITION = {"LP", "NP", "LNP", "CLP"}
GROUPS = ("ALP", "COAL", "GRN", "ON", "IND", "OTH")
PP_TYPES = {"1": "Polling place", "2": "Special hospital team", "3": "Remote mobile team", "4": "Other mobile team", "5": "Pre-poll voting centre"}


def group(ab: str) -> str:
    return "COAL" if ab in COALITION else ab if ab in ("ALP", "GRN", "ON", "IND") else "OTH"


def name(surname: str, given: str) -> str:
    return f"{surname}, {given}" if given else surname


def pct(v: int, total: int) -> float:
    return round(100 * v / total, 2) if total else 0.0


def load_dops() -> dict[tuple[str, str], dict]:
    """(division, booth key) -> {cands, counts}; booth key is the PPId, or the pseudo-booth name when PPId is 0."""
    raw: dict[tuple[str, str], dict] = defaultdict(lambda: {"cands": {}, "pref": defaultdict(dict), "xfer": defaultdict(dict)})
    for f in sorted((FED / "house" / f"HouseDopByPPDownload-{EVENT}-{STATE}").glob("*.csv")):
        for r in rows(f):
            key = (r["DivisionNm"], r["PPId"] if r["PPId"] != "0" else r["PPNm"])
            d = raw[key]
            cid = r["CandidateId"]
            d["cands"][cid] = (int(r["BallotPosition"]), name(r["Surname"], r["GivenNm"]), r["PartyAb"], r["PartyNm"])
            if r["CalculationType"] == "Preference Count":
                d["pref"][int(r["CountNum"])][cid] = int(r["CalculationValue"])
            elif r["CalculationType"] == "Transfer Count":
                d["xfer"][int(r["CountNum"])][cid] = int(r["CalculationValue"])
    out = {}
    for key, d in raw.items():
        order = sorted(d["cands"], key=lambda c: d["cands"][c][0])
        counts = []
        for n in sorted(d["pref"]):
            excluded = next((c for c in order if d["xfer"][n].get(c, 0) < 0), None)
            counts.append({
                "n": n,
                "excluded": d["cands"][excluded][1] if excluded else None,
                "pref": [d["pref"][n].get(c, 0) for c in order],
                "xfer": [d["xfer"][n].get(c, 0) for c in order],
            })
        out[key] = {"cands": [{"name": d["cands"][c][1], "ab": d["cands"][c][2]} for c in order], "counts": counts}
    return out


def load_flows() -> dict[tuple[str, str], dict]:
    raw: dict[tuple[str, str], dict] = defaultdict(lambda: {"to": {}, "rows": {}})
    for f in sorted((FED / "house" / f"HouseTcpFlowByPPDownload-{EVENT}-{STATE}").glob("*.csv")):
        for r in rows(f):
            key = (r["DivisionNm"], r["PPId"] if r["PPId"] != "0" else r["PPNm"])
            d = raw[key]
            to = name(r["ToCandidateSurname"], r["ToCandidateGivenNm"])
            d["to"].setdefault(to, r["ToCandidatePartyAb"])
            src = "First preferences" if r["FromCandidateId"] == "0" else name(r["FromCandidateSurname"], r["FromCandidateGivenNm"])
            row = d["rows"].setdefault(src, {"from": src, "ab": r["FromCandidatePartyAb"], "votes": {}, "pct": {}})
            row["votes"][to] = int(r["TransferCount"])
            row["pct"][to] = float(r["TransferPercent"])
    out = {}
    for key, d in raw.items():
        finalists = list(d["to"])
        out[key] = {
            "finalists": [{"name": n, "ab": d["to"][n]} for n in finalists],
            "rows": [
                {"from": r["from"], "ab": r["ab"], "votes": [r["votes"].get(n, 0) for n in finalists], "pct": [r["pct"].get(n, 0.0) for n in finalists]}
                for r in d["rows"].values()
            ],
        }
    return out


def main() -> None:
    vec = json.loads(vec_distributions_path(2022).with_name("full_2cp_2022.json").read_text())
    districts = fetch_vic_districts(VIC_DISTRICTS_DIR, {d.upper(): d for d in vec})
    divisions = fetch_national_divisions(FEDERAL_BOUNDARIES_DIR, YEAR, states=(STATE,))

    places = load_polling_places(FED / "general", EVENT, STATE)
    assignment = assign_booths(places, districts, divisions)
    fp, informal = defaultdict(list), Counter()
    for r in rows(FED / "house" / f"HouseStateFirstPrefsByPollingPlaceDownload-{EVENT}-{STATE}.csv"):
        if r["Surname"].lower() == "informal":
            informal[r["PollingPlaceID"]] += int(r["OrdinaryVotes"])
        else:
            fp[r["PollingPlaceID"]].append(r)
    tcp = defaultdict(list)
    for r in rows(FED / "house" / f"HouseTcpByCandidateByPollingPlaceDownload-{EVENT}.csv"):
        if r["StateAb"] == STATE:
            tcp[r["PollingPlaceID"]].append(r)
    tpp = {r["PollingPlaceID"]: r for r in rows(FED / "house" / f"HouseTppByPollingPlaceDownload-{EVENT}.csv") if r["StateAb"] == STATE}
    dops, flows = load_dops(), load_flows()

    booths, details = [], defaultdict(lambda: {"booths": {}, "declaration": {}})
    district_votes: dict[str, Counter] = defaultdict(Counter)
    district_booths, methods = Counter(), Counter()
    for pid, p in places.items():
        cands = fp.get(pid, [])
        total = sum(int(r["OrdinaryVotes"]) for r in cands)
        has_xy = bool(p["Latitude"] and p["Longitude"])
        loc = assignment[pid]
        methods["counted" if loc.counted else loc.method if loc.method != "inside" else "outside own division"] += 1
        groups = Counter()
        for r in cands:
            groups[group(r["PartyAb"])] += int(r["OrdinaryVotes"])
        lead = max(cands, key=lambda r: int(r["OrdinaryVotes"]))["PartyAb"] if total else ""
        if loc.counted:
            district_votes[loc.district].update(groups)
            district_booths[loc.district] += 1
        booths.append({
            "id": int(pid), "name": p["PollingPlaceNm"], "div": p["DivisionNm"], "divId": int(p["DivisionID"]),
            "district": loc.district, "method": loc.method, "divKm": loc.division_km, "counted": loc.counted,
            "type": PP_TYPES.get(p["PollingPlaceTypeID"], p["PollingPlaceTypeID"]),
            "lat": float(p["Latitude"]) if has_xy else None, "lon": float(p["Longitude"]) if has_xy else None,
            "votes": total, "lead": lead, "share": {g: pct(groups[g], total) for g in GROUPS},
        })
        address = ", ".join(x for x in (p["PremisesNm"], p["PremisesAddress1"], p["PremisesAddress2"], p["PremisesAddress3"], f"{p['PremisesSuburb']} {p['PremisesPostCode']}") if x.strip())
        t = tpp.get(pid)
        details[p["DivisionID"]]["division"] = p["DivisionNm"]
        details[p["DivisionID"]]["booths"][pid] = {
            "address": address,
            "informal": informal[pid],
            "fp": [
                {"name": name(r["Surname"], r["GivenNm"]), "ab": r["PartyAb"], "party": r["PartyNm"], "votes": int(r["OrdinaryVotes"]),
                 "pct": pct(int(r["OrdinaryVotes"]), total), "swing": r["Swing"], "elected": r["Elected"] == "Y"}
                for r in sorted(cands, key=lambda r: -int(r["OrdinaryVotes"]))
            ],
            "tcp": [
                {"name": name(r["Surname"], r["GivenNm"]), "ab": r["PartyAb"], "votes": int(r["OrdinaryVotes"]), "swing": r["Swing"]}
                for r in tcp.get(pid, [])
            ],
            "tpp": {"alp": int(t["Australian Labor Party Votes"]), "alpPct": float(t["Australian Labor Party Percentage"]),
                    "coal": int(t["Liberal/National Coalition Votes"]), "coalPct": float(t["Liberal/National Coalition Percentage"]),
                    "swing": t["Swing"]} if t else None,
            "flows": flows.get((p["DivisionNm"], pid)),
            "dop": dops.get((p["DivisionNm"], pid)),
        }

    # Division-wide declaration votes (absent, postal, declaration pre-poll, provisional): no location
    for div_id, d in details.items():
        for kind in ("ABSENT", "POSTAL", "PRE_POLL", "PROVISIONAL"):
            dop = dops.get((d["division"], kind))
            if dop:
                d["declaration"][kind] = {"dop": dop, "flows": flows.get((d["division"], kind))}

    gj = to_geojson(districts, tolerance=0.0003, decimals=5)  # ~30 m: invisible at street zoom, 1/7 of the vertices
    for f in gj["features"]:
        dname = f["properties"]["district"]
        v = district_votes[dname]
        total = sum(v.values())
        t = vec[dname]
        party = {c["candidate_id"]: c["party"] for c in t["candidates"]}
        f["properties"].update({
            "booths": district_booths[dname], "votes": total, "share": {g: pct(v[g], total) for g in GROUPS},
            "vec2022": {"winner": t["declared_winner"], "party": party.get(t["declared_winner"], ""),
                        "final": [{"name": k, "party": party.get(k, ""), "votes": n} for k, n in sorted(t["final_totals"].items(), key=lambda kv: -kv[1])],
                        "formal": t["formal_votes"]},
        })

    (OUT / "divisions").mkdir(parents=True, exist_ok=True)
    (OUT / "districts.geojson").write_text(json.dumps(gj, separators=(",", ":")), encoding="utf-8")
    (OUT / "booths.json").write_text(json.dumps(booths, separators=(",", ":")), encoding="utf-8")
    # Victoria's outline (mainland + islands) as [lat, lon] rings, used to mask everything outside the state
    outline = [[[round(y, 5), round(x, 5)] for x, y in simplify_ring(r, 0.0005)] for r in state_outline(districts)]
    (OUT / "victoria_outline.json").write_text(json.dumps(outline, separators=(",", ":")), encoding="utf-8")
    for div_id, d in details.items():
        (OUT / "divisions" / f"{div_id}.json").write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")

    flows = build_district_flows(FED, EVENT, STATE, districts, divisions, assignment=assignment)
    (OUT / "district_flows.json").write_text(
        json.dumps({k: flows[k] for k in ("own_division_tolerance_km", "booth_votes", "counted_votes", "declaration_votes", "districts")},
                   separators=(",", ":")),
        encoding="utf-8",
    )

    with (FED / f"booth_districts_{STATE}.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["PollingPlaceID", "PollingPlaceNm", "DivisionNm", "PollingPlaceType", "Latitude", "Longitude", "District", "Method",
                    "KmOutsideOwnDivision", "CountedInDistrict", "OrdinaryFormalVotes"])
        for b in sorted(booths, key=lambda b: b["id"]):
            w.writerow([b["id"], b["name"], b["div"], b["type"], b["lat"], b["lon"], b["district"] or "", b["method"],
                        "" if b["divKm"] is None else b["divKm"], "Y" if b["counted"] else "N", b["votes"]])

    print(f"{len(booths)} polling places: {dict(methods)}")
    print(f"Districts with no booth: {[d.name for d in districts if not district_booths[d.name]]}")
    print(f"Wrote {OUT.relative_to(ROOT)}/ and {(FED / f'booth_districts_{STATE}.csv').relative_to(ROOT)}")
    build_forecasts()


# Forecast views: model -> (2026 run, one-line description shown in the visualiser)
FORECASTS = {
    "model1": ("VIC2026 (2025)", "Model 1 (\"nothing changes\"): 2025 federal polling-place votes inside each district, restricted to the parties "
                                 "standing in 2026, counted with federal preferences. No polling: One Nation stays at its federal level."),
    "model2": ("VIC2026 (2022)", "Model 2 (core-candidate heuristic): the declared 2026 candidates, 2022 primaries swung to the 2026 polling average, "
                                 "One Nation on its 2025 federal booth pattern, preferences fitted to the 2022 distributions."),
}


def build_forecasts() -> None:
    """visualiser/data/<model>_vic2026.json for each model whose 2026 run has a district_counts.json."""
    OUT.mkdir(parents=True, exist_ok=True)
    for model, (run_id, description) in FORECASTS.items():
        run_dir = ROOT / "predictions" / "modelling" / model / "output" / run_id
        if not (run_dir / "district_counts.json").exists():
            print(f"Skipped {model} view: no {run_dir.relative_to(ROOT)}/district_counts.json (run the model first)")
            continue
        meta = json.loads((run_dir / "run_metadata.json").read_text())
        def read_seats(name: str) -> list[dict] | None:
            if not (run_dir / name).exists():
                return None
            with (run_dir / name).open(encoding="utf-8") as f:
                return [{k: (v if k == "party" else float(v)) for k, v in r.items()} for r in csv.DictReader(f)]
        seats, blocs = read_seats("statewide_seats.csv"), read_seats("statewide_blocs.csv")
        out = {
            "meta": {k: meta.get(k) for k in ("model", "run_id", "timestamp", "git_commit", "runs", "seed")}
                    | {"description": description, "polls": meta["inputs"].get("polls"), "polls_used": meta["inputs"].get("polls_used"), "majority": 45},
            "seats": seats,
            "blocs": blocs,  # Liberals + Nationals summed run by run (statewide_blocs.csv)
            "districts": json.loads((run_dir / "district_counts.json").read_text()),
        }
        (OUT / f"{model}_vic2026.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
        print(f"Wrote {(OUT / f'{model}_vic2026.json').relative_to(ROOT)} ({len(out['districts'])} districts)")


if __name__ == "__main__":
    import sys
    build_forecasts() if "--forecasts-only" in sys.argv or "--model2-only" in sys.argv else main()
