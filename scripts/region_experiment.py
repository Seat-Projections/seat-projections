#!/usr/bin/env python3
"""
Regional-error experiment for model2's forecast backtests (VIC2022, QLD2024, WA2025, SA2026 F runs).

Regions for the non-Victorian runs come from ABS ASGS Edition 3 (2021) SA4 boundaries
(data/benchmarks/raw/SA4_2021_AUST_SHP_GDA94.zip, fetched from the ASGS Edition 3 digital boundary
files page). Each district is assigned to the SA4 group holding the largest share of its counted
federal booth votes — model1's own booth assignment for the run's preceding federal election —
with a polygon interior point as the fallback for districts without counted booths.

  PYTHONPATH=<repo>/src python predictions/modelling/model2/region_experiment.py

Settings:
  A  current — VIC keeps Legislative Council regions, others one region; region_sd 2 (must match the
     published F scores)
  B  SA4 groups, region_sd 1/2/3/4
  C  GCCSA (capital vs rest), region_sd 2/3

Writes predictions/benchmarking/region_experiment.csv and one district-region map CSV per state.
Simulation outputs go to a temp dir only.
"""
from __future__ import annotations

import csv
import json
import sys
import tempfile
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

from multiprocessing import Pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "predictions" / "modelling" / "model2"))
import model2
import run_model2
from vic_election.benchmark import norm_district, score
from vic_election.booth_flows import assign_booths, load_booth_flows, load_polling_places
from vic_election.config import DATA_DIR, FEDERAL_BOUNDARIES_DIR, ROOT, RUNS
from vic_election.geo import (District, _bbox, assign_point, fetch_national_divisions,
                              load_state_districts, read_dbf, read_shp_polygons, shapefile_polygons)

# model2 F run -> the model1 run on its preceding federal election (same booth data model1 used)
F_RUNS = {
    "VIC2022 (F)": "VIC2022 (2022)",
    "QLD2024 (F)": "QLD2024 (2022)",
    "WA2025 (F)": "WA2025 (2022)",
    "SA2026 (F)": "SA2026 (2025)",
}

SA4_ZIP = DATA_DIR / "benchmarks" / "raw" / "SA4_2021_AUST_SHP_GDA94.zip"
SA4_URL = ("https://www.abs.gov.au/statistics/standards/"
           "australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/"
           "access-and-downloads/digital-boundary-files/SA4_2021_AUST_SHP_GDA94.zip")

# SA4 groupings (region name -> SA4 names, exact ASGS Edition 3 names)
SA4_GROUPS = {
    "QLD": {
        "Brisbane": ["Brisbane - East", "Brisbane - North", "Brisbane - South", "Brisbane - West",
                     "Brisbane Inner City", "Ipswich", "Logan - Beaudesert",
                     "Moreton Bay - North", "Moreton Bay - South"],
        "Coasts": ["Gold Coast", "Sunshine Coast"],
        "Wide Bay-Darling Downs": ["Wide Bay", "Toowoomba", "Darling Downs - Maranoa"],
        "Central": ["Central Queensland", "Mackay - Isaac - Whitsunday"],
        "North": ["Townsville", "Cairns", "Queensland - Outback"],
    },
    "SA": {
        "Adelaide North": ["Adelaide - North"],
        "Adelaide South": ["Adelaide - South"],
        "Adelaide Central/West": ["Adelaide - Central and Hills", "Adelaide - West"],
        "Country North & West": ["Barossa - Yorke - Mid North", "South Australia - Outback"],
        "South East": ["South Australia - South East"],
    },
    "WA": {
        "Perth North": ["Perth - Inner", "Perth - North East", "Perth - North West"],
        "Perth South": ["Perth - South East", "Perth - South West"],
        "Peel & South West": ["Mandurah", "Bunbury"],
        "Regional": ["Western Australia - Wheat Belt", "Western Australia - Outback (North)",
                     "Western Australia - Outback (South)"],
    },
}

