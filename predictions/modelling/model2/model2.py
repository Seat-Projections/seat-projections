"""
Model 2 — core-candidate heuristic. See predictions/modelling/model2/README.md.

Each seat's candidates are split into a few *core* candidates and the *minor* rest. Minor votes are sent
straight to the core with per-party flows; the core contest is then resolved explicitly, in whichever
exclusion order the drawn primaries produce. Monte Carlo over primaries and flows gives probabilities.

Preferences are a Luce (Plackett-Luce first-choice) model per source party: an excluded pile of party x
goes to each continuing candidate k in proportion to a strength w[x][party(k)]. Strengths are fitted to
every exclusion in the 2022 VEC distributions of preferences, so any continuing set has a defined split
and the conditional splits s[x -> y | {y, z}] = w[x][y] / (w[x][y] + w[x][z]) of the design follow.
"""
from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from statistics import quantiles

from vic_election.benchmark import norm_district, party_group

POOLED = "*"  # strengths fitted to every source party together: fallback and shrinkage target
EXH = "EXH"  # pseudo-recipient for exhausted ballots (optional preferential voting, e.g. NSW)
SHRINK_VOTES = 2000.0  # a source party's own fit counts as this many votes' worth against the pooled fit
FLOOR = 0.002  # strength of a recipient party never observed
IND = "IND*"
COALITION = ("LP", "NP")
BLOCS = ("ALP", "LNP", "GRN", "ON", "OTH")  # how polls report the vote

# Placeholders from the design (README "Parameters"); log-scale for flows, percentage points for votes
NOISE = {
    "poll_sd": 2.5,  # statewide polling error per bloc
    "region_sd": 2.0,  # regional deviation per bloc (Legislative Council region)
    "seat_sd": 3.5,  # seat noise for party candidates
    "flow_state": 0.15,  # statewide log-noise on every flow strength
    "flow_seat": 0.05,  # seat-level log-noise on every flow strength
}
CORE_TOP = 4  # a candidate is core if in the top CORE_TOP of primaries ... (4, not 3: lets a fourth-placed
#               candidate win, e.g. Finniss SA 2026; with no smaller candidates standing it matches
#               counting every candidate)
CORE_SHARE = 0.05  # ... in at least this share of pre-pass runs
CORE_PREPASS = 200
NEW_IND = (10.0, 6.0)  # prior (mean, sd) primary for a credible independent who did not run in 2022
RECONTEST_IND_SD = 6.0
ON_ELASTICITY = 0.7  # One Nation's 2026 seat pattern: (federal 2025 share / mean) ** elasticity

# One Nation barely contested 2022, so flows to and from it are priors (triangular: low, mode, high)
ON_PRIORS = {
    "ON->LP|LP,ALP": (0.65, 0.80, 0.90),
    "LP->ON|ON,ALP": (0.45, 0.65, 0.80),
    "ALP->LP|LP,ON": (0.45, 0.60, 0.75),
    "GRN->ON:ALP": (0.05, 0.10, 0.20),  # Greens strength to One Nation relative to Labor
    "RIGHT->ON:LP": (1.0, 1.43, 2.0),  # right-populist minors: strength to One Nation relative to Liberal
    "OTHER->ON:LP": (0.6, 0.86, 1.2),  # other minors and independents
}
RIGHT_MINORS = {"FFP", "Freedom Party of Victoria", "Labour DLP", "LDP", "Shooters, Fishers & Farmers Vic",
                "Angry Victorians Party", "Derryn Hinch's Justice Party", "Health Australia Party",
                "The Republican Make Australia Great Again", "Safety Victoria - Violent Crime Prevention",
                "Australian Citizens Party (Victorian Division)"}


@dataclass(frozen=True)
class Cand:
    cid: str
    party: str  # party group
    votes: float


@dataclass
class Seat:
    district: str
    region: str
    cands: list[Cand]
    credible: set[str] = field(default_factory=set)  # candidate ids of credible independents
    ind_prior: dict[str, tuple[float, float]] = field(default_factory=dict)  # cid -> (mean, sd) primary %


# ---------------------------------------------------------------- 2022 data

def seats_from_vec(tables: dict, regions: dict[str, str]) -> dict[str, Seat]:
    out = {}
    for d, t in tables.items():
        party = {c["candidate_id"]: party_group(c["party"]) for c in t["candidates"]}
        out[d] = Seat(d, regions.get(d, regions.get(norm_district(d), "")), [Cand(c, party[c], float(v)) for c, v in t["first_preferences"].items()])
    return out


