"""
District distributions of preferences for other states' lower-house elections, from each electoral
commission's own publications, in the same shape as the parsed VEC tables:

    {district: {"candidates": [{"candidate_id", "name", "party"}], "first_preferences": {id: votes},
                "steps": [{"excluded_candidate", "transfers": {id: votes}, "exhausted": votes}],
                "final_totals": {id: votes}, "formal_votes": int}}

`party` is the party-group code the models use (ALP, LP, NP, LNP, GRN, ON, IND*, KAP, ...). Transfers list
only continuing candidates. Raw downloads are cached under data/<RUN>/raw/.

| Election | Source |
|---|---|
| QLD 2020, 2024 | ECQ results archive XML (official distribution of preferences count) |
| WA 2021, 2025 | WAEC results API (eis.waec.wa.gov.au), resultsFullDistribution; WA stops once a majority is reached |
| SA 2022 | ECSA "House of Assembly final distribution" CSV zip |
| SA 2026 | ECSA results API (apim-ecsa-production), finalDistribution |
| NSW 2023 | NSWEC Virtual Tally Room distribution of preferences pages (optional preferential: exhausted votes) |
"""
from __future__ import annotations

import csv
import io
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from bs4 import BeautifulSoup

from .http_cache import CachedSession

IND = "IND*"
# Commission party codes -> model party groups (codes not listed are kept as they are)
CODES = {"IND": IND, "": IND, "LIB": "LP", "NAT": "NP", "NATS": "NP", "ONP": "ON", "PHON": "ON", "GRN": "GRN", "ALP": "ALP",
         "LNP": "LNP", "KAP": "KAP", "ON": "ON",
         # ECQ writes some parties out in full
         "AUSTRALIAN LABOR PARTY": "ALP", "THE GREENS": "GRN", "PAULINE HANSON'S ONE NATION": "ON", "ONE NATION": "ON",
         "FAMILY FIRST": "FFP", "ANIMAL JUSTICE PARTY": "AJP", "LIBERTARIANS": "LDP", "CLIVE PALMER'S UAP": "UAP"}


def _group(code: str) -> str:
    return CODES.get(code.strip().upper(), code.strip().upper())


def _table(cands: list[tuple[str, str]], first: dict[str, float], steps: list[dict], final: dict[str, float]) -> dict:
    return {"candidates": [{"candidate_id": c, "name": c, "party": p} for c, p in cands], "first_preferences": first,
            "steps": steps, "final_totals": final, "formal_votes": int(round(sum(first.values())))}


# ------------------------------------------------------------------ Queensland (ECQ)

ECQ_ARCHIVES = {
    2020: "https://resultsdata.elections.qld.gov.au/XMLData/publicResults_State2020_aurukun2020_Final.zip",
    2024: "https://resultsdata.elections.qld.gov.au/XMLData/publicResults_SGE2024_ICCDiv4_Final.zip",
}


def fetch_qld(year: int, raw_dir: Path, refresh: bool = False) -> dict[str, dict]:
    content = CachedSession(refresh).bytes(raw_dir / ECQ_ARCHIVES[year].rsplit("/", 1)[-1], ECQ_ARCHIVES[year])
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        root = ET.fromstring(zf.read(zf.namelist()[0]))
    election = next(e for e in root.findall("election") if e.get("eventType") == "State General")
    out = {}
    for d in election.find("districts"):
        cands = [(c.get("ballotName"), _group(c.get("partyCode") or "")) for c in d.find("candidates")]
        dop = [r for r in d.findall("countRound") if r.get("preferences") == "YES"]
        summary = dop[-1].find("preferenceDistributionSummary") if dop else None
        if summary is None:  # no distribution: the official first-preference count only
            final_round = d.findall("countRound")[-1]
            first = {c.get("ballotName"): float(c.findtext("count")) for c in final_round.find("primaryVoteResults")}
            out[d.get("districtName")] = _table(cands, first, [], {})
            continue
        first = {c.get("ballotName"): float(c.findtext("count")) for c in summary.find("primaryVotes")}
        steps = [{"excluded_candidate": p.get("excludedBallotName"),
                  "transfers": {c.get("ballotName"): float(c.findtext("count")) for c in p.findall("candidatePreferences")},
                  "exhausted": float(p.findtext("exhausted") or 0)} for p in summary.findall("preferenceDistribution")]
        final = {c.get("ballotName"): float(c.findtext("count")) for c in dop[-1].find("twoCandidateVotes")}
        out[d.get("districtName")] = _table(cands, first, steps, final)
    return out