# GCCSA variant: capital city SA4s vs the rest of the state (Mandurah is part of Greater Perth)
GCCSA_GROUPS = {
    "QLD": {"Greater Brisbane": SA4_GROUPS["QLD"]["Brisbane"]},
    "SA": {"Greater Adelaide": ["Adelaide - North", "Adelaide - South",
                                "Adelaide - Central and Hills", "Adelaide - West"]},
    "WA": {"Greater Perth": ["Perth - Inner", "Perth - North East", "Perth - North West",
                             "Perth - South East", "Perth - South West", "Mandurah"]},
}
REST_NAME = {"QLD": "Rest of Qld", "SA": "Rest of SA", "WA": "Rest of WA", "NSW": "Rest of NSW"}

SETTINGS = ([("A-current", None, 2.0)]
            + [(f"B-sa4-sd{sd}", "sa4", float(sd)) for sd in (1, 2, 3, 4)]
            + [(f"C-gccsa-sd{sd}", "gccsa", float(sd)) for sd in (2, 3)])

REGIONS_DIR = DATA_DIR / "benchmarks" / "regions"
OUT_CSV = ROOT / "predictions" / "benchmarking" / "region_experiment.csv"


def load_sa4s() -> dict[str, dict[str, District]]:
    """state -> SA4 name -> District, from the ABS ASGS Ed3 SA4 shapefile."""
    SA4_ZIP.parent.mkdir(parents=True, exist_ok=True)
    if not SA4_ZIP.exists():
        print(f"fetching {SA4_URL}")
        req = urllib.request.Request(SA4_URL, headers={"User-Agent": "VicElectionResearch/1.0"})
        SA4_ZIP.write_bytes(urllib.request.urlopen(req, timeout=120).read())
    zf = zipfile.ZipFile(SA4_ZIP)
    dbf = read_dbf(zf.read(next(n for n in zf.namelist() if n.endswith(".dbf"))))
    shp = read_shp_polygons(zf.read(next(n for n in zf.namelist() if n.endswith(".shp"))))
    out: dict[str, dict[str, District]] = {}
    for rec, rings in zip(dbf, shp):
        state = {"Queensland": "QLD", "South Australia": "SA", "New South Wales": "NSW",
                 "Western Australia": "WA"}.get(rec["STE_NAME21"])
        if state is None:
            continue
        name, polys = rec["SA4_NAME21"], shapefile_polygons(rings)
        if not polys:
            continue
        out.setdefault(state, {})[name] = District(name, "", polys, _bbox(polys))
    return out


def interior_point(d: District) -> tuple[float, float]:
    """A point inside the district polygon: grid search over its bbox, nearest the bbox centre."""
    x0, y0, x1, y1 = d.bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    best, best_d = None, float("inf")
    for i in range(51):
        for j in range(51):
            x, y = x0 + (x1 - x0) * i / 50, y0 + (y1 - y0) * j / 50
            if d.contains(x, y) and (x - cx) ** 2 + (y - cy) ** 2 < best_d:
                best, best_d = (x, y), (x - cx) ** 2 + (y - cy) ** 2
    if best is None:
        raise SystemExit(f"No interior sample point found in {d.name}")
    return best


def build_region_map(model1_run: str, sa4s: dict[str, dict[str, District]], groups: dict[str, list[str]],
                     capital: set[str] | None = None) -> dict[str, tuple[str, str, str, int]]:
    """district -> (group, sa4, basis, counted votes). Basis 'booths' or 'interior'."""
    bench = RUNS[model1_run]
    sa4_names = sa4s[bench.state]
    sa4_to_group = {}
    for g, names in groups.items():
        for n in names:
            if n not in sa4_names:
                raise SystemExit(f"SA4 name not in ABS file for {bench.state}: {n!r} "
                                 f"(have {sorted(sa4_names)})")
            sa4_to_group[n] = g
    def sa4_of(lon: float, lat: float) -> str:
        name, _ = assign_point(list(sa4_names.values()), lon, lat, max_km=1e9)
        return name if name else min(sa4_names.values(), key=lambda s: s.distance(lon, lat)).name

    def group_of(sa4: str) -> str:
        return sa4_to_group.get(sa4, REST_NAME[bench.state])

    districts = load_state_districts(bench.state, bench.state_election)
    divisions = fetch_national_divisions(FEDERAL_BOUNDARIES_DIR, bench.federal_year, states=(bench.state,))
    places = load_polling_places(bench.federal_dir / "general", bench.event, bench.state)
    booths, _ = load_booth_flows(bench.federal_dir / "house", bench.event, bench.state)
    assignment = assign_booths(places, districts, divisions)

    votes: dict[str, Counter] = {d.name: Counter() for d in districts}
    for pid, loc in assignment.items():
        if not loc.counted or pid not in booths:
            continue
        p = places[pid]
        votes[loc.district][sa4_of(float(p["Longitude"]), float(p["Latitude"]))] += booths[pid].total
    out = {}
    for d in districts:
        v = votes[d.name]
        if v:
            sa4, n = v.most_common(1)[0]
            out[d.name] = (group_of(sa4), sa4, "booths", n)
        else:
            x, y = interior_point(d)
            sa4 = sa4_of(x, y)
            out[d.name] = (group_of(sa4), sa4, "interior", 0)
    return out


