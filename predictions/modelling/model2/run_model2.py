#!/usr/bin/env python3
"""
Model 2 (core-candidate heuristic). See predictions/modelling/model2/README.md.

  .venv/bin/python predictions/modelling/model2/run_model2.py --all                    # every run
  .venv/bin/python predictions/modelling/model2/run_model2.py "QLD2024 (F)" --runs 20000

Runs (the bracket names the data the run starts from):
  <STATEyyyy> (F)   forecast backtest: previous-election baseline and flows, final-poll target
  VIC2026 (2022)    2026 forecast: 2022 primaries swung to the 2026 polling average

Writes the standard outputs to predictions/modelling/model2/output/<run_id>/ plus core_stage.csv,
and scores runs whose election has happened (predictions/benchmarking/README.md).
"""
from __future__ import annotations

import argparse
import dataclasses
import csv
import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import re

import model2  # sibling module in predictions/modelling/model2/
from vic_election.benchmark import align_districts, bloc_seats, load_forecast, load_winners, load_winners_csv, norm_district, party_group, score
import vic_election.polls as vic_polls
from vic_election.config import DATA_DIR, WINNERS_DIR
from vic_election.geo import districts_from_geojson

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
VEC_2022 = DATA_DIR / "2022" / "distributions"
POLLS = DATA_DIR / "2026" / "polls_vic2026.csv"
INDEPENDENTS = DATA_DIR / "2026" / "independents_vic2026.csv"
CANDIDATES = DATA_DIR / "2026" / "candidates_vic2026.csv"  # scripts/fetch_vic2026_candidates.py
ON_PATTERN = ROOT / "predictions" / "modelling" / "model1" / "output" / "VIC2026 (2025)" / "district_primaries.csv"
MODEL1_OUTPUT = ROOT / "predictions" / "modelling" / "model1" / "output"
FINAL_POLLS = DATA_DIR / "benchmarks" / "polls" / "final_polls.csv"
OFFICIAL_2018 = DATA_DIR / "2018" / "distributions" / "official_2018.json"
NOTIONAL_2018 = DATA_DIR / "2018" / "notional_2022_boundaries.json"


@dataclass(frozen=True)
class Run:
    mode: str  # "forecast" or "backtest"
    state: str
    election: str  # YYYY-MM-DD
    distributions: Path  # the SCORED election's distributions (backtest: read only for the candidate field and scoring)
    winners: str | None  # "vec:2022" or a data/benchmarks/winners/<stem>.csv
    exhaust: bool = False  # optional preferential voting (exhausted ballots leave the count)
    # backtest only: inputs that must all predate the scored election
    prev_distributions: Path | None = None  # flows are fitted on these only
    notional: Path | None = None  # baseline primaries (else the previous election's own primaries)
    prev_tables_for_inds: Path | None = None  # previous-election tables for the independent-credibility rule
    on_pattern: Path | None = None  # model1 district_primaries.csv for One Nation's seat pattern
    poll_election: str | None = None  # key into data/benchmarks/polls/final_polls.csv


def _state(run: str) -> Path:
    return DATA_DIR / run / "distributions" / f"dop_{run}.json"


