#!/usr/bin/env python3
"""
Download (cached) and parse every benchmark state election's district distributions of preferences
(vic_election.state_dop) into data/<RUN>/distributions/dop_<RUN>.json, check that every exclusion
conserves the excluded pile, and that each commission's count agrees with the declared winners in
data/benchmarks/winners/.
"""
from __future__ import annotations

import json
from collections import Counter

from vic_election.benchmark import align_districts, load_winners_csv
from vic_election.config import DATA_DIR, WINNERS_DIR
from vic_election.state_dop import FETCHERS, validate

ELECTIONS = {"QLD2020": ("QLD", 2020), "WA2021": ("WA", 2021), "SA2022": ("SA", 2022),
             "NSW2019": ("NSW", 2019), "NSW2023": ("NSW", 2023),
             "QLD2024": ("QLD", 2024), "WA2025": ("WA", 2025), "SA2026": ("SA", 2026)}


def main() -> None:
    for run, (state, year) in ELECTIONS.items():
        tables = FETCHERS[state](year, DATA_DIR / run / "raw")
        issues = validate(tables)
        if issues:
            raise SystemExit(f"{run}: {len(issues)} inconsistent distributions, e.g. {issues[:3]}")
        out = DATA_DIR / run / "distributions" / f"dop_{run}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(tables, indent=1), encoding="utf-8")
        winners_path = WINNERS_DIR / f"{run}.csv"
        declared = align_districts(load_winners_csv(winners_path), list(tables)) if winners_path.exists() else None
        counted = {}
        for d, t in tables.items():
            party = {c["candidate_id"]: c["party"] for c in t["candidates"]}
            counted[d] = party[max(t["final_totals"], key=t["final_totals"].get)]
        disagree = {} if declared is None else {d: (counted[d], declared[d]) for d in tables if counted[d] != declared[d]}
        exhausted = sum(s["exhausted"] for t in tables.values() for s in t["steps"]) / sum(t["formal_votes"] for t in tables.values())
        print(f"{run}: {len(tables)} districts, {sum(len(t['steps']) for t in tables.values())} exclusions, "
              f"exhausted {100 * exhausted:.2f}% of formal; count winner vs declared winner disagree in {len(disagree)}: {disagree}")
        print(f"   count winners: {dict(Counter(counted.values()).most_common())}")


if __name__ == "__main__":
    main()