def flow_observations(tables: dict, exhaust: bool = False) -> list[tuple[str, str, list[str], list[float]]]:
    """
    (district, source party, continuing candidates' parties, votes each received) for every exclusion. With
    `exhaust` (optional preferential voting), exhausted votes are one more alternative, EXH, in every choice.
    """
    obs = []
    for d, t in tables.items():
        party = {c["candidate_id"]: party_group(c["party"]) for c in t["candidates"]}
        for s in t["steps"]:
            cont = [c for c in s["transfers"] if c != s["excluded_candidate"]]
            alts, votes = [party[c] for c in cont], [float(s["transfers"][c]) for c in cont]
            if exhaust:
                alts, votes = alts + [EXH], votes + [float(s.get("exhausted", 0.0))]
            if cont and sum(votes) > 0:
                obs.append((d, party[s["excluded_candidate"]], alts, votes))
    return obs


def _luce_mm(obs: list[tuple[list[str], list[float]]], iters: int) -> dict[str, float]:
    """Maximum-likelihood Luce strengths (Hunter's MM algorithm); alternatives may repeat a party."""
    wins: Counter = Counter()
    for alts, n in obs:
        for a, v in zip(alts, n):
            wins[a] += v
    w = {a: 1.0 for alts, _ in obs for a in alts}
    for _ in range(iters):
        denom: Counter = Counter()
        for alts, n in obs:
            tot, s = sum(n), sum(w[a] for a in alts)
            for a in alts:
                denom[a] += tot / s
        w = {a: max(wins[a] / denom[a], 1e-9) for a in w}
        z = sum(w.values())
        w = {a: v / z for a, v in w.items()}
    return w


def fit_flows(obs, iters: int = 60) -> dict[str, dict[str, float]]:
    """Source party -> {recipient party: strength}, shrunk towards the pooled fit for thinly observed sources."""
    by_src: dict[str, list] = defaultdict(list)
    for d, src, alts, n in obs:
        by_src[src].append((alts, n))
    pooled = _luce_mm([o for v in by_src.values() for o in v], iters)
    out = {POOLED: pooled}
    for src, o in by_src.items():
        own, n = _luce_mm(o, iters), sum(sum(x[1]) for x in o)
        k = n / (n + SHRINK_VOTES)
        out[src] = {a: k * own.get(a, 0.0) + (1 - k) * pooled.get(a, 0.0) for a in set(own) | set(pooled)}
    return out


def strength(w: dict[str, dict[str, float]], src: str, dst: str) -> float:
    return max(w.get(src, w[POOLED]).get(dst, 0.0), FLOOR)


def on_strength(w: dict[str, dict[str, float]], src: str, dst: str, draw: dict[str, float]) -> float:
    """
    Strength with every flow to and from One Nation set by the drawn priors, relative to fitted strengths
    (One Nation barely contested 2022, so its fitted flows are not used).
    """
    if src == "ON":
        p = draw["ON->LP|LP,ALP"]
        fixed = {"ALP": 1.0, "LP": p / (1 - p), "NP": p / (1 - p), "GRN": draw["GRN->ON:ALP"]}
        return fixed[dst] if dst in fixed else strength(w, POOLED, dst) / strength(w, POOLED, "ALP")
    if dst != "ON":
        return strength(w, src, dst)
    if src in COALITION:
        p = draw["LP->ON|ON,ALP"]
        return strength(w, src, "ALP") * p / (1 - p)
    if src == "ALP":
        p = draw["ALP->LP|LP,ON"]
        return strength(w, src, "LP") * (1 - p) / p
    if src == "GRN":
        return strength(w, src, "ALP") * draw["GRN->ON:ALP"]
    return strength(w, src, "LP") * draw["RIGHT->ON:LP" if src in RIGHT_MINORS else "OTHER->ON:LP"]


def strength_fn(w, draw: dict[str, float] | None, *noises: dict):
    """
    (src, dst) -> strength: fitted flows, One Nation priors (skipped when `draw` is None), then each
    noise table's log-normal factor.
    """
    def st(src: str, dst: str) -> float:
        x = strength(w, src, dst) if draw is None else on_strength(w, src, dst, draw)
        for n in noises:
            x *= n[(src, dst)]
        return x
    return st