# ------------------------------------------------------------------ Western Australia (WAEC)

WAEC_API = "https://eis.waec.wa.gov.au/api/sgElections/"


def _wa_district(res: dict) -> dict:
    rows = res["resultsFullDistribution"] or []
    first = {r["BALLOT_PAPER_NAME"]: float(r["FORMAL_LAST_PUBLISHED_NUMBER_ENTERED"] or 0) for r in rows if r["DISTRIBUTION_LEVEL"] == "First Preference"}
    if not first:
        first = {f"{c['BALLOT_PAPER_NAME']} - {c['PARTY_AFFILIATION']}": float(c["Votes_Counted"]) for c in res["resultsCandidates"]}
    # Rows are labelled "SURNAME - PARTY"; the candidate list can spell the party differently, so parse the label
    cands = [(n, _group(n.rsplit(" - ", 1)[1] if " - " in n else "")) for n in first]
    steps, k = [], 1
    while True:
        level = [r for r in rows if r["DISTRIBUTION_LEVEL"] == f"Distribution {k}"]
        if not level:
            break
        excluded = [r["BALLOT_PAPER_NAME"] for r in level if (r["FORMAL_LAST_PUBLISHED_NUMBER_ENTERED"] or 0) < 0]
        if len(excluded) != 1:  # bulk exclusions cannot be attributed to one source party
            break
        steps.append({"excluded_candidate": excluded[0],
                      "transfers": {r["BALLOT_PAPER_NAME"]: float(r["FORMAL_LAST_PUBLISHED_NUMBER_ENTERED"]) for r in level
                                    if (r["FORMAL_LAST_PUBLISHED_NUMBER_ENTERED"] or 0) > 0 or (r["FORMAL_LAST_PUBLISHED_NUMBER_ENTERED"] == 0 and r["BALLOT_PAPER_NAME"] not in {s["excluded_candidate"] for s in steps})},
                      # repeated on every row except already-excluded candidates' (0)
                      "exhausted": float(max(r["EXHAUSTED_LAST_PUBLISHED_NUMBER_ENTERED"] or 0 for r in level))})
        k += 1
    out_steps = []
    gone = set()
    for s in steps:
        gone.add(s["excluded_candidate"])
        out_steps.append(s | {"transfers": {c: v for c, v in s["transfers"].items() if c not in gone}})
    final = {r["Ballot_Paper_Name"]: float(r["Votes_Counted"]) for r in res.get("results2CP") or []}
    return _table(cands, first, out_steps, final)


def fetch_wa(year: int, raw_dir: Path, refresh: bool = False) -> dict[str, dict]:
    http = CachedSession(refresh)
    name = f"sg{year}"
    listing = json.loads(http.bytes(raw_dir / "list.json", WAEC_API + f"{name}/list"))
    districts = [e for e in listing["electorates"] if e.get("ElelctorateType", e.get("ElectorateType")) == "District"]

    def one(e: dict) -> tuple[str, dict]:
        res = json.loads(http.bytes(raw_dir / f"{e['ElectorateCode']}.json", WAEC_API + f"{name}/{e['ElectorateCode']}/results"))
        return e["ElectorateName"], _wa_district(res)

    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(one, districts))


# ------------------------------------------------------------------ South Australia (ECSA)