RUNS = {
    "VIC2026 (2022)": Run("forecast", "VIC", "2026-11-28", VEC_2022 / "full_2cp_2022.json", None),
    # backtests: model2 forecasts a PAST election exactly as it forecasts VIC2026 — baseline = previous
    # election, flows fitted on the previous election's distributions only, poll target = final polls
    "VIC2022 (F)": Run("backtest", "VIC", "2022-11-26", VEC_2022 / "official_2022.json", "vec:2022",
                       prev_distributions=OFFICIAL_2018, notional=NOTIONAL_2018,
                       prev_tables_for_inds=OFFICIAL_2018, poll_election="VIC2022",
                       on_pattern=MODEL1_OUTPUT / "VIC2022 (2022)" / "district_primaries.csv"),
    "QLD2024 (F)": Run("backtest", "QLD", "2024-10-26", _state("QLD2024"), "QLD2024",
                       prev_distributions=_state("QLD2020"), prev_tables_for_inds=_state("QLD2020"),
                       poll_election="QLD2024",
                       on_pattern=MODEL1_OUTPUT / "QLD2024 (2022)" / "district_primaries.csv"),
    "NSW2023 (F)": Run("backtest", "NSW", "2023-03-25", _state("NSW2023"), "NSW2023",
                       exhaust=True,
                       prev_distributions=_state("NSW2019"), prev_tables_for_inds=_state("NSW2019"),
                       notional=DATA_DIR / "NSW2019" / "notional_NSW2023_boundaries.json",
                       poll_election="NSW2023",
                       on_pattern=MODEL1_OUTPUT / "NSW2023 (2022)" / "district_primaries.csv"),
    "WA2025 (F)": Run("backtest", "WA", "2025-03-08", _state("WA2025"), "WA2025",
                      prev_distributions=_state("WA2021"), prev_tables_for_inds=_state("WA2021"),
                      notional=DATA_DIR / "WA2021" / "notional_WA2025_boundaries.json",
                      poll_election="WA2025",
                      on_pattern=MODEL1_OUTPUT / "WA2025 (2022)" / "district_primaries.csv"),
    "SA2026 (F)": Run("backtest", "SA", "2026-03-21", _state("SA2026"), "SA2026",
                      prev_distributions=_state("SA2022"), prev_tables_for_inds=_state("SA2022"),
                      notional=DATA_DIR / "SA2022" / "notional_SA2026_boundaries.json",
                      poll_election="SA2026",
                      on_pattern=MODEL1_OUTPUT / "SA2026 (2025)" / "district_primaries.csv"),
}


def regions() -> dict[str, str]:
    gj = json.loads((DATA_DIR / "boundaries" / "vic_assembly_2022" / "districts.geojson").read_text())
    return {d.name: d.region for d in districts_from_geojson(gj)}


REGIONS_DIR = DATA_DIR / "benchmarks" / "regions"  # data/benchmarks/regions/README.md documents the source


def state_regions(state: str) -> dict[str, str]:
    """Non-Victorian F runs take ABS ASGS Ed3 SA4 groups; VIC keeps its Legislative Council regions.
    Keyed by norm_district so Geoscape spellings ('Mackillop', 'Collie - Preston') match scored names."""
    if state == "VIC":
        return {norm_district(d): g for d, g in regions().items()}
    path = REGIONS_DIR / f"{state.lower()}_sa4_groups.csv"
    if not path.exists():
        raise SystemExit(f"Needs {path.relative_to(ROOT)}: run scripts/region_experiment.py to build the SA4 region maps")
    return {norm_district(r["district"]): r["region"] for r in read_csv(path)}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _norm_person(name: str) -> str:
    """Surname key for matching the same candidate across elections. Commissions format names differently
    ('CUPPER, Ali', 'Geoff BROCK', 'BROCK', 'MADEO - NMV', 'MCNAIR Reuben'), so only the surname is used:
    the part before a comma, otherwise the all-capitals words, after dropping any ' - PARTY' suffix."""
    name = name.split(" - ")[0]
    if "," in name:
        sur = name.split(",")[0]
    else:
        caps = [w for w in name.split() if len(w) > 1 and w.upper() == w]
        sur = " ".join(caps) or name
    return re.sub(r"[^a-z]", "", sur.lower())


def candidates_from_distributions(tables: dict) -> list[dict]:
    """Scored-election candidate list in candidates_vic2026.csv shape (nominations are public before
    polling day). Only names and parties are taken — no votes."""
    return [{"district": d, "candidate": c["candidate_id"], "party_group": party_group(c["party"]),
             "ballot_position": c.get("ballot_position", "")}
            for d, t in tables.items() for c in t["candidates"]]


def seats_from_notional(path: Path, regions_map: dict[str, str]) -> dict[str, model2.Seat]:
    """Baseline seats from notional_2022_boundaries.json ({district: {party group: votes}}): one
    pseudo-candidate per party group (independent identity lives only in the credibility list)."""
    data = json.loads(path.read_text())["districts"]
    return {d: model2.Seat(d, regions_map.get(norm_district(d), ""), [model2.Cand(p, p, float(v)) for p, v in parties.items()])
            for d, parties in data.items()}


