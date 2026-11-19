#!/usr/bin/env python3
"""Separate full-strength YouGov regional scenario. Does not rebuild the site.

Run compare_yougov_mrp.py first. Fixed region/category multipliers calibrate
the published mean district primaries to the updated YouGov regional shares.
Apply those same multipliers to each ordinary model draw, preserving random
draws and within-region relative support. All candidates, including independents
in Others, receive their category adjustment. Independent priors are drawn as
usual, but their final shares can change after the regional adjustment.
"""
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "predictions/modelling/model2")]
import model2
import run_model2 as runner

RUN = "VIC2026 (2022)"
VARIANTS = {
    "yougov": ("yougov_regional_comparison.csv", "yougov_current", "VIC2026 (YouGov regional)"),
    "combined": ("mrp_combined_regional_comparison.csv", "combined_current", "VIC2026 (MRP combined regional)"),
    "partial": ("mrp_combined_regional_comparison.csv", "combined_current", "VIC2026 (MRP partial regional)"),
    # Seat-level method used by The Tally Room/DemosAU/RedBridge: average the two MRPs' district
    # primaries, apply one uniform (additive) statewide swing per party group to reach current polling.
    "uniform": ("mrp_combined_regional_comparison.csv", "combined_current", "VIC2026 (MRP uniform swing)"),
}
# "partial": the MRP adjustment is shrunk and uncertain. Each simulation draws, per region and party
# group, the fraction of the full log-adjustment applied, lambda ~ N(PARTIAL_MEAN, PARTIAL_SD) clipped
# to [PARTIAL_MIN, 1], plus extra multiplicative regional noise exp(N(0, EXTRA_REGION_LOG_SD)).
PARTIAL_MEAN, PARTIAL_SD, PARTIAL_MIN = 0.3, 0.3, -0.3
EXTRA_REGION_LOG_SD = 0.06
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "yougov"
TABLE, COLUMN, RUN_NAME = VARIANTS[VARIANT]
OUT = ROOT / "predictions/modelling/model2/output" / RUN_NAME
CATS = tuple(model2.BLOCS)


def fit_factors(rows, weights, target):
    """Fit fixed category multipliers, preserving each district's total."""
    factors = dict.fromkeys(CATS, 1.0)
    total = sum(weights.values())
    for _ in range(1000):
        shares = dict.fromkeys(CATS, 0.0)
        for d, row in rows.items():
            z = sum(row[c] * factors[c] for c in CATS)
            for c in CATS:
                shares[c] += weights[d] * row[c] * factors[c] / z / total * 100
        if max(abs(shares[c] - target[c]) for c in CATS) < 1e-7:
            return factors
        for c in CATS:
            if shares[c] <= 0:
                raise ValueError(f"No support for requested category {c}")
            factors[c] *= target[c] / shares[c]
    raise ValueError("Regional factors failed to converge")