class LogNoise(dict):
    """Lazily drawn exp(N(0, sd)) factor per key, so only the flows a count actually uses are drawn."""
    def __init__(self, rng: random.Random, sd: float):
        super().__init__()
        self.rng, self.sd = rng, sd

    def __missing__(self, key):
        self[key] = v = math.exp(self.rng.gauss(0, self.sd)) if self.sd else 1.0
        return v


# ---------------------------------------------------------------- count

def _split(st, src: str, targets: list[tuple[str, str]], votes: float) -> list[tuple[str, float]]:
    s = [st(src, p) for _, p in targets]
    z = sum(s)
    return [(c, votes * x / z) for (c, _), x in zip(targets, s)]


def count_seat(cands: list[Cand], core: set[str], st, exhaust: bool = False, order: list | None = None,
               stages: list | None = None) -> tuple[str, dict[str, float], str | None]:
    """
    One count. Returns (winner, final-two totals, first core candidate excluded or None).

    Minor candidates' votes go straight to the core by each minor party's flows. Each core pile is kept
    broken down by the party its votes started with (origin tracking); when a core candidate is excluded,
    every part of the pile is split by its own origin party's flows. With `exhaust`, part of every
    transfer goes to EXH and leaves the count. `order`, if given, receives the excluded core candidates in
    turn; `stages` receives one record per stage (excluded candidate, its pile, transfers, totals after).
    """
    party = {c.cid: c.party for c in cands}
    sink = [(EXH, EXH)] if exhaust else []
    piles: dict[str, Counter] = {c.cid: Counter({c.party: c.votes}) for c in cands if c.cid in core}
    targets = [(c, party[c]) for c in piles] + sink
    minors = [c for c in cands if c.cid not in core and c.votes > 0]
    moved: Counter = Counter()
    for c in minors:
        for k, v in _split(st, c.party, targets, c.votes):
            moved[k] += v
            if k != EXH:
                piles[k][c.party] += v
    if stages is not None and minors:
        stages.append({"excluded": [c.cid for c in minors], "pile": sum(c.votes for c in minors), "transfers": dict(moved),
                       "totals": {k: sum(p.values()) for k, p in piles.items()}})
    first = None
    while len(piles) > 2:
        x = min(piles, key=lambda k: (sum(piles[k].values()), k))
        first = first or x
        if order is not None:
            order.append(x)
        pile = piles.pop(x)
        targets = [(c, party[c]) for c in piles] + sink
        moved = Counter()
        for origin, v in pile.items():
            for k, share in _split(st, origin, targets, v):
                moved[k] += share
                if k != EXH:
                    piles[k][origin] += share
        if stages is not None:
            stages.append({"excluded": [x], "pile": sum(pile.values()), "transfers": dict(moved),
                           "totals": {k: sum(p.values()) for k, p in piles.items()}})
    totals = {k: sum(p.values()) for k, p in piles.items()}
    return max(totals, key=lambda k: (totals[k], k)), totals, first


def central_count(cands: list[Cand], st, exhaust: bool = False) -> dict:
    """
    The count of one scenario shown stage by stage: every candidate is excluded in turn (minor candidates
    one at a time rather than together), with origin tracking.
    """
    stages: list = []
    winner, final, _ = count_seat(cands, {c.cid for c in cands if c.votes > 0}, st, exhaust, stages=stages)
    return {"first": {c.cid: c.votes for c in cands}, "stages": stages, "final": final, "winner": winner}


# ---------------------------------------------------------------- primaries

def poll_average(rows: list[dict], window_days: int = 35, as_of=None, lag_days: int = 2) -> dict[str, float]:
    """Mean of each pollster's latest eligible poll ending within `window_days` of the latest poll; sums to 100.
    With as_of set, polls count only once fieldwork ended at least lag_days before as_of."""
    from datetime import date
    rows = [r for r in rows if r["eligible_for_average"] == "true"]
    if as_of is not None:
        cutoff = as_of if isinstance(as_of, date) else date.fromisoformat(as_of)
        rows = [r for r in rows if (cutoff - date.fromisoformat(r["fieldwork_end"])).days >= lag_days]
        if not rows:
            raise ValueError(f"no eligible polls published by {cutoff}")
    end = max(date.fromisoformat(r["fieldwork_end"]) for r in rows)
    latest: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: r["fieldwork_end"]):
        if (end - date.fromisoformat(r["fieldwork_end"])).days <= window_days:
            latest[r["pollster"]] = r
    cols = {"ALP": "alp", "LNP": "lnp", "ON": "onp", "GRN": "grn", "OTH": "others"}
    avg = {b: sum(float(r[c]) for r in latest.values()) / len(latest) for b, c in cols.items()}
    z = sum(avg.values())
    return {b: 100 * v / z for b, v in avg.items()} | {"_polls": sorted(f"{r['pollster']} {r['fieldwork_end']}" for r in latest.values())}