def run_setting(run_id: str, region_map: dict[str, str] | None, sd: float, runs: int = 5000, seed: int = 1) -> dict:
    r = run_model2.RUNS[run_id]
    seats, flows_for, primaries, inputs = run_model2.setup(r)
    if region_map is not None and r.state != "VIC":
        by_norm = {norm_district(d): g for d, g in region_map.items()}
        for d, s in seats.items():
            if norm_district(d) in by_norm:
                s.region = by_norm[norm_district(d)]
            else:
                raise SystemExit(f"{run_id}: no region for district {d!r}")
    model2.NOISE["region_sd"] = sd
    try:
        sim = model2.simulate(seats, flows_for, primaries, runs=runs, seed=seed,
                              majority=len(seats) // 2 + 1, on_priors=True, exhaust=r.exhaust)
    finally:
        model2.NOISE["region_sd"] = 2.0
    tables = json.loads(r.distributions.read_text())
    # sum candidate p_win by party (same as load_forecast key='party')
    pf = {}
    for d in seats:
        agg = Counter()
        for c in sim["wins"][d]:
            party = next(x.party for x in seats[d].cands if x.cid == c)
            agg[party] += sim["wins"][d][c] / runs
        pf[d] = dict(agg)
    actual = run_model2.winners_for(r.winners, list(pf))
    sc = score(pf, actual)
    diag = run_model2.diagnostics(sim, tables, seats)
    t1 = run_model2.t1_mae(sim, seats, tables, on_polled=inputs["poll_on_reported"])
    missed = [d for d in pf if max(pf[d], key=pf[d].get) != actual[d]]
    miss_p = sum(pf[d].get(actual[d], 0.0) for d in missed) / len(missed) if missed else None
    return {"scores": sc, "diag": diag, "t1": t1, "missed": missed, "miss_p": miss_p,
            "forecast": pf, "actual": actual, "districts": len(seats)}


def _job(args):
    """Worker: one (setting, run) simulation; returns its result row and detail."""
    setting, run_id, rmap, sd = args
    res = run_setting(run_id, rmap, sd)
    row = {"setting": setting, "run": run_id,
           "seats_right": res["scores"]["raw_seat_count"], "districts": res["districts"],
           "accuracy": round(res["scores"]["raw_seat_count"] / res["districts"], 4),
           "brier": res["scores"]["brier"], "log_loss": res["scores"]["log_loss"],
           "final_two_acc": res["diag"]["final_two_accuracy"],
           "tcp_mae": res["diag"]["tcp_margin_mae"], "t1_mae": res["t1"],
           "missed": len(res["missed"]),
           "missed_winner_p": round(res["miss_p"], 4) if res["miss_p"] is not None else ""}
    return row, res


def main() -> None:
    sa4s = load_sa4s()
    for st, names in SA4_GROUPS.items():
        have = sa4s[st]
        for g, want in names.items():
            for n in want:
                assert n in have, (st, g, n)
    # per-state maps for the two regional variants (keyed by model2 run -> model1 run)
    maps = {}
    sizes = {}
    for run_id, m1 in F_RUNS.items():
        state = run_model2.RUNS[run_id].state
        if state == "VIC":
            continue
        for variant, groups in (("sa4", SA4_GROUPS[state]), ("gccsa", GCCSA_GROUPS[state])):
            rm = build_region_map(m1, sa4s, groups)
            maps[(run_id, variant)] = rm
            c = Counter(g for g, _, _, _ in rm.values())
            sizes[(run_id, variant)] = dict(sorted(c.items()))
            print(run_id, variant, sizes[(run_id, variant)])
            # write per-state map CSV (SA4 variant carries the SA4 name too)
    for run_id, m1 in F_RUNS.items():
        state = run_model2.RUNS[run_id].state
        if state == "VIC":
            continue
        for variant in ("sa4",):
            REGIONS_DIR.mkdir(parents=True, exist_ok=True)
            p = REGIONS_DIR / f"{state.lower()}_sa4_groups.csv"
            with p.open("w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["district", "region", "sa4", "basis", "counted_votes"])
                for d, (g, sa4, basis, n) in sorted(maps[(run_id, variant)].items()):
                    w.writerow([d, g, sa4, basis, n])

    tmp = tempfile.TemporaryDirectory(prefix="region_exp_")
    print("outputs ->", tmp.name, flush=True)
    simple_maps = {k: {d: v[0] for d, v in rm.items()} for k, rm in maps.items()}
    jobs = [(setting, run_id,
             None if variant is None or run_model2.RUNS[run_id].state == "VIC"
             else simple_maps[(run_id, variant)], sd)
            for setting, variant, sd in SETTINGS for run_id in F_RUNS]
    rows = []
    detail: dict[tuple[str, str], dict] = {}
    with Pool(8) as pool:
        for row, res in pool.imap_unordered(_job, jobs):
            detail[(row["setting"], row["run"])] = res
            rows.append(row)
            print(json.dumps(row), flush=True)
            with (Path(tmp.name) / f"{row['setting']}__{row['run']}.csv".replace(" ", "_").replace("/", "-")).open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["district", "party", "p_win"])
                for d, pr in res["forecast"].items():
                    for p, v in pr.items():
                        w.writerow([d, p, round(v, 4)])
    rows.sort(key=lambda r: ([x[0] for x in SETTINGS].index(r["setting"]),
                             list(F_RUNS).index(r["run"])))
    for setting, variant, sd in SETTINGS:
        # per-setting mean row
        sub = [r for r in rows if r["setting"] == setting]
        mean = {"setting": setting, "run": "MEAN",
                "seats_right": round(sum(r["seats_right"] for r in sub) / len(sub), 2),
                "districts": "",
                "accuracy": round(sum(r["accuracy"] for r in sub) / len(sub), 4),
                "brier": round(sum(r["brier"] for r in sub) / len(sub), 4),
                "log_loss": round(sum(r["log_loss"] for r in sub) / len(sub), 4),
                "final_two_acc": round(sum(r["final_two_acc"] for r in sub) / len(sub), 4),
                "tcp_mae": round(sum(r["tcp_mae"] for r in sub) / len(sub), 2),
                "t1_mae": round(sum(r["t1_mae"] for r in sub) / len(sub), 2),
                "missed": "", "missed_winner_p": ""}
        rows.append(mean)
        print("MEAN", json.dumps(mean))

    cols = ["setting", "run", "seats_right", "districts", "accuracy", "brier", "log_loss",
            "final_two_acc", "tcp_mae", "t1_mae", "missed", "missed_winner_p"]
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print("wrote", OUT_CSV)

    # regression check: setting A must equal the published scores.json
    for run_id in F_RUNS:
        pub = json.loads((ROOT / "predictions" / "modelling" / "model2" / "output" / run_id / "scores.json").read_text())
        got = detail[("A-current", run_id)]
        for k in ("raw_seat_count", "brier", "log_loss", "final_two_accuracy"):
            want = pub[k] if k in pub else pub.get(k)
            have = got["scores"].get(k, got["diag"].get(k))
            print("A-check", run_id, k, "published", want, "got", have, "OK" if want == have else "MISMATCH")


if __name__ == "__main__":
    main()
