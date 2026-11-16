#!/usr/bin/env python3
"""
Model 2 (core-candidate heuristic). See predictions/modelling/model2/README.md.

  .venv/bin/python predictions/modelling/model2/run_model2.py --all                    # every run
  .venv/bin/python predictions/modelling/model2/run_model2.py "QLD2024 (B1)" --runs 20000

Runs (the bracket names the data the run starts from):
  <STATEyyyy> (B1)  replay: that election's actual primaries, flows fitted to its own distributions of
                    preferences without the scored district (leave-one-district-out)
  VIC2026 (2022)    2026 forecast: 2022 primaries swung to the 2026 polling average

Writes the standard outputs to predictions/modelling/model2/output/<run_id>/ plus core_stage.csv,
and scores runs whose election has happened (predictions/benchmarking/README.md).
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import model2  # sibling module in predictions/modelling/model2/
from vic_election.benchmark import align_districts, bloc_seats, load_forecast, load_winners, load_winners_csv, score
from vic_election.config import DATA_DIR, WINNERS_DIR
from vic_election.geo import districts_from_geojson

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
VEC_2022 = DATA_DIR / "2022" / "distributions"
POLLS = DATA_DIR / "2026" / "polls_vic2026.csv"
INDEPENDENTS = DATA_DIR / "2026" / "independents_vic2026.csv"
CANDIDATES = DATA_DIR / "2026" / "candidates_vic2026.csv"  # scripts/fetch_vic2026_candidates.py
ON_PATTERN = ROOT / "predictions" / "modelling" / "model1" / "output" / "VIC2026 (2025)" / "district_primaries.csv"


@dataclass(frozen=True)
class Run:
    mode: str  # "replay" or "forecast"
    state: str
    election: str  # YYYY-MM-DD
    distributions: Path  # parsed distributions of preferences (VEC tables or vic_election.state_dop output)
    winners: str | None  # "vec:2022" or a data/benchmarks/winners/<stem>.csv
    exhaust: bool = False  # optional preferential voting (exhausted ballots leave the count)


def _state(run: str) -> Path:
    return DATA_DIR / run / "distributions" / f"dop_{run}.json"


RUNS = {
    "QLD2020 (B1)": Run("replay", "QLD", "2020-10-31", _state("QLD2020"), "QLD2020"),
    "WA2021 (B1)": Run("replay", "WA", "2021-03-13", _state("WA2021"), "WA2021"),
    "SA2022 (B1)": Run("replay", "SA", "2022-03-19", _state("SA2022"), "SA2022"),
    "VIC2022 (B1)": Run("replay", "VIC", "2022-11-26", VEC_2022 / "full_2cp_2022.json", "vec:2022"),
    "NSW2023 (B1)": Run("replay", "NSW", "2023-03-25", _state("NSW2023"), "NSW2023", exhaust=True),
    "QLD2024 (B1)": Run("replay", "QLD", "2024-10-26", _state("QLD2024"), "QLD2024"),
    "WA2025 (B1)": Run("replay", "WA", "2025-03-08", _state("WA2025"), "WA2025"),
    "SA2026 (B1)": Run("replay", "SA", "2026-03-21", _state("SA2026"), "SA2026"),
    "VIC2026 (2022)": Run("forecast", "VIC", "2026-11-28", VEC_2022 / "full_2cp_2022.json", None),
}


def regions() -> dict[str, str]:
    gj = json.loads((DATA_DIR / "boundaries" / "vic_assembly_2022" / "districts.geojson").read_text())
    return {d.name: d.region for d in districts_from_geojson(gj)}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def setup(r: Run, as_of=None):
    """Seats, flows_for(district), primaries(rng) and input metadata for a run."""
    if not r.distributions.exists():
        raise SystemExit(f"Needs {r.distributions.relative_to(ROOT)}: run scripts/fetch_state_dops.py")
    tables = json.loads(r.distributions.read_text())
    seats = model2.seats_from_vec(tables, regions() if r.state == "VIC" else {})
    obs = model2.flow_observations(tables, exhaust=r.exhaust)
    if r.mode == "replay":
        fits = {d: model2.fit_flows(obs, exclude_district=d) for d in seats}
        shares = {d: {c.cid: c.votes for c in s.cands} for d, s in seats.items()}
        meta = {"primaries": f"actual {r.election[:4]} primaries", "flows": "that election's distributions of preferences, leave-one-district-out",
                "distributions": str(r.distributions.relative_to(ROOT))}
        return seats, fits.__getitem__, lambda rng: shares, meta
    if not ON_PATTERN.exists():
        raise SystemExit(f"Needs {ON_PATTERN.relative_to(ROOT)}: run model1 'VIC2026 (2025)' first")
    on = {row["district"]: float(row["share"]) for row in read_csv(ON_PATTERN) if row["party"] == "ON"}
    if not CANDIDATES.exists():
        raise SystemExit(f"Needs {CANDIDATES.relative_to(ROOT)}: run scripts/fetch_vic2026_candidates.py")
    base = model2.baseline_2026(seats, read_csv(CANDIDATES), on, read_csv(INDEPENDENTS))
    polls = model2.poll_average(read_csv(POLLS), as_of=as_of)
    fit = model2.fit_flows(obs)
    meta = {"primaries": "2022 VEC primaries, proportional swing to the 2026 polling average", "flows": "2022 VEC distributions (all districts)",
            "polls": {k: round(v, 2) for k, v in polls.items() if k != "_polls"}, "polls_used": polls["_polls"], "polls_source": "electiontracker.au/data/vic2026/polls.csv",
            "one_nation_pattern": "federal 2025 booth share per district (model1 'VIC2026 (2025)'), elasticity " + str(model2.ON_ELASTICITY),
            "independents": str(INDEPENDENTS.relative_to(ROOT)),
            "candidates": f"{CANDIDATES.relative_to(ROOT)} (VEC nominations, closed 9 Nov 2026)"}
    return base.seats, lambda d: fit, lambda rng: model2.draw_primaries(base, polls, rng), meta


def winners_for(source: str, districts: list[str]) -> dict[str, str]:
    if source.startswith("vec:"):
        year = source.split(":")[1]
        return load_winners(DATA_DIR / year / "distributions" / f"official_{year}.json")
    return align_districts(load_winners_csv(WINNERS_DIR / f"{source}.csv"), districts)


def diagnostics(sim: dict, tables: dict, seats) -> dict:
    """Final-two accuracy and 2CP error of the winner's median share where the final pair was right."""
    hits, errs = 0, []
    for d, t in tables.items():
        party = {c.cid: c.party for c in seats[d].cands}
        actual = tuple(sorted(party.get(c, "?") for c in t["final_totals"]))
        if sim["pair"][d] and sim["pair"][d].most_common(1)[0][0] == actual:
            hits += 1
            win = max(t["final_totals"], key=t["final_totals"].get)
            med = model2.percentiles(sim["tcp"][d].get(win, []))
            if med:
                errs.append(abs(med[1] - 100 * t["final_totals"][win] / sum(t["final_totals"].values())))
    return {"final_two_accuracy": round(hits / len(tables), 4), "tcp_margin_mae": round(sum(errs) / len(errs), 2) if errs else None}


