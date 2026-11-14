"""
Model 1 — "nothing changes" baseline.

Federal polling-place votes are added up inside each state district (the counted booths of
`booth_flows`), and the district's preferential count is replayed assuming voters behave exactly as they
did at that federal election: same parties, same first preferences, same preferences. Monte Carlo noise
around those inputs turns the single replay into seat probabilities.

Preferences: the AEC only publishes how each party's ballots split between the final two of each
division. From every such split statewide, a Bradley-Terry strength is fitted for each (from-party,
to-party) pair; when a party is excluded its votes go to the continuing parties in proportion to those
strengths (Luce's choice rule), so a transfer is defined for any set of continuing parties.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from statistics import quantiles

from vic_election.booth_flows import FIRST, AecCandidate, BoothFlows, BoothLocation
from vic_election.irv import run_irv_from_transfer_matrix

POOLED = "*"  # fallback preference strengths for parties whose own transfers were never observed
UNOBSERVED_WEIGHT = 0.02  # strength towards a party never seen in a final two (relative; observed sum to 1)
NOISE = {"state": 0.08, "seat": 0.12, "flow": 0.15}  # log-scale standard deviations (placeholders)
BT_MAX_ITERATIONS = 200  # Bradley-Terry fixed-point iterations: stop early once strengths move less than BT_TOLERANCE
BT_TOLERANCE = 1e-9
BT_MIN_STRENGTH = 1e-6  # keeps a strength positive when an item never received a vote


def district_primaries(booths: dict[str, BoothFlows], candidates: dict[str, AecCandidate], assignment: dict[str, BoothLocation]) -> dict[str, Counter]:
    """District -> party group -> first-preference votes, from the booths counted in that district."""
    out: dict[str, Counter] = defaultdict(Counter)
    for pid, b in booths.items():
        loc = assignment.get(pid)
        if loc is None or not loc.counted:
            continue
        for (src, to), v in b.votes.items():
            out[loc.district][candidates[to].group if src == FIRST else candidates[src].group] += v
    return dict(out)


def _bradley_terry(pairs: dict[tuple[str, str], list[int]], max_iterations: int = BT_MAX_ITERATIONS) -> dict[str, float]:
    """Bradley-Terry strengths (summing to 1) from pairwise vote splits, by the standard fixed-point iteration."""
    items = {x for pair in pairs for x in pair}
    wins = Counter()
    for (a, b), (va, vb) in pairs.items():
        wins[a] += va
        wins[b] += vb
    w = {x: 1.0 for x in items}
    for _ in range(max_iterations):
        new = {}
        for x in items:
            denom = sum((va + vb) / (w[a] + w[b]) for (a, b), (va, vb) in pairs.items() if x in (a, b))
            new[x] = max(wins[x] / denom, BT_MIN_STRENGTH) if denom else w[x]
        total = sum(new.values())
        new = {x: v / total for x, v in new.items()}
        converged = max(abs(new[x] - w[x]) for x in items) < BT_TOLERANCE
        w = new
        if converged:
            break
    return w


def preference_weights(booths: Iterable[BoothFlows], candidates: dict[str, AecCandidate]) -> dict[str, dict[str, float]]:
    """From-party -> {to-party: strength}, fitted to every observed split between a division's final two."""
    obs: dict[str, dict[tuple[str, str], list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for b in booths:
        fin = tuple(candidates[c].group for c in b.finalists)
        if len(fin) != 2 or fin[0] == fin[1]:
            continue
        for (src, to), v in b.votes.items():
            if src == FIRST or candidates[src].group in fin:
                continue
            obs[candidates[src].group][fin][fin.index(candidates[to].group)] += v
    weights = {p: _bradley_terry(pairs) for p, pairs in obs.items()}
    pooled: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for pairs in obs.values():
        for pair, (va, vb) in pairs.items():
            pooled[pair][0] += va
            pooled[pair][1] += vb
    weights[POOLED] = _bradley_terry(pooled)
    return weights


def _strength(weights: dict[str, dict[str, float]], src: str, dst: str) -> float:
    return weights.get(src, weights[POOLED]).get(dst, UNOBSERVED_WEIGHT)


IND = "IND*"
COALITION = ("LP", "NP")
# AEC party codes -> the state party groups they continue as (vic_election.benchmark.party_group)
FEDERAL_TO_STATE = {"LTP": "LDP", "SAL": "Socialist Alliance", "CEC": "Australian Citizens Party (Victorian Division)"}


def apply_state_field(primaries: dict[str, Counter], field: dict[str, set[str]], weights: dict[str, dict[str, float]]) -> tuple[dict[str, Counter], dict]:
    """
    Restrict each district's federal vote to the parties actually standing at the state election (`field`:
    district -> state party groups). Votes of a federal party with no state candidate are handed on as if
    it were excluded first: to its Coalition partner if one of the Liberals/Nationals is missing, otherwise
    to the standing parties in proportion to its fitted preference strengths. The pooled federal independent
    vote is kept only where an independent stands. A standing party with no federal vote here gets none
    ("nothing changes"). Returns the new primaries and, per district, what was moved where.
    """
    out, notes = {}, {}
    for d, prim in primaries.items():
        standing = field.get(d, set())
        votes = Counter()
        for p, v in prim.items():
            votes[FEDERAL_TO_STATE.get(p, p)] += v
        keep = [p for p in votes if p in standing]  # a list, in vote order: set order varies between processes and would reorder the random draws
        moved: dict[str, dict[str, float]] = {}
        for p in [p for p in votes if p not in keep]:
            partner = next((q for q in COALITION if q != p), None) if p in COALITION else None
            if partner in keep:
                targets = {partner: 1.0}
            else:
                targets = {q: _strength(weights, p, q) for q in keep}
            z = sum(targets.values())
            moved[p] = {q: votes[p] * s / z for q, s in targets.items()}
        new = Counter({p: float(votes[p]) for p in keep})
        for parts in moved.values():
            for q, v in parts.items():
                new[q] += v
        out[d] = new
        notes[d] = {"dropped": {p: round(votes[p]) for p in moved}, "no_federal_vote": sorted(standing - set(votes))}
    return out, notes


def central_count(prim: Counter, weights: dict[str, dict[str, float]]) -> dict:
    """The noise-free replay, stage by stage, as % of formal votes: who is excluded and where their votes go."""
    total = sum(prim.values())
    votes = {p: 100 * v / total for p, v in prim.items() if v > 0}
    flows = {p: {q: _strength(weights, p, q) for q in votes if q != p} for p in votes}
    res = run_irv_from_transfer_matrix(votes, flows, candidates=list(votes), mode="full_2cp")
    stages = [{"excluded": [r.excluded_candidate], "pile": r.excluded_votes, "transfers": dict(r.transfers),
               "totals": dict(r.progressive_totals)} for r in res.rounds]
    return {"first": votes, "stages": stages, "final": dict(res.final_totals), "winner": res.winner}


def simulate(
    primaries: dict[str, Counter],
    weights: dict[str, dict[str, float]],
    runs: int = 1000,
    seed: int = 1,
    noise: dict[str, float] | None = None,
) -> dict:
    """
    Replay every district's count `runs` times. Each run scales every party's vote by a statewide factor
    (shared by all districts) and a district factor, and every party's attractiveness as a preference
    recipient by a statewide factor, all log-normal with the log-sds in `noise` (default NOISE).
    Returns per-district win and final-two counts, 2CP shares and statewide seat counts per run.
    """
    noise = NOISE if noise is None else noise
    rng = random.Random(seed)
    parties = sorted({p for c in primaries.values() for p in c})
    wins = {d: Counter() for d in primaries}
    final_two = {d: Counter() for d in primaries}
    tcp: dict[str, dict[str, list[float]]] = {d: defaultdict(list) for d in primaries}
    pair_tcp: dict[str, dict[tuple[str, str], list[float]]] = {d: defaultdict(list) for d in primaries}
    order: dict[str, Counter] = {d: Counter() for d in primaries}
    seats: dict[str, list[int]] = {p: [] for p in parties}
    for _ in range(runs):
        state = {p: rng.gauss(0, noise["state"]) for p in parties}
        appeal = {p: math.exp(rng.gauss(0, noise["flow"])) for p in parties}
        won = Counter()
        for d, prim in primaries.items():
            votes = {p: v * math.exp(state[p] + rng.gauss(0, noise["seat"])) for p, v in prim.items() if v > 0}
            flows = {p: {q: _strength(weights, p, q) * appeal[q] for q in votes if q != p} for p in votes}
            res = run_irv_from_transfer_matrix(votes, flows, candidates=list(votes), district=d, mode="full_2cp")
            total = sum(res.final_totals.values())
            wins[d][res.winner] += 1
            won[res.winner] += 1
            for p, v in res.final_totals.items():
                final_two[d][p] += 1
                tcp[d][p].append(100 * v / total)
            a, b = sorted(res.final_totals)
            pair_tcp[d][(a, b)].append(100 * res.final_totals[a] / total)
            order[d][tuple(res.elimination_order[-2:])] += 1  # the last two exclusions decide three-way seats
        for p in parties:
            seats[p].append(won[p])
    return {"runs": runs, "wins": wins, "final_two": final_two, "tcp": tcp, "pair_tcp": pair_tcp, "order": order, "seats": seats}


def percentiles(values: list[float]) -> tuple[float, float, float] | None:
    """(p10, p50, p90) of `values`, all from the same inclusive-quantile definition; None if empty."""
    if not values:
        return None
    if len(values) == 1:
        return (values[0],) * 3
    deciles = quantiles(values, n=10, method="inclusive")
    return deciles[0], deciles[4], deciles[-1]
