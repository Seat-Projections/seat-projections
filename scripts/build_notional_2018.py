#!/usr/bin/env python3
"""
2018 Victorian first preferences re-cut onto the 2022 (EBC 2021 redivision) district boundaries.

Downloads (cached) the VEC 2018 first preferences by voting centre, the VEC 2018 voting-centre
locations and the 2013-redivision district boundaries used in 2018, then writes:

  data/2018/booths/fpv_by_voting_centre_2018.json   every voting centre's first preferences, by 2018 district
  data/2018/notional_2022_boundaries.json            notional 2018 primaries per 2022 district (party groups)
  data/2018/notional_2022_boundaries.csv             the same, long format
  data/2018/boundary_changes_2018_2022.csv           per 2022 district: where its 2018-located electors came from

Requires data/2018/distributions/official_2018.json (scripts/fetch_vec_2018.py).
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict

from vic_election.benchmark import party_group
from vic_election.config import DATA_DIR, VIC_DISTRICTS_GEOJSON, BOUNDARIES_DIR
from vic_election.geo import districts_from_geojson, fetch_vic_districts_2013
from vic_election.vec_booths import (
    fetch_fpv_by_voting_centre_2018, fetch_voting_centre_locations_2018, load_voting_centre_locations, notional, remap,
)

YEAR_DIR = DATA_DIR / "2018"


def main() -> None:
    official = json.loads((YEAR_DIR / "distributions" / "official_2018.json").read_text())
    results = fetch_fpv_by_voting_centre_2018(YEAR_DIR, official)
    locations = load_voting_centre_locations(fetch_voting_centre_locations_2018(YEAR_DIR))
    old = fetch_vic_districts_2013(BOUNDARIES_DIR / "vic_assembly_2014")
    new = districts_from_geojson(json.loads(VIC_DISTRICTS_GEOJSON.read_text()))
    groups = {d: {c["candidate_id"]: party_group(c["party"]) for c in t["candidates"]} for d, t in official.items()}

    (YEAR_DIR / "booths").mkdir(exist_ok=True)
    (YEAR_DIR / "booths" / "fpv_by_voting_centre_2018.json").write_text(json.dumps({
        d: {"source": b.source, "candidates": b.candidates, "centres": b.centres, "declaration": b.declaration} for d, b in results.items()
    }, indent=1), encoding="utf-8")

    mapping = remap(results, locations, old, new)
    notional_votes = notional(results, groups, mapping)
    formal_2018 = sum(t["formal_votes"] for t in official.values())
    assert abs(sum(sum(c.values()) for c in notional_votes.values()) - formal_2018) < 1, "notional votes must conserve the 2018 formal vote"

    ordinary = sum(b.ordinary_total for b in results.values())
    unlocated = Counter()
    for _, _, v, reason in mapping["unlocated"]:
        unlocated[reason] += v
    located = ordinary - sum(unlocated.values())
    meta = {
        "description": "2018 Victorian first preferences on 2022 district boundaries (party groups)",
        "method": "election-day voting centres placed by coordinates; all other votes of each 2018 district spread "
                  "over 2022 districts in proportion to that district's located election-day votes",
        "formal_votes": formal_2018,
        "located_election_day_votes": round(located),
        "located_share_of_formal": round(100 * located / formal_2018, 1),
        "unlocated_election_day_votes": {k: round(v) for k, v in unlocated.items()},
        "fallback_districts": {d: b.source for d, b in results.items() if b.source != "recheck page"},
        "sources": {"results": "VEC fpvbyvotingcentre<district>.html (2018 recheck)", "locations": "VEC voting centre locations 2018 (xlsx)",
                    "old_boundaries": "Vicmap Admin State Assembly Polygon 2013 (WFS)", "new_boundaries": "EBC 2021 redivision KMZ"},
    }
    out = {"meta": meta, "districts": {d: {p: round(v, 1) for p, v in c.most_common()} for d, c in sorted(notional_votes.items())}}
    (YEAR_DIR / "notional_2022_boundaries.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    with (YEAR_DIR / "notional_2022_boundaries.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "party", "votes", "share"])
        for d, c in sorted(notional_votes.items()):
            tot = sum(c.values())
            for p, v in c.most_common():
                w.writerow([d, p, round(v, 1), round(100 * v / tot, 2)])

    # Where each 2022 district's electors were in 2018 (by located election-day votes, all vote types spread alike)
    into: dict[str, Counter] = defaultdict(Counter)
    for o, ws in mapping["weights"].items():
        for n, s in ws.items():
            into[n][o] += s * results[o].total
    old_names = {d.name for d in old}
    with (YEAR_DIR / "boundary_changes_2018_2022.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district_2022", "existed_in_2018", "share_from_same_name", "largest_2018_source", "largest_share", "sources_over_2pct"])
        for n, c in sorted(into.items()):
            tot = sum(c.values())
            main, mv = c.most_common(1)[0]
            w.writerow([n, int(n in old_names), round(c.get(n, 0) / tot, 3), main, round(mv / tot, 3),
                        "; ".join(f"{o} {100 * v / tot:.0f}%" for o, v in c.most_common() if v / tot > 0.02)])

    print(f"{len(notional_votes)} districts; {meta['located_share_of_formal']}% of formal votes located; unlocated election-day: {meta['unlocated_election_day_votes']}")
    print(f"fallbacks: {meta['fallback_districts']}")


if __name__ == "__main__":
    main()
