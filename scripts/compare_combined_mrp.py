#!/usr/bin/env python3
"""Equal-weight YouGov + RedBridge regional pattern, scaled to current polling.

Each MRP is aggregated to Council regions and calibrated to the same midyear
polling average (removing differences in their statewide levels). The two
calibrated regional tables are averaged 50/50, then calibrated to current
polling. Run extract_yougov_mrp.py first and fetch the RedBridge table into
data/2026/raw/mrp/redbridge_afr_primaries.tsv (see data/2026/MRP.md).
"""
import csv
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "predictions/modelling/model2"), str(ROOT / "scripts")]
from model2 import bloc, poll_average
from compare_yougov_mrp import CATS, calibrate

RAW = ROOT / "data/2026/raw/mrp"


def yougov():
    out = {}
    for r in csv.DictReader((RAW / "yougov_primaries.csv").open()):
        p = {c: float(r[c]) for c in CATS if c != "OTH"}
        p["OTH"] = sum(float(r[c]) for c in ("IND", "OTHER_LEFT", "OTHER_RIGHT"))
        out[r["district"]] = p
    return out


def redbridge():
    cols = {"ALP": "FP: Labor", "LNP": "FP: Coalition", "GRN": "FP: Greens", "ON": "FP: One Nation"}
    out = {}
    for r in csv.DictReader((RAW / "redbridge_afr_primaries.tsv").open(), delimiter="\t"):
        if not r["FP: Labor"]:
            continue  # article section headings
        p = {c: float(r[k]) for c, k in cols.items()}
        p["OTH"] = 100 - sum(p.values())
        assert p["OTH"] >= 0, r["District"]
        out[r["District"]] = p
    return out


def main():
    geo = json.loads((ROOT / "data/boundaries/vic_assembly_2022/districts.geojson").read_text())
    region_of = {f["properties"]["district"]: f["properties"]["region"] for f in geo["features"]}
    weight = {d: t["formal_votes"] for d, t in
              json.loads((ROOT / "data/2022/distributions/official_2022.json").read_text()).items()}
    sources = {"yougov": yougov(), "redbridge": redbridge()}
    for name, rows in sources.items():
        assert set(rows) == set(region_of), f"{name}: district mismatch"

    def regional(rows):
        t = defaultdict(lambda: dict.fromkeys(CATS, 0.0))
        for d, p in rows.items():
            z = sum(p.values())
            for c in CATS:
                t[region_of[d]][c] += weight[d] * p[c] / z
        return t

    totals = defaultdict(float)
    for d in region_of:
        totals[region_of[d]] += weight[d]
    model_json = json.loads((ROOT / "site/data/model2_vic2026.json").read_text())
    model = defaultdict(lambda: dict.fromkeys(CATS, 0.0))
    for d, info in model_json["districts"].items():
        z = sum(c["primary"] for c in info["candidates"])
        for c in info["candidates"]:
            model[region_of[d]][bloc(c["party"])] += weight[d] * c["primary"] / z

    polls = list(csv.DictReader((ROOT / "data/2026/polls_vic2026.csv").open()))
    exclude = {"redbridge-2026-07-trades-hall", "redbridge-accent-2026-06-afr"}
    midyear = poll_average([r for r in polls if r["id"] not in exclude], as_of="2026-07-12")
    current = poll_average(polls)

    mid = {n: calibrate(regional(rows), midyear) for n, rows in sources.items()}
    combined = {r: {c: (mid["yougov"][r][c] + mid["redbridge"][r][c]) / 2 for c in CATS} for r in totals}
    updated = calibrate(combined, current)
    per_source_now = {n: calibrate(t, current) for n, t in mid.items()}
    comparable = calibrate(model, current)

    share = lambda table, r, c: 100 * table[r][c] / totals[r]
    records = []
    for r in sorted(totals):
        for c in CATS:
            records.append({
                "region": r, "party": c,
                "yougov_current": round(share(per_source_now["yougov"], r, c), 4),
                "redbridge_current": round(share(per_source_now["redbridge"], r, c), 4),
                "combined_current": round(share(updated, r, c), 4),
                "model_current_common_target": round(share(comparable, r, c), 4),
                "difference_pp": round(share(updated, r, c) - share(comparable, r, c), 4),
                "source_gap_pp": round(share(per_source_now["yougov"], r, c) - share(per_source_now["redbridge"], r, c), 4),
            })
    out = ROOT / "predictions/benchmarking/mrp_combined_regional_comparison.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(records[0]))
        w.writeheader()
        w.writerows(records)
    meta = {"sources": {"yougov": "Common Threads report, 16 Jun-10 Jul 2026, n=4,003",
                        "redbridge": "Trades Hall MRP via AFR Datawrapper NunPy/2, Jun-Jul 2026, n~6,500; Others = 100 - four parties"},
            "weights": {"yougov": 0.5, "redbridge": 0.5},
            "district_weight": "2022 formal votes", "midyear": midyear, "current": current,
            "excluded_midyear_records": sorted(exclude),
            "method": "Each MRP aggregated to Council regions and raked to the same midyear statewide target; "
                      "regional tables averaged equally; result raked to current polling."}
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    print("Largest combined differences against the model at the same statewide target:")
    for x in sorted(records, key=lambda x: -abs(x["difference_pp"]))[:14]:
        print(f'{x["region"]}: {x["party"]} combined {x["combined_current"]:.1f}% (YouGov {x["yougov_current"]:.1f}, '
              f'RedBridge {x["redbridge_current"]:.1f}) vs model {x["model_current_common_target"]:.1f} ({x["difference_pp"]:+.1f} pp)')
    print("\nLargest YouGov vs RedBridge disagreements:")
    for x in sorted(records, key=lambda x: -abs(x["source_gap_pp"]))[:8]:
        print(f'{x["region"]}: {x["party"]} YouGov {x["yougov_current"]:.1f} vs RedBridge {x["redbridge_current"]:.1f} ({x["source_gap_pp"]:+.1f})')


if __name__ == "__main__":
    main()