def district_counts(sim: dict, seats, flows_for, r: Run, top: int = 5) -> dict:
    """
    Per district, for display: candidates with mean primary and probabilities; the central scenario's count
    stage by stage (mean primaries, central flows, every candidate excluded in turn); the most likely final
    pairs with each side's 2CP p10/p50/p90; and the most likely orders in which core candidates go out.
    """
    runs = sim["runs"]
    out = {}
    for d, seat in seats.items():
        party = {c.cid: c.party for c in seat.cands}
        prim = sim["mean_primary"][d]
        total = sum(prim.values())
        cands = [model2.Cand(c, party[c], 100 * v / total) for c, v in prim.items()]
        st = model2.strength_fn(flows_for(d), model2.central_on_priors() if r.mode == "forecast" else None)
        central = model2.central_count(cands, st, r.exhaust)
        rnd = lambda x: round(x, 2)  # noqa: E731
        pairs = []
        for (a, b), shares in sorted(sim["pair_tcp"][d].items(), key=lambda kv: -len(kv[1]))[:3]:
            qa = model2.percentiles(shares)
            pairs.append({"p": round(len(shares) / runs, 4), "a": a, "b": b,
                          "a_tcp": [rnd(x) for x in qa], "b_tcp": [rnd(100 - x) for x in reversed(qa)],
                          "p_a_wins": round(sum(s > 50 for s in shares) / len(shares), 4)})
        out[d] = {
            "candidates": [{"id": c, "party": party[c], "primary": rnd(100 * prim[c] / total), "core": c in sim["core"][d],
                            "p_win": round(sim["wins"][d][c] / runs, 4), "p_final_two": round(sim["final_two"][d][c] / runs, 4)}
                           for c in sorted(prim, key=lambda c: -prim[c])],
            "central": {"winner": central["winner"], "final": {k: rnd(v) for k, v in central["final"].items()},
                        "stages": [{"excluded": s["excluded"], "pile": rnd(s["pile"]), "transfers": {k: rnd(v) for k, v in s["transfers"].items()},
                                    "totals": {k: rnd(v) for k, v in s["totals"].items()}} for s in central["stages"]]},
            "pairs": pairs,
            "orders": [{"order": list(o), "p": round(n / runs, 4)} for o, n in sim["order"][d].most_common(top)],
        }
    return out