def uniform_swing_factors(seats, reference, weights, runner):
    """District multipliers turning the published mean primaries into MRP-average + uniform swing."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from compare_combined_mrp import redbridge, yougov
    from model2 import poll_average
    sources = [yougov(), redbridge()]
    avg = {}
    for d in seats:
        rows = [{c: v / sum(src[d].values()) * 100 for c, v in src[d].items()} for src in sources]
        avg[d] = {c: sum(r[c] for r in rows) / len(rows) for c in CATS}
    total = sum(weights[d] for d in seats)
    state = {c: sum(weights[d] * avg[d][c] for d in seats) / total for c in CATS}
    current = poll_average(list(csv.DictReader((ROOT / "data/2026/polls_vic2026.csv").open())))
    swing = {c: round(current[c] - state[c], 4) for c in CATS}
    factors = {}
    for d in seats:
        target = {c: max(avg[d][c] + swing[c], 0.5) for c in CATS}
        z = sum(target.values())
        target = {c: 100 * v / z for c, v in target.items()}
        ref = dict.fromkeys(CATS, 0.0)
        for cand in reference["districts"][d]["candidates"]:
            ref[model2.bloc(cand["party"])] += cand["primary"]
        zr = sum(ref.values())
        # categories with no candidate in the seat cannot receive votes; the rest renormalise
        factors[d] = {c: (target[c] / (100 * ref[c] / zr)) if ref[c] > 0 else 1.0 for c in CATS}
    return factors, swing


def scenario_setup(r, as_of=None):
    seats, flows, draw, meta = runner.setup(r, as_of=as_of)
    reference_path = ROOT / "site/data/model2_vic2026.json"
    reference = json.loads(reference_path.read_text())
    table_path = ROOT / "predictions/benchmarking" / TABLE
    targets = {}
    for row in csv.DictReader(table_path.open()):
        targets.setdefault(row["region"], {})[row["party"]] = float(row[COLUMN])
    weights = {d: t["formal_votes"] for d, t in
               json.loads((ROOT / "data/2022/distributions/official_2022.json").read_text()).items()}
    categories = {d: {c.cid: model2.bloc(c.party) for c in s.cands} for d, s in seats.items()}
    factors = {}
    for region, target in targets.items():
        target = {c: 100 * v / sum(target.values()) for c, v in target.items()}
        rows = {}
        for d, seat in seats.items():
            if seat.region != region:
                continue
            rows[d] = dict.fromkeys(CATS, 0.0)
            for c in reference["districts"][d]["candidates"]:
                rows[d][model2.bloc(c["party"])] += c["primary"]
        if not rows:
            raise ValueError(f"No seats for {region}")
        factors[region] = fit_factors(rows, {d: weights[d] for d in rows}, target)
    assert set(factors) == {s.region for s in seats.values()}
    district_factors, swing = None, None
    if VARIANT == "uniform":
        district_factors, swing = uniform_swing_factors(seats, reference, weights, runner)

    import math

    def adjusted(rng):
        draws = draw(rng)
        if VARIANT == "partial":
            used = {r: {c: math.exp(min(max(rng.gauss(PARTIAL_MEAN, PARTIAL_SD), PARTIAL_MIN), 1.0) * math.log(f[c])
                                    + rng.gauss(0, EXTRA_REGION_LOG_SD)) for c in CATS}
                    for r, f in sorted(factors.items())}
        else:
            used = factors
        for d, votes in draws.items():
            total = sum(votes.values())
            f = district_factors[d] if district_factors else used[seats[d].region]
            scaled = {cid: v * f[categories[d][cid]] for cid, v in votes.items()}
            z = sum(scaled.values())
            draws[d] = {cid: v * total / z for cid, v in scaled.items()}
        return draws

    strength = ("partial: lambda~N(%s,%s) clipped [%s,1] per region/party/draw, extra regional log-sd %s"
                % (PARTIAL_MEAN, PARTIAL_SD, PARTIAL_MIN, EXTRA_REGION_LOG_SD)) if VARIANT == "partial" else "full strength, no age discount"
    if VARIANT == "uniform":
        strength = "district level: 50/50 YouGov+RedBridge primaries plus a uniform statewide swing to current polls"
    meta = dict(meta, scenario=f"{VARIANT} MRP pattern, {strength}", uniform_swing_pp=swing,
                regional_factors=factors,
                regional_target_source=str(table_path.relative_to(ROOT)),
                reference_sha256=hashlib.sha256(reference_path.read_bytes()).hexdigest(),
                comparison_sha256=hashlib.sha256(table_path.read_bytes()).hexdigest(),
                regional_method="Fixed region/category multipliers applied to each draw, then "
                "renormalised per seat. Candidate ordering within each category retained. "
                "OTH adjustment includes independents. Regional targets are fitted to the "
                "reference mean, not forced on every random draw.",
                limitation="Old MRP pattern assumed stable. Existing noise retained, with no "
                "additional MRP estimation uncertainty. Not a calibrated improvement.")
    return seats, flows, adjusted, meta


if __name__ == "__main__":
    metadata = runner.run(RUN, 5000, 1, out_dir=OUT, setup_fn=scenario_setup)
    metadata["run_id"] = RUN_NAME
    (OUT / "run_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print((OUT / "statewide_blocs.csv").read_text())
