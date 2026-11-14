#!/usr/bin/env python3
"""
Model 1 ("nothing changes"): replay each state district's preferential count from a federal election's
polling-place votes and preferences, unchanged. See predictions/modelling/model1/README.md.

  .venv/bin/python predictions/modelling/model1/run_model1.py "VIC2022 (2022)"   # one run
  .venv/bin/python predictions/modelling/model1/run_model1.py --all            # every run in config.RUNS

Writes the standard outputs to predictions/modelling/model1/output/<run_id>/ and scores runs whose
election has happened (metrics: predictions/benchmarking/README.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import model1  # sibling module in predictions/modelling/model1/
from vic_election.benchmark import align_districts, bloc_seats, load_forecast, load_winners, load_winners_csv, score
from vic_election.booth_flows import LABELS, OWN_DIVISION_TOLERANCE_KM, assign_booths, load_booth_flows, load_candidates, load_polling_places
from vic_election.config import FEDERAL_BOUNDARIES_DIR, MODELS_DIR, ROOT, RUNS, WINNERS_DIR, BenchmarkRun, majority_of, vec_distributions_path
from vic_election.geo import fetch_national_divisions, load_state_districts

MODEL = "model1"
OUTPUT_DIR = MODELS_DIR / MODEL / "output"
# Runs whose state candidates are known: federal votes are restricted to the parties actually standing
FIELDS = {"VIC2026 (2025)": ROOT / "data" / "2026" / "candidates_vic2026.csv"}  # scripts/fetch_vic2026_candidates.py
SHARE_DECIMALS = 2
PROBABILITY_DECIMALS = 4


def winners_for(source: str) -> dict[str, str]:
    if source.startswith("vec:"):
        return load_winners(vec_distributions_path(int(source.split(":")[1])))
    return load_winners_csv(WINNERS_DIR / f"{source}.csv")


def git_commit() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT)
    return result.stdout.strip() or None


def input_manifest(run: BenchmarkRun) -> dict | None:
    """Provenance of the AEC download feeding the run: when it was retrieved and what it contained."""
    path = run.federal_dir / "manifest.json"
    if not path.exists():
        return None
    m = json.loads(path.read_text(encoding="utf-8"))
    return {k: m.get(k) for k in ("source", "retrieved", "file_count", "total_bytes")}


def write_seat_probabilities(path: Path, primaries: dict, sim: dict) -> None:
    runs = sim["runs"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "candidate", "party", "p_win", "p_final_two", "tcp_p10", "tcp_p50", "tcp_p90"])
        for d in sorted(primaries):
            for p in sorted(primaries[d], key=lambda p: -primaries[d][p]):
                q = model1.percentiles(sim["tcp"][d].get(p, []))
                tcp = ("",) * 3 if q is None else tuple(round(x, SHARE_DECIMALS) for x in q)
                p_win = round(sim["wins"][d][p] / runs, PROBABILITY_DECIMALS)
                p_final_two = round(sim["final_two"][d][p] / runs, PROBABILITY_DECIMALS)
                w.writerow([d, LABELS.get(p, p), p, p_win, p_final_two, *tcp])


def write_statewide_seats(path: Path, sim: dict, majority: int, seats: dict | None = None) -> None:
    """One row per party (or per bloc, if `seats` is given, e.g. bloc_seats(sim["seats"]))."""
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["party", "seats_mean", "seats_p10", "seats_p50", "seats_p90", "p_majority"])
        for p, s in sorted((seats or sim["seats"]).items(), key=lambda kv: -sum(kv[1])):
            if any(s):
                p_majority = round(sum(x >= majority for x in s) / len(s), PROBABILITY_DECIMALS)
                w.writerow([p, round(sum(s) / len(s), 2), *(round(x, 1) for x in model1.percentiles(s)), p_majority])


def write_district_primaries(path: Path, primaries: dict) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "party", "votes", "share"])
        for d in sorted(primaries):
            total = sum(primaries[d].values())
            for p, v in primaries[d].most_common():
                w.writerow([d, p, v, round(100 * v / total, SHARE_DECIMALS)])


def load_field(path: Path) -> tuple[dict[str, set[str]], dict[str, dict[str, list[str]]]]:
    """district -> standing party groups, and district -> party group -> candidate names."""
    groups: dict[str, set[str]] = {}
    names: dict[str, dict[str, list[str]]] = {}
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            groups.setdefault(r["district"], set()).add(r["party_group"])
            names.setdefault(r["district"], {}).setdefault(r["party_group"], []).append(r["candidate"])
    return groups, names


def district_counts(primaries: dict, sim: dict, weights: dict, names: dict | None, notes: dict | None) -> dict:
    """Per district, for the visualiser: party chances, the noise-free count stage by stage, likely final pairs."""
    runs, out = sim["runs"], {}
    for d, prim in primaries.items():
        total = sum(prim.values())
        central = model1.central_count(prim, weights)
        label = lambda p: "; ".join((names or {}).get(d, {}).get(p, [])) or LABELS.get(p, p)  # noqa: E731
        pairs = []
        for (a, b), shares in sorted(sim["pair_tcp"][d].items(), key=lambda kv: -len(kv[1]))[:3]:
            q = model1.percentiles(shares)
            pairs.append({"p": round(len(shares) / runs, 4), "a": a, "b": b, "a_tcp": [round(x, 2) for x in q],
                          "b_tcp": [round(100 - x, 2) for x in reversed(q)], "p_a_wins": round(sum(s > 50 for s in shares) / len(shares), 4)})
        r2 = lambda x: round(x, 2)  # noqa: E731
        out[d] = {
            "candidates": [{"id": p, "name": label(p), "party": p, "primary": r2(100 * prim[p] / total), "core": True,
                            "p_win": round(sim["wins"][d][p] / runs, 4), "p_final_two": round(sim["final_two"][d][p] / runs, 4)}
                           for p in sorted(prim, key=lambda p: -prim[p]) if prim[p] > 0],
            "central": {"winner": central["winner"], "final": {k: r2(v) for k, v in central["final"].items()},
                        "stages": [{"excluded": s["excluded"], "pile": r2(s["pile"]), "transfers": {k: r2(v) for k, v in s["transfers"].items()},
                                    "totals": {k: r2(v) for k, v in s["totals"].items()}} for s in central["stages"]]},
            "pairs": pairs,
            "orders": [{"order": list(o), "p": round(n / runs, 4)} for o, n in sim["order"][d].most_common(5)],
            "field": (notes or {}).get(d),
        }
    return out


def run(run_id: str, runs: int, seed: int, noise: dict[str, float]) -> dict:
    bench = RUNS[run_id]
    districts = load_state_districts(bench.state, bench.state_election)
    divisions = fetch_national_divisions(FEDERAL_BOUNDARIES_DIR, bench.federal_year, states=(bench.state,))
    candidates = load_candidates(bench.federal_dir / "house", bench.event)
    booths, declaration = load_booth_flows(bench.federal_dir / "house", bench.event, bench.state)
    assignment = assign_booths(load_polling_places(bench.federal_dir / "general", bench.event, bench.state), districts, divisions)

    primaries = model1.district_primaries(booths, candidates, assignment)
    missing = [d.name for d in districts if d.name not in primaries]
    if missing:
        raise SystemExit(f"{run_id}: no counted polling place in {missing}")
    weights = model1.preference_weights([*booths.values(), *declaration.values()], candidates)
    majority = majority_of(len(districts))
    federal = primaries  # district_primaries.csv stays the raw federal vote (model2 reads One Nation's pattern from it)
    names = notes = None
    if run_id in FIELDS:
        if not FIELDS[run_id].exists():
            raise SystemExit(f"Needs {FIELDS[run_id].relative_to(ROOT)}: run scripts/fetch_vic2026_candidates.py")
        field, names = load_field(FIELDS[run_id])
        primaries, notes = model1.apply_state_field(primaries, field, weights)
    sim = model1.simulate(primaries, weights, runs=runs, seed=seed, noise=noise)

    out = OUTPUT_DIR / run_id
    out.mkdir(parents=True, exist_ok=True)
    write_seat_probabilities(out / "seat_probabilities.csv", primaries, sim)
    write_statewide_seats(out / "statewide_seats.csv", sim, majority)
    write_statewide_seats(out / "statewide_blocs.csv", sim, majority, bloc_seats(sim["seats"]))  # Liberals + Nationals as one Coalition
    write_district_primaries(out / "district_primaries.csv", federal)
    if names is not None:
        write_district_primaries(out / "field_primaries.csv", primaries)
    (out / "district_counts.json").write_text(json.dumps(district_counts(primaries, sim, weights, names, notes), separators=(",", ":")), encoding="utf-8")

    meta = {
        "model": MODEL, "run_id": run_id, "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(), "runs": runs, "seed": seed, "noise_log_sd": noise,
        "inputs": {
            "state": bench.state, "state_election": bench.state_election, "districts": len(districts),
            "federal_election": bench.federal_year, "aec_event": bench.event, "aec_download": input_manifest(bench),
            "booths": f"inside the district and within {OWN_DIVISION_TOLERANCE_KM} km of their own federal division",
            "polls": None, "winners": bench.winners,
            "state_field": str(FIELDS[run_id].relative_to(ROOT)) if run_id in FIELDS else None,
        },
    }
    if bench.winners:
        forecast = load_forecast(out / "seat_probabilities.csv")
        actual = align_districts(winners_for(bench.winners), list(forecast))
        meta["scores"] = score(forecast, actual)
        meta["actual_seats"] = {p: list(actual.values()).count(p) for p in sorted(set(actual.values()))}
        (out / "scores.json").write_text(json.dumps(meta["scores"], indent=2), encoding="utf-8")
    meta["predicted_seats_mean"] = {p: round(sum(s) / len(s), 2) for p, s in sim["seats"].items() if any(s)}
    (out / "run_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    parser = argparse.ArgumentParser(description="Model 1: 'nothing changes' federal-booth replay")
    parser.add_argument("run_ids", nargs="*", help="Runs to execute, e.g. \"VIC2022 (2022)\" (see vic_election.config.RUNS)")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--runs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=1)
    for key, default in model1.NOISE.items():
        parser.add_argument(f"--noise-{key}", type=float, default=default, help=f"log-sd of the {key} factor (default %(default)s)")
    args = parser.parse_args()
    noise = {key: getattr(args, f"noise_{key}") for key in model1.NOISE}
    unknown = [r for r in args.run_ids if r not in RUNS]
    if unknown:
        raise SystemExit(f"Unknown run(s) {unknown}; choose from {list(RUNS)}")
    for run_id in (list(RUNS) if args.all else args.run_ids):
        meta = run(run_id, args.runs, args.seed, noise)
        s = meta.get("scores")
        seats = ", ".join(f"{p} {v:.1f}" for p, v in sorted(meta["predicted_seats_mean"].items(), key=lambda kv: -kv[1]))
        print(f"{run_id}: {seats}" + (f" | {s['raw_seat_count']}/{s['districts']}, Brier {s['brier']}, log loss {s['log_loss']}" if s else ""))


if __name__ == "__main__":
    main()
