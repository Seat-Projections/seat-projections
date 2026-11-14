"""
Federal two-candidate-preferred (TCP) preference flows at each polling place, collated into state districts.

For every polling place the AEC publishes how each candidate's ballots split between the division's final
two (`HouseTcpFlowByPPDownload`). Polling places are placed in state districts by location, and their flows
are added up by party. Summing vote counts (rather than averaging percentages) weights every booth, and
every federal division that contributes booths to a district, by its number of votes.

Candidates are matched across divisions by party. Independents are individuals, so pooling them is not a
like-for-like merge: they are pooled into one `IND*` group for now, and every group records which
candidates it contains, so any merge of several independents is visible.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from .aec import read_aec_csv
from .geo import District, assign_point

FIRST = "FIRST"
IND = "IND*"
INDIVIDUALS = {"IND", "NAFD"}  # independents and non-affiliated candidates: people, not parties
ALIASES = {"GVIC": "GRN", "FFPA": "FFP", "": "NAFD"}  # state-branch codes in the AEC candidate file -> national codes
LABELS = {
    FIRST: "First preferences (finalists' own votes)", IND: "Independent*",
    "ALP": "Labor", "LP": "Liberal", "NP": "Nationals", "GRN": "Greens", "ON": "One Nation", "FFP": "Family First",
    "CYA": "Trumpet of Patriots", "UAPP": "United Australia", "LTP": "Libertarian", "LDP": "Liberal Democrats",
    "HMP": "Legalise Cannabis", "VNS": "Victorian Socialists", "SAL": "Socialist Alliance", "AJP": "Animal Justice",
    "CEC": "Citizens Party", "GRPF": "Gerard Rennick People First", "SOPA": "FUSION", "DHJP": "Derryn Hinch's Justice",
    "GAP": "Great Australian", "TNL": "The New Liberals", "REAS": "Reason", "AUVA": "Australian Values",
}


PRE_POLL_PLACE_TYPE_ID = "5"  # AEC PollingPlaceTypeID for pre-poll voting centres (1 = ordinary polling place)


@dataclass(frozen=True)
class AecCandidate:
    """A House candidate from the AEC candidate file (distinct from models.Candidate, the IRV engine's record)."""

    id: str
    name: str  # "SURNAME, Given"
    party: str  # national party code; IND / NAFD for individuals
    division: str

    @property
    def group(self) -> str:
        return IND if self.party in INDIVIDUALS else self.party


@dataclass
class BoothFlows:
    """One polling place: votes from each candidate (or FIRST for the finalists' own votes) to each finalist."""

    ppid: str
    name: str
    division: str
    finalists: tuple[str, ...]
    votes: dict[tuple[str, str], int]

    @property
    def total(self) -> int:
        return sum(self.votes.values())


def load_candidates(house_dir: Path, event: int) -> dict[str, AecCandidate]:
    return {
        r["CandidateID"]: AecCandidate(
            r["CandidateID"],
            f"{r['Surname']}, {r['GivenNm']}" if r["GivenNm"] else r["Surname"],
            ALIASES.get(r["PartyAb"], r["PartyAb"]),
            r["DivisionNm"],
        )
        for r in read_aec_csv(house_dir / f"HouseCandidatesDownload-{event}.csv")
    }


def load_booth_flows(house_dir: Path, event: int, state: str) -> tuple[dict[str, BoothFlows], dict[tuple[str, str], BoothFlows]]:
    """
    Returns (booths by polling-place ID, declaration votes by (division, kind)). Declaration votes (ABSENT,
    POSTAL, PRE_POLL, PROVISIONAL) are published per division with polling-place ID 0, so they have no location.
    """
    booths: dict[str, BoothFlows] = {}
    declaration: dict[tuple[str, str], BoothFlows] = {}
    for path in sorted((house_dir / f"HouseTcpFlowByPPDownload-{event}-{state}").glob("*.csv")):
        for r in read_aec_csv(path):
            store, key = (booths, r["PPId"]) if r["PPId"] != "0" else (declaration, (r["DivisionNm"], r["PPNm"]))
            if key not in store:
                store[key] = BoothFlows(r["PPId"], r["PPNm"], r["DivisionNm"], (), {})
            b = store[key]
            src = FIRST if r["FromCandidateId"] == "0" else r["FromCandidateId"]
            to = r["ToCandidateId"]
            b.votes[(src, to)] = b.votes.get((src, to), 0) + int(r["TransferCount"])
            if to not in b.finalists:
                b.finalists += (to,)
    return booths, declaration


def load_polling_places(general_dir: Path, event: int, state: str) -> dict[str, dict[str, str]]:
    return {r["PollingPlaceID"]: r for r in read_aec_csv(general_dir / f"GeneralPollingPlacesDownload-{event}.csv") if r["State"] == state}


# A booth serves voters who live in its own federal division. Booths just across a division boundary still
# serve nearby voters; booths far outside it (pre-poll centres and CBD booths taking votes for other
# divisions) do not, so their votes cannot be placed by location.
OWN_DIVISION_TOLERANCE_KM = 1.0


@dataclass(frozen=True)
class BoothLocation:
    district: str | None
    method: str  # 'inside', 'nearest' (within geo.NEAREST_DISTRICT_MAX_KM of a district), 'outside' or 'no coordinates'
    division_km: float | None  # distance outside its own federal division (0 = inside); None if unknown
    in_division: bool  # inside its own division or within the tolerance of it (True when unknown)

    @property
    def counted(self) -> bool:
        """Counted in its district's collated flows: inside the district and (near enough) inside its own division."""
        return self.method == "inside" and self.in_division


def assign_booths(
    places: dict[str, dict[str, str]],
    districts: list[District],
    divisions: list[District] | None = None,
    tolerance_km: float = OWN_DIVISION_TOLERANCE_KM,
) -> dict[str, BoothLocation]:
    by_name = {d.name.lower(): d for d in divisions or []}
    out = {}
    for pid, p in places.items():
        if not (p["Latitude"] and p["Longitude"]):
            out[pid] = BoothLocation(None, "no coordinates", None, True)
            continue
        lon, lat = float(p["Longitude"]), float(p["Latitude"])
        district, method = assign_point(districts, lon, lat)
        div = by_name.get(p["DivisionNm"].lower())
        km = None if div is None else 0.0 if div.contains(lon, lat) else round(div.distance(lon, lat), 2)
        out[pid] = BoothLocation(district, method, km, km is None or km <= tolerance_km)
    return out


def _column_keys(booth: BoothFlows, candidates: dict[str, AecCandidate]) -> dict[str, str]:
    keys = {cid: candidates[cid].group for cid in booth.finalists}
    if len(set(keys.values())) < len(keys):  # e.g. two independents in the final two: keep them apart
        keys = {cid: f"{k} {candidates[cid].name.split(',')[0]}" for cid, k in keys.items()}
    return keys


def _members(cands: dict[str, AecCandidate]) -> list[str]:
    return sorted(f"{c.name} ({c.division})" for c in cands.values())


def collate(booths: list[BoothFlows], candidates: dict[str, AecCandidate]) -> dict:
    """
    Party-level flow matrix for a set of booths. Rows: FIRST (the finalists' own votes), then each party
    group of excluded candidates. Columns: finalist party groups. Cells sum votes; a cell is None when that
    column was never a finalist at any booth where the row's candidates stood.
    """
    cells: dict[str, Counter] = defaultdict(Counter)
    applicable: dict[str, set[str]] = defaultdict(set)
    row_members: dict[str, dict[str, AecCandidate]] = defaultdict(dict)
    col_members: dict[str, dict[str, AecCandidate]] = defaultdict(dict)
    row_divisions: dict[str, set[str]] = defaultdict(set)
    for b in booths:
        cols = _column_keys(b, candidates)
        for cid, key in cols.items():
            col_members[key][cid] = candidates[cid]
        for (src, to), v in b.votes.items():
            row = FIRST if src == FIRST else candidates[src].group
            cells[row][cols[to]] += v
            applicable[row].update(cols.values())
            row_divisions[row].add(b.division)
            if src != FIRST:
                row_members[row][src] = candidates[src]

    total = sum(sum(c.values()) for c in cells.values())
    col_votes = {k: sum(cells[r][k] for r in cells) for k in col_members}
    columns = sorted(col_members, key=lambda k: -col_votes[k])
    order = [FIRST] + sorted((r for r in cells if r != FIRST), key=lambda r: -sum(cells[r].values()))

    def is_individual(key: str) -> bool:
        return key.startswith(IND)

    rows = []
    for r in order:
        row_total = sum(cells[r].values())
        if not row_total:  # candidates who stood but received no votes at these booths
            continue
        votes = [cells[r][c] if c in applicable[r] else None for c in columns]
        members = {k: v for m in col_members.values() for k, v in m.items()} if r == FIRST else row_members[r]
        rows.append({
            "key": r,
            "label": LABELS.get(r, r),
            "votes": votes,
            "total": row_total,
            "pct": [round(100 * v / row_total, 2) if v is not None and row_total else None for v in votes],
            "candidates": _members(members),
            "individual": is_individual(r),
            "merged": is_individual(r) and len(row_members[r]) > 1,
            "divisions": sorted(row_divisions[r]),
        })
    return {
        "total": total,
        "columns": [
            {"key": k, "label": LABELS.get(k, k), "votes": col_votes[k], "pct": round(100 * col_votes[k] / total, 2) if total else 0.0,
             "candidates": _members(col_members[k]), "individual": is_individual(k), "merged": is_individual(k) and len(col_members[k]) > 1}
            for k in columns
        ],
        "rows": rows,
    }


def _pair_label(booth: BoothFlows, candidates: dict[str, AecCandidate]) -> str:
    return " v ".join(sorted(_column_keys(booth, candidates).values()))


def collate_district(booths: list[BoothFlows], candidates: dict[str, AecCandidate], pre_poll: set[str]) -> dict:
    """Overall matrix for a district, plus its contributing divisions and one matrix per final-two pairing."""
    out = collate(booths, candidates)
    total = out["total"]
    by_div: dict[str, list[BoothFlows]] = defaultdict(list)
    by_pair: dict[str, list[BoothFlows]] = defaultdict(list)
    for b in booths:
        by_div[b.division].append(b)
        by_pair[_pair_label(b, candidates)].append(b)

    def share(v: int) -> float:
        return round(100 * v / total, 2) if total else 0.0

    out["booths"] = len(booths)
    out["pre_poll_share"] = share(sum(b.total for b in booths if b.ppid in pre_poll))
    out["divisions"] = sorted(
        (
            {
                "division": d,
                "booths": len(bs),
                "votes": sum(b.total for b in bs),
                "share": share(sum(b.total for b in bs)),
                "final_two": [f"{candidates[c].name} ({candidates[c].group})" for c in bs[0].finalists],
                "pair": _pair_label(bs[0], candidates),
            }
            for d, bs in by_div.items()
        ),
        key=lambda d: -d["votes"],
    )
    out["pairs"] = sorted(
        ({"pair": p, "votes": sum(b.total for b in bs), "share": share(sum(b.total for b in bs)), "divisions": sorted({b.division for b in bs})}
         for p, bs in by_pair.items()),
        key=lambda p: -p["votes"],
    )
    if len(by_pair) > 1:
        out["by_pair"] = {p: collate(bs, candidates) for p, bs in by_pair.items()}
    return out


def _exclusion_reason(loc: BoothLocation) -> str:
    if loc.method == "no coordinates":
        return "no coordinates (mobile or hospital team)"
    if loc.method != "inside":
        return f"not inside a district ({loc.method}{' to ' + loc.district if loc.district else ''})"
    return f"{loc.division_km} km outside its own federal division"


def build_district_flows(
    year_dir: Path,
    event: int,
    state: str,
    districts: list[District],
    divisions: list[District],
    tolerance_km: float = OWN_DIVISION_TOLERANCE_KM,
    assignment: dict[str, BoothLocation] | None = None,
) -> dict:
    """
    Collated flows for every district from the booths lying inside it, excluding booths more than
    `tolerance_km` outside their own federal division. Declaration votes are not included: they have no
    location. Every excluded booth is listed with its reason and votes.
    """
    candidates = load_candidates(year_dir / "house", event)
    booths, declaration = load_booth_flows(year_dir / "house", event, state)
    places = load_polling_places(year_dir / "general", event, state)
    assignment = assignment or assign_booths(places, districts, divisions, tolerance_km)
    pre_poll = {pid for pid, p in places.items() if p["PollingPlaceTypeID"] == PRE_POLL_PLACE_TYPE_ID}

    by_district: dict[str, list[BoothFlows]] = defaultdict(list)
    excluded = []
    # Votes per division that cannot be placed by location (for apportioning later): declaration votes plus excluded booths
    unlocated: dict[str, Counter] = defaultdict(Counter)
    for (division, kind), b in declaration.items():
        unlocated[division][kind.lower()] += b.total
    for pid, b in booths.items():
        loc = assignment[pid]
        if loc.counted:
            by_district[loc.district].append(b)
        else:
            reason = _exclusion_reason(loc)
            excluded.append({"ppid": pid, "name": b.name, "division": b.division, "votes": b.total, "district": loc.district, "reason": reason})
            unlocated[b.division]["out_of_division" if loc.method == "inside" else loc.method.replace(" ", "_")] += b.total

    return {
        "event": event,
        "state": state,
        "booth_votes": sum(b.total for b in booths.values()),
        "counted_votes": sum(b.total for bs in by_district.values() for b in bs),
        "declaration_votes": sum(b.total for b in declaration.values()),
        "own_division_tolerance_km": tolerance_km,
        "excluded_booths": sorted(excluded, key=lambda e: -e["votes"]),
        "unlocated_by_division": {d: dict(c) for d, c in sorted(unlocated.items())},
        "districts": {d.name: {"region": d.region, **collate_district(by_district[d.name], candidates, pre_poll)} for d in districts},
    }


def write_flows_csv(result: dict, path: Path) -> None:
    """Long format: one row per (district, booth set, from group, to finalist group)."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "booth_set", "from_group", "from_label", "to_group", "votes", "row_total", "pct",
                    "individual", "independents_merged", "candidates", "divisions"])
        for name, d in result["districts"].items():
            matrices = [("all booths", d)] + [(f"final two: {p}", m) for p, m in d.get("by_pair", {}).items()]
            for label, m in matrices:
                for r in m["rows"]:
                    for col, v, p in zip(m["columns"], r["votes"], r["pct"]):
                        w.writerow([name, label, r["key"], r["label"], col["key"], "" if v is None else v, r["total"],
                                    "" if p is None else p, "Y" if r["individual"] else "", len(r["candidates"]) if r["merged"] else "",
                                    "; ".join(r["candidates"]), "; ".join(r["divisions"])])