ECSA_2022_DOP = "https://ecsa.sa.gov.au/component/edocman/244-2022se-ha-final-distribution/download?Itemid=0"
ECSA_API = "https://apim-ecsa-production.azure-api.net/results-display/"


def _sa2022_csv(text: str) -> tuple[str, dict]:
    rows = list(csv.reader(io.StringIO(text)))
    district = re.search(r"District of (.+)$", next(r[0] for r in rows if "District of" in r[0])).group(1).strip()
    names_i = next(i for i, r in enumerate(rows) if len(r) > 1 and r[1] == "Votes transferred")
    names, codes = rows[names_i - 1], rows[names_i]
    cols = [i for i in range(2, len(names)) if names[i] and "TOTAL" not in names[i].upper()]  # header may contain line breaks
    cands = [(names[i], _group(codes[i])) for i in cols]
    num = lambda x: float(x.replace(",", "")) if x.strip() not in ("", "Excluded") else None  # noqa: E731
    first, steps, final = {}, [], {}
    for r in rows[names_i + 1:]:
        label = r[0]
        if label.startswith("1st preference"):
            first = {names[i]: num(r[i]) for i in cols}
        elif "excluded candidate" in label:
            excluded = next(names[i] for i in cols if (num(r[i]) or 0) < 0)
            steps.append({"excluded_candidate": excluded, "exhausted": 0.0,
                          "transfers": {names[i]: num(r[i]) for i in cols if num(r[i]) is not None and num(r[i]) >= 0 and names[i] != excluded}})
        elif label.startswith("FINAL DISTRICT TOTALS"):
            final = {names[i]: num(r[i]) for i in cols if num(r[i]) is not None}
    gone = set()
    for s in steps:  # SA lists blank cells for already-excluded candidates; drop zero entries for them
        gone.add(s["excluded_candidate"])
        s["transfers"] = {c: v for c, v in s["transfers"].items() if c not in gone}
    return district, _table(cands, first, steps, final)


def fetch_sa(year: int, raw_dir: Path, refresh: bool = False) -> dict[str, dict]:
    http = CachedSession(refresh)
    if year == 2022:
        with zipfile.ZipFile(io.BytesIO(http.bytes(raw_dir / "2022se_ha_final_distribution.zip", ECSA_2022_DOP))) as zf:
            return dict(_sa2022_csv(zf.read(n).decode("utf-8-sig")) for n in zf.namelist() if n.lower().endswith(".csv"))
    date = {2026: "2026-03-21"}[year]
    static = json.loads(http.bytes(raw_dir / "HAStatic.json", ECSA_API + f"HAStatic/{date}"))
    change = json.loads(http.bytes(raw_dir / "HAChange.json", ECSA_API + f"HAChange/{date}/0"))
    key = lambda name: " ".join(sorted(re.sub(r"[,]", " ", name).lower().split()))  # noqa: E731  'CASEY, Dan' == 'Dan CASEY'
    out = {}
    for sd, cd in zip(static["districts"], change["districts"]):
        party = {key(c["candidateName"]): _group(c["partyId"] or "") for c in sd["candidates"]}
        rounds = cd["finalDistribution"]
        names = [c["candidateName"] for c in rounds[0]["candidateResults"]]
        cands = [(n, party[key(n)]) for n in names]
        first = {c["candidateName"]: float(c["voteChange"]) for c in rounds[0]["candidateResults"]}
        steps, gone = [], set()
        for r in rounds[1:]:
            gone.add(r["excludedCandidateName"])
            steps.append({"excluded_candidate": r["excludedCandidateName"], "exhausted": 0.0,
                          "transfers": {c["candidateName"]: float(c["voteChange"] or 0) for c in r["candidateResults"] if c["candidateName"] not in gone}})
        final = {c["candidateName"]: float(c["progressiveTotal"]) for c in rounds[-1]["candidateResults"] if not c["isExcluded"] and c["progressiveTotal"] is not None}
        out[sd["districtName"]] = _table(cands, first, steps, final)
    return out


