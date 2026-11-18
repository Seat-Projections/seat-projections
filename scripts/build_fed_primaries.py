#!/usr/bin/env python3
"""
Federal baseline primaries for model2's `(fed<year>)` runs: model1's located federal booth
first preferences in each state district PLUS the votes model1 cannot place, spread by division.

model1's district_primaries.csv holds only votes at located polling places (inside a state
district and within tolerance of their own federal division). This script adds the rest:
each division's declaration votes (postal, absent, provisional, declaration pre-poll) and the
ordinary votes at booths the placement rule dropped, raked over the state districts with
iterative proportional fitting so each district keeps its own located party pattern while
each party keeps its division pool total. The unlocated pool is computed as each
candidate's AEC TotalVotes (HouseFirstPrefsByCandidateByVoteTypeDownload) minus their votes
at counted booths, so statewide party totals equal the official AEC totals exactly.

  .venv/bin/python scripts/build_fed_primaries.py            # all federal-baseline inputs
Writes predictions/modelling/model2/inputs/fed_primaries_<state><federal year>.csv.
"""
from __future__ import annotations

import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vic_election.aec import read_aec_csv
from vic_election.booth_flows import FIRST, assign_booths, load_booth_flows, load_candidates, load_polling_places
from vic_election.config import FEDERAL_BOUNDARIES_DIR, ROOT, RUNS
from vic_election.geo import fetch_national_divisions, load_state_districts

OUT_DIR = ROOT / "predictions" / "modelling" / "model2" / "inputs"
MODEL1_RUNS = ["VIC2022 (2022)", "NSW2023 (2022)", "QLD2024 (2022)", "WA2025 (2022)", "SA2026 (2025)", "VIC2026 (2025)"]


def rake_division(seed: dict[tuple[str, str], float], row_totals: dict[str, float],
                  col_totals: dict[str, float], iters: int = 200, tol: float = 0.01) -> dict[tuple[str, str], float]:
    """Iterative proportional fitting: allocate the unlocated pool so each district part keeps its
    located vote share (row margins) while each party keeps its pool votes (column margins).
    Parties with pool votes but a zero seed in a part get a 0.5-vote seed so they can take votes."""
    m = dict(seed)
    parts = [d for d in row_totals if row_totals[d] > 0]
    for g, v in col_totals.items():
        if v > 0:
            for d in parts:
                if m.get((d, g), 0) <= 0:
                    m[(d, g)] = 0.5
    for _ in range(iters):
        for d in parts:
            z = sum(m.get((d, g), 0.0) for g in col_totals)
            if z:
                for g in col_totals:
                    m[(d, g)] = m.get((d, g), 0.0) * row_totals[d] / z
        for g in col_totals:
            z = sum(m.get((d, g), 0.0) for d in parts)
            if z:
                for d in parts:
                    m[(d, g)] = m.get((d, g), 0.0) * col_totals[g] / z
        err = max(
            [abs(sum(m.get((d, g), 0.0) for g in col_totals) - row_totals[d]) for d in parts]
            + [abs(sum(m.get((d, g), 0.0) for d in parts) - col_totals[g]) for g in col_totals if col_totals[g] > 0])
        if err < tol:
            break
    return m


