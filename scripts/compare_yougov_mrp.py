#!/usr/bin/env python3
"""Compare YouGov regional primary votes at midyear and current polling levels.

Run extract_yougov_mrp.py first. This analysis does not replace the published
forecast or use YouGov's preference flows or seat winners.
"""
import csv
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "predictions/modelling/model2")]
from model2 import bloc, poll_average

CATS = ("ALP", "LNP", "GRN", "ON", "OTH")


def calibrate(votes, target):
    """IPF: preserve regional vote totals, match statewide primary shares."""
    out = {r: dict(v) for r, v in votes.items()}
    totals = {r: sum(v.values()) for r, v in out.items()}
    total = sum(totals.values())
    for _ in range(1000):
        current = {c: sum(v[c] for v in out.values()) for c in CATS}
        if max(abs(100 * current[c] / total - target[c]) for c in CATS) < 1e-8:
            return out
        for c in CATS:
            factor = target[c] * total / (100 * current[c])
            for v in out.values():
                v[c] *= factor
        for r, v in out.items():
            factor = totals[r] / sum(v.values())
            for c in CATS:
                v[c] *= factor
    raise ValueError("Regional calibration did not converge")


def main():
    source = ROOT / "data/2026/raw/mrp/yougov_primaries.csv"
    rows = list(csv.DictReader(source.open()))
    official = json.loads((ROOT / "data/2022/distributions/official_2022.json").read_text())
    current_model = json.loads((ROOT / "site/data/model2_vic2026.json").read_text())
    assert len(rows) == 88 and {r["district"] for r in rows} == set(official)
    mrp, model = defaultdict(lambda: dict.fromkeys(CATS, 0.0)), defaultdict(lambda: dict.fromkeys(CATS, 0.0))
    totals = defaultdict(float)
    for row in rows:
        district, region = row["district"], row["region"]
        weight = official[district]["formal_votes"]
        p = {c: float(row[c]) for c in CATS if c != "OTH"}
        p["OTH"] = sum(float(row[c]) for c in ("IND", "OTHER_LEFT", "OTHER_RIGHT"))
        z = sum(p.values())  # source percentages rounded independently
        for c in CATS:
            mrp[region][c] += weight * p[c] / z
        candidates = current_model["districts"][district]["candidates"]
        z = sum(c["primary"] for c in candidates)
        for candidate in candidates:
            model[region][bloc(candidate["party"])] += weight * candidate["primary"] / z
        totals[region] += weight

    polls = list(csv.DictReader((ROOT / "data/2026/polls_vic2026.csv").open()))
    # Avoid using the MRP itself, or a potentially duplicate account of it,
    # as independent contemporaneous polling evidence.
    exclude = {"redbridge-2026-07-trades-hall", "redbridge-accent-2026-06-afr"}
    midyear = poll_average([r for r in polls if r["id"] not in exclude], as_of="2026-07-12")
    current = poll_average(polls)
    mid = calibrate(mrp, midyear)
    updated = calibrate(mid, current)
    # Put the existing model's geography on the identical statewide target.
    comparable = calibrate(model, current)
    direct = calibrate(mrp, current)
    assert max(abs(updated[r][c] - direct[r][c]) for r in updated for c in CATS) < 0.001
    records = []
    for region in sorted(updated):
        for c in CATS:
            share = lambda table: 100 * table[region][c] / totals[region]
            records.append({
                "region": region, "party": c,
                "yougov_raw": round(share(mrp), 4),
                "yougov_midyear": round(share(mid), 4),
                "yougov_current": round(share(updated), 4),
                "model_current_common_target": round(share(comparable), 4),
                "difference_pp": round(share(updated) - share(comparable), 4),
            })
    out = ROOT / "predictions/benchmarking/yougov_regional_comparison.csv"
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    meta = {
        "source": rows[0]["source_url"], "fieldwork": ["2026-06-16", "2026-07-10"],
        "district_weight": "2022 formal votes (proxy, not current enrolment)",
        "midyear_cutoff": "2026-07-12", "midyear": midyear, "current": current,
        "excluded_midyear_records": sorted(exclude),
        "method": "Normalise rounded seat primaries, aggregate to Council regions, "
                  "rake to midyear then current polling. Recalibrate published model "
                  "region shares to current polling for a like-for-like geography comparison.",
        "limitations": ["Old regional pattern assumed stable", "Midyear register may be incomplete",
                        "No MRP uncertainty draws available", "Not a seat forecast"],
    }
    out.with_suffix(".json").write_text(json.dumps(meta, indent=2) + "\n")
    print(json.dumps(meta, indent=2))
    print("\nLargest regional differences against the model at the same statewide target:")
    for r in sorted(records, key=lambda r: -abs(r["difference_pp"]))[:16]:
        print(f'{r["region"]}: {r["party"]} {r["yougov_current"]:.1f}% vs '
              f'{r["model_current_common_target"]:.1f}% ({r["difference_pp"]:+.1f} pp)')


if __name__ == "__main__":
    main()