# ------------------------------------------------------------------ New South Wales (NSWEC)

NSWEC_VTR = "https://pastvtr.elections.nsw.gov.au/"


def _nsw_dop(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    table = next(t for t in soup.find_all("table") if "Exhausted" in t.get_text())
    rows = [[c.get_text("|", strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
    order = [re.sub(r"\|Excluded Candidate$", "", c) for c in rows[1][2:] if c]  # "BEGG Michael (SAP)" per count
    num = lambda x: float(x.split("|")[-1].replace(",", "")) if re.search(r"\d", x) and "EXCLUDED" not in x else None  # noqa: E731
    end = next(i for i, r in enumerate(rows) if r and r[0] == "Total Votes in Count")
    cand_rows = rows[3:end]
    split = [(r[0].split("|") + [""])[:2] for r in cand_rows]  # "NAME|PARTY"; ungrouped independents have no party
    for r, (n, _) in zip(cand_rows, split):
        r[0] = n
    cands = [(n, _group(p)) for n, p in split]
    label = {(f"{n} ({p})" if p else n): n for n, p in split}
    first = {r[0]: num(r[1]) for r in cand_rows}
    exhausted = next(r for r in rows if r[0] == "Exhausted Votes")
    steps, gone = [], set()
    for k, who in enumerate(order):
        col = 2 + 2 * k
        excluded = label.get(who) or next(n for n in label.values() if who.startswith(n))
        gone.add(excluded)
        steps.append({"excluded_candidate": excluded, "exhausted": num(exhausted[col]) or 0.0,
                      "transfers": {r[0]: num(r[col]) or 0.0 for r in cand_rows if r[0] not in gone}})
    last = 1 + 2 * len(order)
    final = {r[0]: num(r[last]) for r in cand_rows if r[0] not in gone and num(r[last]) is not None}
    return _table(cands, first, steps, final)


def fetch_nsw(year: int, raw_dir: Path, refresh: bool = False) -> dict[str, dict]:
    http = CachedSession(refresh)
    event = {2023: "SG2301"}[year]
    listing = http.text(raw_dir / "results.html", NSWEC_VTR + f"{event.lower()}/la/results")
    slugs = sorted(set(re.findall(rf'href="/{event}/LA/([a-z-]+)/dop/dop"', listing)))

    def one(slug: str) -> tuple[str, dict]:
        html = http.text(raw_dir / f"{slug}.html", NSWEC_VTR + f"{event}/LA/{slug}/dop/dop")
        name = re.search(r"State Electoral District of ([^<]+)<", html).group(1).strip()
        return name, _nsw_dop(html)

    with ThreadPoolExecutor(max_workers=6) as pool:
        return dict(pool.map(one, slugs))


FETCHERS = {"QLD": fetch_qld, "WA": fetch_wa, "SA": fetch_sa, "NSW": fetch_nsw}


def validate(tables: dict[str, dict]) -> list[str]:
    """Problems: steps that do not conserve the excluded pile, or progressive totals that miss the final count."""
    issues = []
    for d, t in tables.items():
        totals = dict(t["first_preferences"])
        for s in t["steps"]:
            pile = totals.pop(s["excluded_candidate"], None)
            if pile is None:
                issues.append(f"{d}: excluded {s['excluded_candidate']} not in count")
                break
            moved = sum(s["transfers"].values()) + s["exhausted"]
            if abs(moved - pile) > 1.5:
                issues.append(f"{d}: excluding {s['excluded_candidate']} moved {moved:.0f} of {pile:.0f}")
            for c, v in s["transfers"].items():
                totals[c] = totals.get(c, 0) + v
        if t["final_totals"] and len(totals) == 2 and any(abs(totals.get(c, -1) - v) > 1.5 for c, v in t["final_totals"].items()):
            issues.append(f"{d}: progressive totals {totals} != final {t['final_totals']}")
    return issues