def build(run_id: str) -> dict:
    bench = RUNS[run_id]
    house = bench.federal_dir / "house"
    districts = load_state_districts(bench.state, bench.state_election)
    divisions = fetch_national_divisions(FEDERAL_BOUNDARIES_DIR, bench.federal_year, states=(bench.state,))
    candidates = load_candidates(house, bench.event)
    booths, _declaration = load_booth_flows(house, bench.event, bench.state)
    assignment = assign_booths(load_polling_places(bench.federal_dir / "general", bench.event, bench.state),
                               districts, divisions)

    dist_prim: dict[str, Counter] = defaultdict(Counter)     # located ordinary first prefs, as model1
    div_dist: dict[str, Counter] = defaultdict(Counter)      # division -> district -> located ordinary votes
    div_dist_grp: dict[str, dict[str, Counter]] = defaultdict(lambda: defaultdict(Counter))  # -> -> -> group votes
    div_cand: dict[str, Counter] = defaultdict(Counter)      # division -> candidate -> counted votes
    for pid, b in booths.items():
        loc = assignment.get(pid)
        if loc is None or not loc.counted:
            continue
        for (src, to), v in b.votes.items():
            cid = to if src == FIRST else src  # FIRST rows cover finalists; source rows cover the rest
            cand = candidates.get(cid)
            if cand is None:
                continue
            dist_prim[loc.district][cand.group] += v
            div_dist[b.division][loc.district] += v
            div_dist_grp[b.division][loc.district][cand.group] += v
            div_cand[b.division][cid] += v

    # official per-candidate totals: pool = everything not counted at a located booth
    vote_type = house / f"HouseFirstPrefsByCandidateByVoteTypeDownload-{bench.event}.csv"
    totals: dict[str, Counter] = defaultdict(Counter)
    decl_vt: dict[str, int] = defaultdict(int)
    for r in read_aec_csv(vote_type):
        if r["StateAb"] != bench.state or r["CandidateID"] not in candidates:
            continue  # 'Informal' pseudo-candidate row (id 999) is not a real candidate
        totals[r["DivisionNm"]][r["CandidateID"]] += int(r["TotalVotes"])
        decl_vt[r["DivisionNm"]] += sum(int(r[k]) for k in ("AbsentVotes", "ProvisionalVotes", "PostalVotes"))

    out: dict[str, Counter] = defaultdict(Counter)
    pool_all = counted_all = decl_spread = booth_spread = 0
    for d, parties in dist_prim.items():
        out[d].update(parties)
    for div, cands in totals.items():
        weights = div_dist.get(div, Counter())
        tw = sum(weights.values())
        if not tw:
            weights = Counter({d.name: 1.0 for d in districts})  # no located booths: spread uniformly
            tw = len(weights)
            print(f"  warning: {div} has no located ordinary votes; spread uniformly")
        pool_group: Counter = Counter()
        for cid, total in cands.items():
            pool = max(total - div_cand[div].get(cid, 0), 0)
            counted_all += min(total, div_cand[div].get(cid, 0))
            pool_all += pool
            pool_group[candidates[cid].group] += pool
        pool_total = sum(pool_group.values())
        seed = {(d, g): float(div_dist_grp[div][d][g]) for d in weights for g in pool_group}
        row_totals = {d: pool_total * w / tw for d, w in weights.items()}
        for (d, g), v in rake_division(seed, row_totals, dict(pool_group)).items():
            out[d][g] += v
        # split the pool into declaration vs uncounted-booth votes, approximately
        decl = min(decl_vt[div], sum(pool_group.values()))
        decl_spread += decl
        booth_spread += sum(pool_group.values()) - decl

    # conservation: statewide totals per party group must equal the AEC totals
    official: Counter = Counter()
    for div, cands in totals.items():
        for cid, v in cands.items():
            official[candidates[cid].group] += v
    ours: Counter = Counter()
    for parties in out.values():
        ours.update(parties)
    for g in set(official) | set(ours):
        assert abs(ours[g] - official[g]) < 1.0, f"{run_id}: {g} conserved {ours[g]:.0f} vs official {official[g]}"

    formal = sum(official.values())
    share = 100 * pool_all / formal
    print(f"{run_id}: located {100 * counted_all / formal:.1f}% | spread {pool_all} votes "
          f"({share:.1f}% of formal; ~{decl_spread} declaration, ~{booth_spread} unlocated booths)")

    path = OUT_DIR / f"fed_primaries_{bench.state}{bench.federal_year}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["district", "party", "votes", "share"])
        for d in sorted(out):
            z = sum(out[d].values())
            for p in sorted(out[d], key=lambda p: -out[d][p]):
                w.writerow([d, p, round(out[d][p]), round(100 * out[d][p] / z, 2)])
    print(f"  wrote {path.relative_to(ROOT)}")
    return {"run": run_id, "pool": pool_all, "formal": formal, "decl": decl_spread, "booths": booth_spread}


def main() -> None:
    ids = [a for a in sys.argv[1:] if not a.startswith("--")] or MODEL1_RUNS
    stats = [build(r) for r in ids]
    for s in stats:
        print(f"{s['run']}: spread share {100 * s['pool'] / s['formal']:.2f}% of formal votes")


if __name__ == "__main__":
    main()