def run(run_id: str, runs: int, seed: int, as_of=None, out_dir=None) -> dict:
    r = RUNS[run_id]
    seats, flows_for, primaries, inputs = setup(r, as_of=as_of)
    majority = len(seats) // 2 + 1
    sim = model2.simulate(seats, flows_for, primaries, runs=runs, seed=seed, majority=majority,
                          on_priors=r.mode == "forecast", exhaust=r.exhaust)
    out = out_dir or HERE / "output" / run_id
    out.mkdir(parents=True, exist_ok=True)
    party = {d: {c.cid: c.party for c in s.cands} for d, s in seats.items()}

    with (out / "seat_probabilities.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "candidate", "party", "p_win", "p_final_two", "tcp_p10", "tcp_p50", "tcp_p90"])
        for d in sorted(seats):
            for c in sorted(sim["mean_primary"][d], key=lambda c: -sim["mean_primary"][d][c]):
                q = model2.percentiles(sim["tcp"][d].get(c, []))
                w.writerow([d, c, party[d][c], round(sim["wins"][d][c] / runs, 4), round(sim["final_two"][d][c] / runs, 4),
                            *(("",) * 3 if q is None else (round(x, 2) for x in q))])
    with (out / "core_stage.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "candidate", "party", "mean_primary", "core", "p_excluded_at_core"])
        for d in sorted(seats):
            prim = sim["mean_primary"][d]
            for c in sorted(prim, key=lambda c: -prim[c]):
                w.writerow([d, c, party[d][c], round(100 * prim[c] / sum(prim.values()), 2), int(c in sim["core"][d]),
                            round(sim["first_out"][d][c] / runs, 4)])
    # statewide_seats.csv: one row per party; statewide_blocs.csv: Liberals + Nationals as one Coalition (summed run by run)
    for name, seats_by in (("statewide_seats.csv", sim["seats"]), ("statewide_blocs.csv", bloc_seats(sim["seats"]))):
        with (out / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["party", "seats_mean", "seats_p10", "seats_p50", "seats_p90", "p_majority"])
            for p, s in sorted(seats_by.items(), key=lambda kv: -sum(kv[1])):
                if any(s):
                    w.writerow([p, round(sum(s) / len(s), 2), *(round(x, 1) for x in model2.percentiles(s)), round(sum(x >= majority for x in s) / len(s), 4)])

    (out / "district_counts.json").write_text(json.dumps(district_counts(sim, seats, flows_for, r), separators=(",", ":")), encoding="utf-8")

    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip() or None
    generated = datetime.now(timezone.utc)
    meta = {"model": "model2", "run_id": run_id,
            "timestamp": generated.isoformat(timespec="seconds"), "git_commit": commit, "runs": runs, "seed": seed,
            "noise": model2.NOISE, "on_priors": model2.ON_PRIORS if r.mode == "forecast" else None, "exhaust": r.exhaust,
            "core_rule": {"top": model2.CORE_TOP, "share": model2.CORE_SHARE},
            "inputs": {"state": r.state, "state_election": r.election, "districts": len(seats),
                       "baseline": f"{r.state} {r.election[:4]} actual primaries" if r.mode == "replay" else "VEC 2022 state election",
                       "federal_election": None, "winners": r.winners} | inputs}
    if as_of is not None:
        meta["as_of"] = as_of.isoformat()
        meta["generated"] = generated.date().isoformat()
        meta["poll_cutoff"] = "fieldwork ended at least 2 days before as_of"
        meta["retrospective"] = as_of < generated.date()
    if r.winners:
        tables = json.loads(r.distributions.read_text())
        forecast = load_forecast(out / "seat_probabilities.csv")
        actual = winners_for(r.winners, list(forecast))
        meta["scores"] = score(forecast, actual)
        meta["diagnostics"] = diagnostics(sim, tables, seats)
        meta["actual_seats"] = dict(sorted(Counter(actual.values()).items()))
        (out / "scores.json").write_text(json.dumps(meta["scores"] | meta["diagnostics"], indent=2), encoding="utf-8")
    meta["predicted_seats_mean"] = {p: round(sum(s) / len(s), 2) for p, s in sim["seats"].items() if any(s)}
    (out / "run_metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def snapshot_schedule(poll_rows, start: str = "2026-09-01", step_days: int = 14, today=None) -> list:
    """Dates every step_days from start through today; keep a date only if its
    poll set differs from the previous kept snapshot's (monthly when polls are slow)."""
    from datetime import date, timedelta
    today = today or date.today()
    d0 = date.fromisoformat(start)
    kept, prev = [], None
    d = d0
    while d <= today:
        try:
            pu = tuple(model2.poll_average(poll_rows, as_of=d)["_polls"])
        except ValueError:
            d += timedelta(days=step_days)
            continue
        if pu != prev:
            kept.append(d)
            prev = pu
        d += timedelta(days=step_days)
    return kept


SNAPSHOT_ROOT = HERE / "output" / "VIC2026 snapshots"


def main() -> None:
    parser = argparse.ArgumentParser(description="Model 2: core-candidate heuristic")
    parser.add_argument("run_ids", nargs="*", help=f"Runs: {list(RUNS)}")
    parser.add_argument("--all", action="store_true", help="every run")
    parser.add_argument("--runs", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--as-of", metavar="YYYY-MM-DD", help="forecast with polls as of this date (VIC2026 only)")
    parser.add_argument("--snapshots", action="store_true", help="run the VIC2026 forecast-history snapshot schedule")
    parser.add_argument("--force", action="store_true", help="overwrite existing snapshot dirs")
    args = parser.parse_args()
    if args.as_of or args.snapshots:
        from datetime import date
        poll_rows = read_csv(POLLS)
        dates = snapshot_schedule(poll_rows) if args.snapshots else [date.fromisoformat(args.as_of)]
        for d in dates:
            out_dir = SNAPSHOT_ROOT / d.isoformat()
            if out_dir.exists() and not args.force:
                print(f"{d}: snapshot exists, skipping (use --force)", flush=True)
                continue
            meta = run("VIC2026 (2022)", args.runs, args.seed, as_of=d, out_dir=out_dir)
            seats = ", ".join(f"{p} {v:.1f}" for p, v in sorted(meta["predicted_seats_mean"].items(), key=lambda kv: -kv[1]) if v >= 0.05)
            print(f"{d}: {seats}", flush=True)
        return
    unknown = [r for r in args.run_ids if r not in RUNS]
    if unknown:
        raise SystemExit(f"Unknown run(s) {unknown}; choose from {list(RUNS)}")
    for run_id in (list(RUNS) if args.all else args.run_ids):
        meta = run(run_id, args.runs, args.seed)
        s, dg = meta.get("scores"), meta.get("diagnostics")
        seats = ", ".join(f"{p} {v:.1f}" for p, v in sorted(meta["predicted_seats_mean"].items(), key=lambda kv: -kv[1]) if v >= 0.05)
        extra = f" | {s['raw_seat_count']}/{s['districts']}, Brier {s['brier']}, log loss {s['log_loss']}, final two {dg['final_two_accuracy']}, 2CP MAE {dg['tcp_margin_mae']}" if s else ""
        print(f"{run_id}: {seats}{extra}", flush=True)


if __name__ == "__main__":
    main()
