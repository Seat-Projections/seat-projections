"""
VEC first preferences by voting centre (2018) and their locations, for remapping a past election onto
new district boundaries.

Source: the VEC's recheck pages `fpvbyvotingcentre<slug>.html` (cached in
`data/2018/raw/fpv_by_voting_centre/`), which reconcile exactly with the official formal votes. (The
`primary_by_voting_centre/*.xlsx` workbooks predate the recheck and are 0.1% higher.) Each page lists every
election-day voting centre, then district-wide rows for postal, early, marked-as-voted, provisional and
absent votes. Early votes are not broken down by early voting centre, so only ordinary election-day
votes have a location. The VEC's voting-centre location file gives each centre's coordinates.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from bs4 import BeautifulSoup

from .http_cache import CachedSession

STATE2018_BASE_URL = "https://itsitecoreblobvecprd01.blob.core.windows.net/public-files/historical-results/state2018/"
VC_LOCATIONS_2018_URL = "https://www.vec.vic.gov.au/-/media/d537f12314234c3da9d9a55ffde16b16.xlsx"
DECLARATION_ROWS = {"Postal Votes": "postal", "Early Votes": "early", "Marked As Voted Votes": "marked_as_voted",
                    "Provisional Votes": "provisional", "Absent Votes": "absent", "All Votes Votes": "all_votes"}


@dataclass
class DistrictBooths:
    district: str
    candidates: list[tuple[str, str]]  # (name, party as printed; "" for independents)
    centres: dict[str, dict[str, float]] = field(default_factory=dict)  # centre -> candidate -> formal votes
    declaration: dict[str, dict[str, float]] = field(default_factory=dict)  # vote type -> candidate -> votes
    source: str = "recheck page"

    @property
    def ordinary_total(self) -> int:
        return sum(sum(v.values()) for v in self.centres.values())

    @property
    def total(self) -> int:
        return self.ordinary_total + sum(sum(v.values()) for v in self.declaration.values())


def parse_fpv_by_voting_centre(html: str) -> DistrictBooths:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find(string=re.compile(r"District", re.I))
    table = next(t for t in soup.find_all("table") if t.find(string=re.compile("Voting Centres")))
    rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])] for tr in table.find_all("tr")]
    names, parties = rows[0], rows[1]
    cols = [i for i in range(1, len(names)) if names[i]]
    district = re.sub(r"\s+District.*$", "", str(title).strip()) if title else ""
    out = DistrictBooths(district, [(names[i], parties[i]) for i in cols])
    for r in rows[2:]:
        label = r[0] if r else ""
        if not label or label.startswith(("Ordinary Votes Total", "Total", "Percentage")):
            continue
        votes = {names[i]: int(r[i].replace(",", "")) for i in cols}
        if label in DECLARATION_ROWS:
            out.declaration[DECLARATION_ROWS[label]] = votes
        else:
            out.centres[label] = votes
    return out


XLSX_DECLARATION_ROWS = {"Postal Vote": "postal", "Early Vote": "early", "Marked as Voted": "marked_as_voted",
                         "Provisional": "provisional", "Absent": "absent"}


def parse_voting_centre_workbook(path: Path) -> DistrictBooths:
    """The pre-recheck workbook (`primary_by_voting_centre/<slug>.xlsx`); same layout as the recheck page."""
    rows = list(openpyxl.load_workbook(path, read_only=True).worksheets[0].iter_rows(values_only=True))
    header = next(r for r in rows if any(isinstance(c, str) and "Total Votes" in c for c in r))
    cols = [i for i, c in enumerate(header) if isinstance(c, str) and c.strip() and "Informal" not in c and "Total" not in c]
    split = [header[i].strip().partition("\n") for i in cols]
    out = DistrictBooths(re.sub(r"\s+District \(Primary\)$", "", str(rows[3][0]).strip()), [(n.strip(), p.strip()) for n, _, p in split])
    section = out.centres
    for r in rows[rows.index(header) + 1:]:
        label = str(r[1]).strip() if len(r) > 1 and r[1] else ""
        if label.startswith("Percentage"):
            break
        if label.startswith("Total Ordinary"):
            section = None
        elif label and not label.startswith(("Total", "TOTAL")):
            votes = {name: int(r[i]) for i, (name, _) in zip(cols, out.candidates)}
            if section is not None:
                section[label] = votes
            elif label in XLSX_DECLARATION_ROWS:
                out.declaration[XLSX_DECLARATION_ROWS[label]] = votes
    return out


def _rescaled(b: DistrictBooths, official: dict[str, int]) -> DistrictBooths:
    """Scale each candidate's votes in every row so their totals equal the official first preferences."""
    tot = Counter()
    for row in [*b.centres.values(), *b.declaration.values()]:
        tot.update(row)
    f = {n: official[n] / tot[n] if tot[n] else 0.0 for n in official}
    for rows in (b.centres, b.declaration):
        for k, row in rows.items():
            rows[k] = {n: v * f[n] for n, v in row.items()}
    return b