def credible_independents(prev_tables: dict, candidates: list[dict], min_share: float = 10.0) -> list[dict]:
    """
    Mechanical independents list for backtests: an IND* candidate is credible if the same person won the
    seat as an independent at the previous election, or took at least `min_share`% of the primary there.
    Prior mean = that previous primary share (prior_sd blank -> the recontesting sd in baseline_2026).
    """
    prev = {}
    for d, t in prev_tables.items():
        party = {c["candidate_id"]: party_group(c["party"]) for c in t["candidates"]}
        total = sum(t["first_preferences"].values()) or 1
        shares = {_norm_person(c): 100 * v / total for c, v in t["first_preferences"].items() if party[c] == model2.IND}
        win = t.get("declared_winner") or (max(t["final_totals"], key=t["final_totals"].get) if t.get("final_totals") else None)
        prev[norm_district(d)] = {"shares": shares,
                                  "winner": _norm_person(win) if win and party.get(win) == model2.IND else None}
    rows = []
    for r in candidates:
        if r["party_group"] != model2.IND:
            continue
        p = prev.get(norm_district(r["district"]))
        if not p:
            continue
        n = _norm_person(r["candidate"])
        if p["winner"] == n or p["shares"].get(n, 0.0) >= min_share:
            rows.append({"district": r["district"], "candidate": r["candidate"], "credible": "Y",
                         "prior_mean": f"{p['shares'].get(n, 0.0):.2f}"})
    return rows


def backtest_polls(poll_rows: list[dict], base: model2.Baseline) -> dict[str, float]:
    """
    Poll target for a past election from its final_polls.csv rows: per-category mean (ON averaged only
    over rows that report it), OTH = the remainder. When ON was not polled its target is One Nation's
    statewide share in the baseline (pattern index placed on seats) and OTH takes the rest, floored at 0.
    """
    on_unpolled = None
    if not any(r.get("onp") not in (None, "") for r in poll_rows):
        on_by_d = {d: sum(v for cid, v in sh.items()
                         if {c.cid: c.party for c in base.seats[d].cands}.get(cid) == "ON")
                   for d, sh in base.shares.items()}
        on_unpolled = 100 * sum(base.weight[d] * v for d, v in on_by_d.items()) / \
            sum(base.weight[d] * sum(base.shares[d].values()) for d in base.shares)
    return vic_polls.final_poll_mean(poll_rows, on_unpolled)


def setup(r: Run, as_of=None):
    """Seats, flows_for(district), primaries(rng) and input metadata for a run."""
    if not r.distributions.exists():
        raise SystemExit(f"Needs {r.distributions.relative_to(ROOT)}: run scripts/fetch_state_dops.py")
    if r.mode == "backtest":
        # leakage guard: every model input must predate the scored election. The scored file supplies
        # only the candidate field (nominations were public) and, after simulation, the actual results.
        input_paths = [p for p in (r.prev_distributions, r.notional, r.prev_tables_for_inds,
                                   r.on_pattern, FINAL_POLLS) if p is not None]
        assert r.distributions not in input_paths, f"{r.election}: scored distributions would leak into the forecast"
        tables = json.loads(r.distributions.read_text())  # candidate field only
        prev_tables = json.loads(r.prev_distributions.read_text())
        assert prev_tables is not tables
        fit = model2.fit_flows(model2.flow_observations(prev_tables, exhaust=r.exhaust))
        seat_regions = state_regions(r.state)
        if r.notional:
            seats_prev = seats_from_notional(r.notional, seat_regions)
        else:
            seats_prev = model2.seats_from_vec(prev_tables, seat_regions)
        candidates = candidates_from_distributions(tables)
        canon = {norm_district(x["district"]): x["district"] for x in candidates}  # notional 'Mackillop'/'Collie-Preston' -> scored-election spelling
        seats_prev = {canon.get(norm_district(d), d): dataclasses.replace(s, district=canon.get(norm_district(d), d)) for d, s in seats_prev.items()}
        missing = sorted({x["district"] for x in candidates} - set(seats_prev))
        if missing:
            raise SystemExit(f"{r.election}: no baseline seats for {missing}")
        if not r.on_pattern.exists():
            raise SystemExit(f"Needs {r.on_pattern.relative_to(ROOT)}: run model1 first")
        on = {row["district"]: float(row["share"]) for row in read_csv(r.on_pattern) if row["party"] == "ON"}
        ind_rows = credible_independents(json.loads((r.prev_tables_for_inds or r.prev_distributions).read_text()), candidates)
        base = model2.baseline_2026(seats_prev, candidates, on, ind_rows)
        poll_rows = vic_polls.load_final_polls(r.poll_election)
        polls = backtest_polls(poll_rows, base)
        on_reported = any(x.get("onp") not in (None, "") for x in poll_rows)
        meta = {"primaries": (f"notional 2018 primaries on 2022 boundaries ({r.notional.relative_to(ROOT)})"
                              if r.notional else f"{r.prev_distributions.stem.removeprefix('dop_')} actual primaries"),
                "flows": f"previous election's distributions only ({r.prev_distributions.relative_to(ROOT)})",
                "polls": {k: round(v, 2) for k, v in polls.items()}, "poll_on_reported": on_reported,
                "poll_rows": [f"{x['pollster']} {x['fieldwork_end']}" for x in poll_rows],
                "polls_source": str(FINAL_POLLS.relative_to(ROOT)),
                "one_nation_pattern": f"{r.on_pattern} (federal booths, model1), elasticity {model2.ON_ELASTICITY}",
                "independents": {"rule": "won the seat as an independent at the previous election, or >=10% primary there",
                                 "credible": [f"{x['candidate']} ({x['district']}, {x['prior_mean']}%)" for x in ind_rows]},
                "candidates": f"candidate field of the scored election ({r.distributions.relative_to(ROOT)}), nominations public before polling day",
                "leakage_guard": "baseline, flows and poll target all predate the scored election; its distributions were read only for the candidate list and the final score"}
        return base.seats, lambda d: fit, lambda rng: model2.draw_primaries(base, polls, rng), meta
    tables = json.loads(r.distributions.read_text())
    seats = model2.seats_from_vec(tables, regions() if r.state == "VIC" else {})
    obs = model2.flow_observations(tables, exhaust=r.exhaust)
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
        st = model2.strength_fn(flows_for(d), model2.central_on_priors())
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


