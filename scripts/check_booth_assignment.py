#!/usr/bin/env python3
"""
Checks the polling-place -> state-district assignment behind every benchmark run (config.RUNS) and writes
predictions/benchmarking/booth_assignment_checks.md (+ .json).

For each run it reports how many polling places (and votes) were counted, why the rest were not,
and flags possible problems:
  - booths inside more than one district polygon (overlapping or duplicated boundaries)
  - booths whose federal division has no boundary (own-division check skipped)
  - districts with no counted booth
  - districts whose counted vote is far from the state median (outside OUTLIER_BOUNDS)
  - booths placed in a district of another state's boundary set (outside every district)
  - vote conservation: district totals must add up to the counted booth votes
"""
from __future__ import annotations

import json
from collections import Counter
from statistics import median

from vic_election.booth_flows import OWN_DIVISION_TOLERANCE_KM, assign_booths, load_booth_flows, load_polling_places
from vic_election.config import BENCHMARKS_DIR, FEDERAL_BOUNDARIES_DIR, ROOT, RUNS, BenchmarkRun
from vic_election.geo import fetch_national_divisions, load_state_districts

OUTLIER_BOUNDS = (0.4, 2.5)  # a district's counted vote / state median outside this range is flagged
MAX_MULTI_BOOTHS_LISTED = 10
OUT_OF_DIVISION = f"outside own division (> {OWN_DIVISION_TOLERANCE_KM:g} km)"


def check(bench: BenchmarkRun) -> dict:
    districts = load_state_districts(bench.state, bench.state_election)
    divisions = fetch_national_divisions(FEDERAL_BOUNDARIES_DIR, bench.federal_year, states=(bench.state,))
    places = load_polling_places(bench.federal_dir / "general", bench.event, bench.state)
    booths, declaration = load_booth_flows(bench.federal_dir / "house", bench.event, bench.state)
    assignment = assign_booths(places, districts, divisions)

    votes = {pid: b.total for pid, b in booths.items()}
    reasons, reason_votes = Counter(), Counter()
    per_district, booths_per_district = Counter(), Counter()
    multi, no_division = [], set()
    division_names = {d.name.lower() for d in divisions}
    for pid, p in places.items():
        loc = assignment[pid]
        v = votes.get(pid, 0)
        if loc.counted:
            key = "counted"
            per_district[loc.district] += v
            booths_per_district[loc.district] += 1
        elif loc.method == "inside":
            key = OUT_OF_DIVISION
        else:
            key = loc.method
        reasons[key] += 1
        reason_votes[key] += v
        if p["DivisionNm"].lower() not in division_names:
            no_division.add(p["DivisionNm"])
        if p["Latitude"] and p["Longitude"]:
            lon, lat = float(p["Longitude"]), float(p["Latitude"])
            hits = [d.name for d in districts if d.contains(lon, lat)]
            if len(hits) > 1:
                multi.append((p["PollingPlaceNm"], hits, v))

    med = median(per_district.values()) if per_district else 0
    low, high = OUTLIER_BOUNDS
    outliers = sorted(((d, per_district[d], round(per_district[d] / med, 2)) for d in per_district
                       if med and not low <= per_district[d] / med <= high), key=lambda x: x[2])
    booth_votes = sum(votes.values())
    return {
        "run": bench.run_id, "state": bench.state, "federal": bench.federal_year, "districts": len(districts),
        "polling_places": len(places), "booth_votes": booth_votes, "declaration_votes": sum(b.total for b in declaration.values()),
        "reasons": dict(reasons), "reason_votes": dict(reason_votes),
        "counted_share": round(100 * reason_votes["counted"] / booth_votes, 1) if booth_votes else 0,
        "conserved": sum(per_district.values()) == reason_votes["counted"],
        "empty_districts": [d.name for d in districts if not booths_per_district[d.name]],
        "multi_district_booths": multi, "divisions_without_boundary": sorted(no_division),
        "median_district_votes": med, "outlier_districts": outliers,
        "min_booths": min(booths_per_district.values()) if booths_per_district else 0,
    }


def summary_table(results: list[dict]) -> list[str]:
    lines = ["| Run | Districts | Polling places | Counted booths | Counted votes | Outside own division | No coordinates | "
             "Outside every district | Conserved | Empty districts | Booths in 2+ districts | Divisions without boundary |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        rv = r["reason_votes"]
        lines.append(
            f"| {r['run']} | {r['districts']} | {r['polling_places']} | {r['reasons'].get('counted', 0)} | {r['counted_share']}% | "
            f"{rv.get(OUT_OF_DIVISION, 0):,} | {rv.get('no coordinates', 0):,} | "
            f"{rv.get('outside', 0) + rv.get('nearest', 0):,} | {'yes' if r['conserved'] else 'NO'} | {len(r['empty_districts'])} | "
            f"{len(r['multi_district_booths'])} | {len(r['divisions_without_boundary'])} |")
    return lines


def flags(r: dict) -> list[str]:
    out = []
    if r["empty_districts"]:
        out.append(f"- Districts with no counted booth: {', '.join(r['empty_districts'])}")
    if r["multi_district_booths"]:
        listed = r["multi_district_booths"][:MAX_MULTI_BOOTHS_LISTED]
        out.append("- Booths inside two or more district polygons: " + "; ".join(f"{n} ({', '.join(h)}, {v:,} votes)" for n, h, v in listed))
    if r["divisions_without_boundary"]:
        out.append(f"- Federal divisions with no boundary (own-division check skipped): {', '.join(r['divisions_without_boundary'])}")
    if r["outlier_districts"]:
        out.append(f"- Districts far from the median counted vote ({r['median_district_votes']:,}): "
                   + "; ".join(f"{d} {v:,} (×{x})" for d, v, x in r["outlier_districts"]))
    if not r["conserved"]:
        out.append("- District totals do not add up to the counted booth votes")
    return out or ["- No issues found."]


def main() -> None:
    results = [check(bench) for bench in RUNS.values()]
    out = BENCHMARKS_DIR / "booth_assignment_checks.md"
    lines = ["# Polling place → state district assignment checks", "",
             f"Generated by `scripts/check_booth_assignment.py`. A booth is counted when it lies inside a state district and "
             f"within {OWN_DIVISION_TOLERANCE_KM:g} km of its own federal division. Vote figures are ordinary votes at polling places; "
             "declaration votes (absent, postal, provisional, declaration pre-poll) have no location and are never counted.", "",
             *summary_table(results), "", "## Flags by run", ""]
    for r in results:
        lines += [f"### {r['run']}", "", *flags(r), ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(results, indent=1), encoding="utf-8")
    print(f"Wrote {out.relative_to(ROOT)}")
    for r in results:
        print(f"{r['run']:<16} counted {r['counted_share']:>5}%  empty {len(r['empty_districts'])}  multi {len(r['multi_district_booths'])}  "
              f"no-division {len(r['divisions_without_boundary'])}  outliers {len(r['outlier_districts'])}  conserved {r['conserved']}")


if __name__ == "__main__":
    main()