def bloc(party: str) -> str:
    return "LNP" if party in COALITION else party if party in BLOCS else "OTH"


@dataclass
class Baseline:
    """2026 starting point per seat: % shares of party candidates before the statewide swing."""
    seats: dict[str, Seat]
    shares: dict[str, dict[str, float]]  # district -> cid -> %
    weight: dict[str, float]  # district -> formal votes (for statewide averages)


NEW_PARTY_SHARE = 1.0  # % baseline for a party that stood nowhere in 2022


def _surname(name: str) -> str:
    return name.split(",")[0].strip().lower()


def baseline_2026(seats_2022: dict[str, Seat], candidates: list[dict], on_pattern: dict[str, float], independents: list[dict],
                  ind_source: dict[str, Seat] | None = None) -> Baseline:
    """
    Baseline shares for the actual 2026 candidates (`candidates`: rows of data/2026/candidates_vic2026.csv),
    built from each district's 2022 primaries:

    - a party that stood here in 2022 starts from its 2022 share here;
    - a party that stood elsewhere in 2022 starts from its 25th-percentile share in the districts it
      contested; a party that stood nowhere starts from NEW_PARTY_SHARE;
    - the Coalition keeps its 2022 combined share: if only one partner stands now it gets all of it, and
      a partner newly standing takes its mean 2022 share from the other;
    - One Nation (barely stood in 2022) is placed on its 2025 federal booth pattern;
    - independents: credible ones (hand-entered file) get a seat prior (their 2022 primary if recontesting,
      otherwise NEW_IND); others their own 2022 share if recontesting, else the median 2022 minor-independent share.
    2022 candidates whose party does not stand again simply drop out; their votes are shared out when each
    draw renormalises.

    `ind_source` supplies the seats every independent-related rule reads (surname-matched recontesting
    shares and the minor-independent median). The federal-baseline variant passes the state seats its
    counterpart uses, since its own baseline holds only a pooled IND* pseudo-candidate; that pooled
    vote then stands nowhere and drops out like any non-standing party.
    """
    ind_seats = ind_source if ind_source is not None else seats_2022
    ind_pct = {d: {c.cid: 100 * c.votes / sum(x.votes for x in s.cands) for c in s.cands} for d, s in ind_seats.items()}
    mean_on = sum(on_pattern.values()) / len(on_pattern)
    pct = {d: {c.cid: 100 * c.votes / sum(x.votes for x in s.cands) for c in s.cands} for d, s in seats_2022.items()}
    by_party: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))  # district -> party -> 2022 %
    for d, s in seats_2022.items():
        for c in s.cands:
            by_party[d][c.party] += pct[d][c.cid]
    contested: dict[str, list[float]] = defaultdict(list)
    for d, parties in by_party.items():
        for p, v in parties.items():
            contested[p].append(v)
    party_mean = {p: sum(v) / len(v) for p, v in contested.items()}
    # Parties contest their best seats first, so a seat a party did not contest in 2022 starts from its
    # 25th-percentile 2022 result, not its mean (e.g. Victorian Socialists: 22 mostly inner-city seats -> all 88)
    party_low = {p: sorted(v)[len(v) // 4] for p, v in contested.items()}
    minor_ind = sorted(ind_pct[d][c.cid] for d, s in ind_seats.items() for c in s.cands if c.party == IND and ind_pct[d][c.cid] < 10)
    minor_ind_share = minor_ind[len(minor_ind) // 2] if minor_ind else 1.0
    credible = {(r["district"], _surname(r["candidate"])): r for r in independents if r["credible"].strip().upper() == "Y"}

    field: dict[str, list[dict]] = defaultdict(list)
    for r in candidates:
        field[r["district"]].append(r)
    seats, shares, weight = {}, {}, {}
    for d, s in seats_2022.items():
        prev_ind = {_surname(c.cid): ind_pct[d][c.cid] for c in ind_seats[d].cands if c.party == IND} if d in ind_seats else {}
        coalition_2022 = sum(by_party[d].get(p, 0.0) for p in COALITION)
        standing = {r["party_group"] for r in field[d]}
        coalition_now = [p for p in COALITION if p in standing]
        seat = Seat(d, s.region, [])
        sh: dict[str, float] = {}
        for r in field[d]:
            cid, p = r["candidate"], r["party_group"]
            seat.cands.append(Cand(cid, p, 0.0))
            if p == IND:
                key = (d, _surname(cid))
                if key in credible:
                    row, prev = credible[key], prev_ind.get(_surname(cid))
                    mean = float(row["prior_mean"]) if row.get("prior_mean") else (prev if prev is not None else NEW_IND[0])
                    sd = float(row["prior_sd"]) if row.get("prior_sd") else (RECONTEST_IND_SD if prev is not None else NEW_IND[1])
                    seat.credible.add(cid)
                    seat.ind_prior[cid] = (mean, sd)
                else:
                    sh[cid] = prev_ind.get(_surname(cid), minor_ind_share)
            elif p == "ON":
                sh[cid] = (on_pattern.get(d, mean_on) / mean_on) ** ON_ELASTICITY  # index; scaled to One Nation's poll level
            elif p in COALITION and coalition_2022 > 0:
                if len(coalition_now) == 1:
                    sh[cid] = coalition_2022
                elif by_party[d].get(p):
                    other = next(q for q in COALITION if q != p)
                    sh[cid] = by_party[d][p] if by_party[d].get(other) else by_party[d][p] - min(party_mean.get(other, 0.0), by_party[d][p] / 2)
                else:  # partner newly standing: take its mean 2022 share from the other partner
                    other = next(q for q in COALITION if q != p)
                    sh[cid] = min(party_mean.get(p, 0.0), by_party[d].get(other, 0.0) / 2)
            else:
                sh[cid] = by_party[d].get(p) or party_low.get(p, NEW_PARTY_SHARE)
        # several candidates of one party (rare): split the party's share between them
        for p, n in Counter(r["party_group"] for r in field[d] if r["party_group"] not in (IND, "ON")).items():
            if n > 1:
                for r in field[d]:
                    if r["party_group"] == p:
                        sh[r["candidate"]] /= n
        seats[d], shares[d], weight[d] = seat, sh, sum(c.votes for c in s.cands)
    return Baseline(seats, shares, weight)


def _scaled_sd(sd: float, share: float) -> float:
    return sd * min(1.0, math.sqrt(max(share, 0.0) / 25.0))


def draw_primaries(base: Baseline, polls: dict[str, float], rng: random.Random, noise=NOISE) -> dict[str, dict[str, float]]:
    """
    One statewide draw: poll error per bloc, proportional swing from the baseline to the drawn poll level,
    regional and seat noise, credible independents from their seat priors; shares renormalised per seat.
    """
    target = {b: max(polls[b] + rng.gauss(0, _scaled_sd(noise["poll_sd"], polls[b])), 0.5) for b in BLOCS}
    z = sum(target.values())
    target = {b: 100 * v / z for b, v in target.items()}
    tot_w = sum(base.weight.values())
    level: Counter = Counter()  # statewide baseline level per bloc (One Nation: pattern index, mean 1)
    for d, sh in base.shares.items():
        party = {c.cid: c.party for c in base.seats[d].cands}
        for cid, v in sh.items():
            level[bloc(party[cid])] += v * base.weight[d] / tot_w
    factor = {b: target[b] / level[b] for b in BLOCS if level[b] > 0}
    regions = sorted({s.region for s in base.seats.values()})  # sorted: set order varies between processes (hash seed)
    reg = {(r, b): rng.gauss(0, 1) for r in regions for b in BLOCS}
    out = {}
    for d, sh in base.shares.items():
        seat = base.seats[d]
        party = {c.cid: c.party for c in seat.cands}
        v = {}
        for cid, s0 in sh.items():
            b = bloc(party[cid])
            s = s0 * factor[b]
            v[cid] = max(s + _scaled_sd(noise["region_sd"], s) * reg[(seat.region, b)] + rng.gauss(0, _scaled_sd(noise["seat_sd"], s)), 0.05)
        ind = {cid: min(max(rng.gauss(*seat.ind_prior[cid]), 1.0), 60.0) for cid in seat.credible}
        z = sum(v.values()) / (100 - sum(ind.values()))
        out[d] = {cid: x / z for cid, x in v.items()} | ind
    return out


def core_sets(draws: list[dict[str, dict[str, float]]], seats: dict[str, Seat]) -> dict[str, set[str]]:
    """Core = top CORE_TOP in at least CORE_SHARE of the draws, plus credible independents; at least two."""
    out = {}
    for d, seat in seats.items():
        top: Counter = Counter()
        for dr in draws:
            for cid in sorted(dr[d], key=lambda c: -dr[d][c])[:CORE_TOP]:
                top[cid] += 1
        core = {c for c, n in top.items() if n >= CORE_SHARE * len(draws)} | seat.credible
        out[d] = core if len(core) >= 2 else set(sorted(dr[d], key=lambda c: -dr[d][c])[:2])
    return out


# ---------------------------------------------------------------- simulation

def draw_on_priors(rng: random.Random) -> dict[str, float]:
    return {k: rng.triangular(lo, hi, mode) for k, (lo, mode, hi) in ON_PRIORS.items()}


def central_on_priors() -> dict[str, float]:
    return {k: mode for k, (_, mode, _) in ON_PRIORS.items()}


def simulate(
    seats: dict[str, Seat],
    flows_for,  # callable district -> fitted strengths
    primaries,  # callable rng -> district -> cid -> share
    runs: int,
    seed: int,
    noise=NOISE,
    majority: int = 45,
    on_priors: bool = True,  # False fits One Nation's flows like every other party's
    exhaust: bool = False,  # optional preferential voting
) -> dict:
    rng = random.Random(seed)
    prepass = [primaries(rng) for _ in range(CORE_PREPASS)]
    core = core_sets(prepass, seats)
    mean_primary = {d: {c: sum(p[d][c] for p in prepass) / len(prepass) for c in prepass[0][d]} for d in seats}
    res = {k: {d: Counter() for d in seats} for k in ("wins", "final_two", "first_out", "pair", "order")}
    tcp = {d: defaultdict(list) for d in seats}
    pair_tcp = {d: defaultdict(list) for d in seats}  # (cid, cid) sorted -> first candidate's 2CP % per run
    parties = sorted({c.party for s in seats.values() for c in s.cands})
    seat_counts: dict[str, list[int]] = {p: [] for p in parties}
    for _ in range(runs):
        prim = primaries(rng)
        on = draw_on_priors(rng) if on_priors else None
        state = LogNoise(rng, noise["flow_state"])  # shared by every seat: how-to-vote cards and attitudes are statewide
        won: Counter = Counter()
        for d, seat in seats.items():
            party = {c.cid: c.party for c in seat.cands}
            st = strength_fn(flows_for(d), on, state, LogNoise(rng, noise["flow_seat"]))
            cands = [Cand(cid, party[cid], v) for cid, v in prim[d].items()]
            order: list = []
            winner, final, first = count_seat(cands, core[d], st, exhaust, order=order)
            total = sum(final.values())
            res["wins"][d][winner] += 1
            res["pair"][d][tuple(sorted(party[c] for c in final))] += 1
            res["order"][d][tuple(order)] += 1
            a, b = sorted(final)
            pair_tcp[d][(a, b)].append(100 * final[a] / total)
            if first:
                res["first_out"][d][first] += 1
            for c, v in final.items():
                res["final_two"][d][c] += 1
                tcp[d][c].append(100 * v / total)
            won[party[winner]] += 1
        for p in parties:
            seat_counts[p].append(won[p])
    return res | {"tcp": tcp, "pair_tcp": pair_tcp, "seats": seat_counts, "core": core, "mean_primary": mean_primary,
                  "runs": runs, "majority": majority}


def percentiles(values: list[float]) -> tuple[float, float, float] | None:
    if not values:
        return None
    if len(values) == 1:
        return (values[0],) * 3
    q = quantiles(values, n=10, method="inclusive")
    return q[0], sorted(values)[len(values) // 2], q[-1]