def t1_mae(sim: dict, seats, tables: dict, on_polled: bool) -> float:
    """Mean over districts of the mean |predicted - actual| primary share (pp) across the model3 poll
    categories. Predicted = mean simulated primary; actual = the scored election's first preferences."""
    cats = [c for c in ("ALP", "LNP", "GRN", "ON", "OTH") if c != "ON" or on_polled]
    errs = []
    for d, t in tables.items():
        if d not in seats:
            continue
        party = {c.cid: c.party for c in seats[d].cands}
        actual_party = {c["candidate_id"]: party_group(c["party"]) for c in t["candidates"]}
        prim, at = sim["mean_primary"][d], t["first_preferences"]
        z1, z2 = sum(prim.values()), sum(at.values()) or 1
        for c in cats:
            p = sum(v for cid, v in prim.items() if _cat_of(party[cid], on_polled) == c) / z1
            a = sum(v for cid, v in at.items() if _cat_of(actual_party.get(cid, cid), on_polled) == c) / z2
            errs.append(100 * abs(p - a))
    return round(sum(errs) / len(errs), 4)


def _cat_of(group: str, on_polled: bool) -> str:
    if group in ("LP", "NP", "LNP", "CLP", "LIB", "NAT"):
        return "LNP"
    if group in ("GRN",):
        return "GRN"
    if group in ("ON", "ONP", "PHON"):
        return "ON" if on_polled else "OTH"
    return "ALP" if group == "ALP" else "OTH"


def run(run_id: str, runs: int, seed: int, as_of=None, out_dir=None) -> dict:
    r = RUNS[run_id]
    seats, flows_for, primaries, inputs = setup(r, as_of=as_of)
    majority = len(seats) // 2 + 1
    sim = model2.simulate(seats, flows_for, primaries, runs=runs, seed=seed, majority=majority,
                          on_priors=True, exhaust=r.exhaust)
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
            "noise": model2.NOISE, "on_priors": model2.ON_PRIORS, "exhaust": r.exhaust,
            "core_rule": {"top": model2.CORE_TOP, "share": model2.CORE_SHARE},
            "inputs": {"state": r.state, "state_election": r.election, "districts": len(seats),
                       "baseline": "previous election" if r.mode == "backtest" else "VEC 2022 state election",
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
        if r.mode == "backtest":
            meta["diagnostics"]["t1_mae_pp"] = t1_mae(sim, seats, tables, on_polled=inputs["poll_on_reported"])
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
