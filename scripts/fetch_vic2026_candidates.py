#!/usr/bin/env python3
"""
Download (cached) the VEC's list of 2026 Legislative Assembly candidates and write
data/2026/candidates_vic2026.csv: district, ballot position, candidate, party (as registered), party group.

The VEC spreadsheet ("spreadsheet of all the candidates" on vec.vic.gov.au/voting/2026-state-election) lists
candidates per district in ballot-paper order, together with contact persons, phone numbers and email
addresses. Only names and parties are kept; the raw file stays under data/2026/raw/ (not committed).
"""
from __future__ import annotations

import csv
import re
from collections import Counter

import xlrd

from vic_election.benchmark import party_group
from vic_election.config import DATA_DIR
from vic_election.http_cache import CachedSession

URL = "https://www.vec.vic.gov.au/-/media/f487c2abe7274ed4b5bb60daa2b001ad.xls"
RAW = DATA_DIR / "2026" / "raw" / "candidates_vic2026.xls"
OUT = DATA_DIR / "2026" / "candidates_vic2026.csv"


def parse(content: bytes) -> tuple[list[dict], dict[str, int], str]:
    sheet = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
    rows = [[str(c).strip() for c in sheet.row_values(i)] for i in range(sheet.nrows)]
    as_at = next((r[0] for r in rows if r[0].startswith("As at")), "")
    district, position, out, declared = None, 0, [], {}
    for r in rows:
        a = r[0]
        if m := re.fullmatch(r"(.+) District", a):
            district, position = m.group(1), 0
        elif a.endswith(" Region"):  # upper-house regions follow the districts
            district = None
        elif m := re.match(r"\(1 vacancy, (\d+) candidates?\)", a):
            if district:
                declared[district] = int(m.group(1))
        elif district and a and a != "Candidates":
            position += 1
            out.append({"district": district, "ballot_position": position, "candidate": a, "party": r[4], "party_group": party_group(r[4]) if r[4] else "IND*"})
    return out, declared, as_at


def main() -> None:
    cands, declared, as_at = parse(CachedSession().bytes(RAW, URL))
    counts = Counter(c["district"] for c in cands)
    bad = {d: (counts[d], n) for d, n in declared.items() if counts[d] != n}
    if len(declared) != 88 or bad:
        raise SystemExit(f"Candidate counts do not match the VEC's per-district totals: {bad or len(declared)}")
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(cands[0]))
        w.writeheader()
        w.writerows(cands)
    print(f"{len(cands)} candidates in {len(counts)} districts ({as_at}) -> {OUT.relative_to(DATA_DIR.parent)}")
    print("By party group:", dict(Counter(c["party_group"] for c in cands).most_common()))


if __name__ == "__main__":
    main()
