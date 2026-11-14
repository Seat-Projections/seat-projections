#!/usr/bin/env python3
"""
Declared winners (party group per district) for state elections used as benchmarks, saved to
data/benchmarks/winners/<election>.csv. Victoria uses the parsed VEC results instead.

Source: Wikipedia post-election pendulums (QLD 2020, NSW 2023, QLD 2024) and members-elected tables
(WA 2021, SA 2022, WA 2025, SA 2026), which cite the electoral commissions. Each file's party totals
are checked against the official seat totals in ELECTIONS below.
"""
from __future__ import annotations

import csv
import json
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

from vic_election.config import WINNERS_DIR as OUT
from vic_election.wiki_winners import parse_members_table, parse_pendulum
ELECTIONS = {
    "QLD2020": ("Post-election pendulum for the 2020 Queensland state election", parse_pendulum,
                {"ALP": 52, "LNP": 34, "KAP": 3, "GRN": 2, "ON": 1, "IND*": 1}),
    "WA2021": ("Members of the Western Australian Legislative Assembly, 2021–2025", parse_members_table,
               {"ALP": 53, "NP": 4, "LP": 2}),
    "SA2022": ("Members of the South Australian House of Assembly, 2022–2026", lambda w: parse_members_table(w, year=2022),
               {"ALP": 27, "LP": 16, "IND*": 4}),
    "NSW2023": ("Post-election pendulum for the 2023 New South Wales state election", parse_pendulum,
                {"ALP": 45, "LP": 25, "NP": 11, "IND*": 9, "GRN": 3}),
    "QLD2024": ("Post-election pendulum for the 2024 Queensland state election", parse_pendulum,
                {"LNP": 52, "ALP": 36, "KAP": 3, "GRN": 1, "IND*": 1}),
    "WA2025": ("Members of the Western Australian Legislative Assembly, 2025–2029", parse_members_table,
               {"ALP": 46, "LP": 7, "NP": 6}),
    "SA2026": ("Members of the South Australian House of Assembly, 2026–2030", parse_members_table,
               {"ALP": 34, "LP": 5, "ON": 4, "IND*": 4}),
}


def wikitext(page: str) -> str:
    url = ("https://en.wikipedia.org/w/api.php?action=parse&prop=wikitext&format=json&formatversion=2&redirects=1&page="
           + urllib.parse.quote(page))
    req = urllib.request.Request(url, headers={"User-Agent": "VicElectionResearch/1.0"})
    return json.load(urllib.request.urlopen(req, timeout=60))["parse"]["wikitext"]


def main() -> None:
    refresh = "--refresh" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    for election, (page, parser, official) in ELECTIONS.items():
        if (OUT / f"{election}.csv").exists() and not refresh:  # cached; Wikipedia rate-limits repeated calls
            print(f"{election}: cached")
            continue
        time.sleep(2)
        winners = parser(wikitext(page))
        totals = dict(Counter(winners.values()))
        if totals != official:
            raise SystemExit(f"{election}: parsed totals {totals} != official {official}")
        with (OUT / f"{election}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["district", "party", "source"])
            for d in sorted(winners):
                w.writerow([d, winners[d], f"https://en.wikipedia.org/wiki/{urllib.parse.quote(page.replace(' ', '_'))}"])
        print(f"{election}: {len(winners)} districts {totals}")


if __name__ == "__main__":
    main()