def fetch_fpv_by_voting_centre_2018(data_dir: Path, official: dict, refresh: bool = False, max_workers: int = 8) -> dict[str, DistrictBooths]:
    """
    District -> first preferences by voting centre for 2018, from the VEC recheck pages (cached under
    data_dir/raw/fpv_by_voting_centre/). `official` is the parsed official_2018.json, which supplies the page
    names and is the reconciliation target. Where a page is unusable the pre-recheck workbook is used,
    rescaled per candidate to the official totals, and `source` says why: Brunswick's page holds the 2014
    result, and Ripon's (recounted) page has a single "All Votes" row with no voting-centre breakdown.
    """
    http = CachedSession(refresh)

    def one(district: str) -> DistrictBooths:
        t = official[district]
        slug = re.sub(r"^distribution", "", t["source_url"].rsplit("/", 1)[-1]).removesuffix(".html")
        page = f"fpvbyvotingcentre{slug}.html"
        b = parse_fpv_by_voting_centre(http.text(data_dir / "raw" / "fpv_by_voting_centre" / page, STATE2018_BASE_URL + page))
        problem = ("recheck page holds the wrong election" if {n for n, _ in b.candidates} != set(t["first_preferences"])
                   else "recheck page has no voting-centre breakdown" if not b.ordinary_total else None)
        if problem:
            b = _rescaled(parse_voting_centre_workbook(data_dir / "raw" / "primary_by_voting_centre" / f"{slug}.xlsx"), t["first_preferences"])
            b.source = f"pre-recheck workbook, rescaled to official totals ({problem})"
        b.district = district
        return b

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return {b.district: b for b in pool.map(one, sorted(official))}


def fetch_voting_centre_locations_2018(data_dir: Path, refresh: bool = False) -> Path:
    path = data_dir / "raw" / "voting_centres" / "voting_centre_locations_2018.xlsx"
    CachedSession(refresh).bytes(path, VC_LOCATIONS_2018_URL)
    return path


def load_voting_centre_locations(path: Path) -> dict[tuple[str, str], tuple[float, float, str]]:
    """
    (district, centre name) -> (lon, lat, centre type), from the VEC 'VC Locations' sheet. A centre serving
    two districts is listed under both (Electorate1 and Electorate2).
    """
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    rows = ws.iter_rows(values_only=True)
    ix = {h: i for i, h in enumerate(next(rows))}
    out = {}
    for r in rows:
        if r[ix["_x"]] is None:
            continue
        for col in ("Electorate1", "Electorate2"):
            if r[ix[col]]:
                district = re.sub(r"\s+District( \(\d{4}\))?$", "", str(r[ix[col]]).strip())
                out.setdefault((district, str(r[ix["Name"]]).strip()), (float(r[ix["_x"]]), float(r[ix["_y"]]), str(r[ix["Type"]])))
    return out


def remap(results: dict[str, DistrictBooths], locations, old_districts, new_districts) -> dict:
    """
    Place each old district's election-day voting centres in the new districts.

    A centre is *located* if it has coordinates inside its own old district; its votes go to the new
    district containing it. Centres without coordinates, or sited outside their own district (they serve
    that district's electors from just over the line), are *unlocated*. Returns per old district the
    located votes by new district and candidate, the unlocated centres, and `weights`: old -> new -> share
    of the old district's located votes, used to spread everything that has no location.
    """
    from .geo import assign_point
    own = {d.name: d for d in old_districts}
    located: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))
    unlocated = []
    for old, b in results.items():
        for centre, votes in b.centres.items():
            loc = locations.get((old, centre))
            reason = ("no coordinates" if loc is None else
                      "outside own district" if not own[old].contains(loc[0], loc[1]) else None)
            new = None if reason else assign_point(new_districts, loc[0], loc[1])[0]
            if new is None:
                unlocated.append((old, centre, sum(votes.values()), reason or "outside every new district"))
            else:
                located[old][new].update(votes)
    weights = {}
    for old, by_new in located.items():
        tot = sum(sum(c.values()) for c in by_new.values())
        weights[old] = {n: sum(c.values()) / tot for n, c in by_new.items()}
    return {"located": located, "unlocated": unlocated, "weights": weights}


def notional(results: dict[str, DistrictBooths], groups: dict[str, dict[str, str]], mapping: dict) -> dict[str, Counter]:
    """
    New district -> party group -> notional votes. Located election-day votes go where their centre is;
    each old district's remaining votes (unlocated centres, early, postal, absent, provisional) are spread
    over the new districts by `mapping['weights']`. `groups[old][candidate]` is the candidate's party group.
    Every old district's formal vote is conserved.
    """
    out: dict[str, Counter] = defaultdict(Counter)
    for old, b in results.items():
        g = groups[old]
        rest = Counter()
        for row in b.declaration.values():
            rest.update(row)
        located_centres = Counter()
        for new, votes in mapping["located"].get(old, {}).items():
            for cand, v in votes.items():
                out[new][g[cand]] += v
            located_centres.update(votes)
        for centre_votes in b.centres.values():
            rest.update(centre_votes)
        rest.subtract(located_centres)
        for new, w in mapping["weights"][old].items():
            for cand, v in rest.items():
                out[new][g[cand]] += v * w
    return dict(out)
