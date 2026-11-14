#!/usr/bin/env python3
"""
Collated federal preference-flow matrices for each Victorian state district.

Every federal polling place inside a district (and inside, or within 1 km of, its own federal division) is
included; its two-candidate-preferred flows are summed by party, so booths and divisions are weighted by votes.
Independents are pooled into one IND* group, with every pooled candidate listed.

Writes data/federal/{year}/district_flows_VIC.json (full detail) and .csv (long format).
Run scripts/fetch_aec.py first.
"""
from __future__ import annotations

import argparse
import json

from vic_election.booth_flows import OWN_DIVISION_TOLERANCE_KM, build_district_flows, write_flows_csv
from vic_election.config import (
    AEC_EVENTS, AEC_STATES, FEDERAL_BOUNDARIES_DIR, ROOT, VIC_DISTRICTS_GEOJSON, federal_data_dir, vec_distributions_path,
)
from vic_election.geo import fetch_national_divisions, fetch_vic_districts, load_state_districts

VIC_YEARS = [year for year, states in AEC_STATES.items() if "VIC" in states]


def load_districts():
    if VIC_DISTRICTS_GEOJSON.exists():
        return load_state_districts("VIC")
    vec = json.loads(vec_distributions_path(2022).read_text())
    return fetch_vic_districts(VIC_DISTRICTS_GEOJSON.parent, {d.upper(): d for d in vec})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--year", type=int, nargs="*", choices=VIC_YEARS, default=VIC_YEARS)
    parser.add_argument("--division-tolerance-km", type=float, default=OWN_DIVISION_TOLERANCE_KM,
                        help="Count booths up to this far outside their own federal division (default: %(default)s)")
    args = parser.parse_args()
    districts = load_districts()

    for year in args.year:
        divisions = fetch_national_divisions(FEDERAL_BOUNDARIES_DIR, year, states=("VIC",))
        year_dir = federal_data_dir(year)
        result = build_district_flows(year_dir, AEC_EVENTS[year], "VIC", districts, divisions, args.division_tolerance_km)
        (year_dir / "district_flows_VIC.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        write_flows_csv(result, year_dir / "district_flows_VIC.csv")

        d = result["districts"].values()
        reasons: dict[str, list[int]] = {}
        for e in result["excluded_booths"]:
            key = e["reason"].split(" (")[0] if "km outside" not in e["reason"] else "far outside its own federal division"
            reasons.setdefault(key, [0, 0])
            reasons[key][0] += 1
            reasons[key][1] += e["votes"]
        print(f"{year}: {result['counted_votes']:,} of {result['booth_votes']:,} polling-place votes counted in 88 districts "
              f"({100 * result['counted_votes'] / result['booth_votes']:.1f}%); declaration votes (no location): {result['declaration_votes']:,}")
        for k, (n, v) in sorted(reasons.items(), key=lambda kv: -kv[1][1]):
            print(f"  excluded: {k}: {n} booths, {v:,} votes")
        print(f"  districts drawing on more than one final-two pairing: {sum(len(x['pairs']) > 1 for x in d)}; "
              f"with several independents merged: {sum(any(r['merged'] for r in x['rows']) for x in d)}")
        print(f"  wrote {(year_dir / 'district_flows_VIC.json').relative_to(ROOT)} and .csv")


if __name__ == "__main__":
    main()
