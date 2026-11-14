# Model 2 — Core-Candidate Heuristic

**Status:** implemented (`model2.py`, `run_model2.py`). Parameter values are still the placeholders
below; [Implementation](#implementation) records how each stage was built and where it departs from
the design. Model 2 counts with **origin tracking** (Stage 3); the earlier `core` and `full` variants
were compared on the B1 replays and removed (see [Variants](#variants)).

```bash
.venv/bin/python predictions/modelling/model2/run_model2.py --all          # every run
.venv/bin/python predictions/modelling/model2/run_model2.py "VIC2026 (2022)" --runs 20000
```

| Run | What it is | Scored |
|---|---|---|
| `<STATEyyyy> (B1)` | Benchmark B1 on all 8 elections model1 is scored on (QLD 2020/2024, WA 2021/2025, SA 2022/2026, VIC 2022, NSW 2023): that election's actual primaries, flows fitted to its own distributions of preferences **leaving out the scored district** | Declared winners |
| `VIC2026 (2022)` | 2026 forecast: 2022 primaries swung to the 2026 polling average | After 28 Nov 2026 |

The bracket names the data the run starts from (for model1 it is the federal election year).

## Idea

A preferential count only has a few decisions that change the winner. Minor candidates are
almost always excluded first, and the order they go out in barely matters. What matters is the
**core stage**: when 2–4 serious candidates remain, who is excluded next, and where their votes go.

Model 2 therefore:

1. splits each seat's candidates into **core** and **minor**,
2. sends every minor candidate's votes straight to the core using per-party flow vectors,
3. resolves the core contest explicitly for **whichever exclusion order occurs**,
4. repeats this thousands of times with uncertain primaries and flows (Monte Carlo) to get
   probabilities.

A single predicted runoff table is not used, because it fixes one exclusion order. In seats where
Labor, Liberal and One Nation are close, a small primary shift changes who is excluded third and
can flip the winner (see the worked example).

---

## Stage 1 — Core vs minor candidates

- **Core:** candidates with a realistic path to the final two — typically Labor, Liberal or
  National, One Nation, and where relevant the Greens or a credible independent.
- **Minor:** everyone else.

Rule: a candidate is core if they finish in the top **four** of the pre-preference totals in at least
**5%** of simulation runs. (Top three was the original placeholder; four lets a fourth-placed
candidate win, as Finniss did in SA 2026, and on the B1 replays it matches counting every candidate.) Independents are core only if flagged credible
(e.g. high-profile, recontesting, or strong in 2022) — see [Independents](#independents).

## Stage 2 — Collapse minor candidates into the core

Victoria is full preferential, so every minor vote eventually reaches a core candidate. Each minor
party *m* has a flow vector `f[m → k]` over the core candidates *k* in that seat (renormalised over
whichever core candidates are actually running).

Core total before the core stage:

```
T[k] = primary[k] + Σ_m primary[m] · f[m → k]
```

Approximation: ignores the order minor candidates are excluded in. On the B1 replays this costs
nothing measurable against counting every candidate in turn (see [Variants](#variants)).

## Stage 3 — Resolve the core contest

With three core candidates A, B, C:

1. Exclude the lowest of `T[A], T[B], T[C]`.
2. Split their pile between the other two using the **conditional split**
   `s[x → y | {y, z}]` — the share of x's votes going to y when exactly y and z remain.
3. The higher of the final two wins.

Only three conditional splits are needed per three-way core (one per possible excluded candidate).
With four core candidates, the lowest is excluded first using `s[x → · | {three remaining}]`, then
the three-way step runs.

**Origin tracking.** A core candidate's pile contains votes inherited from minor candidates. Each
pile is kept broken down by the party its votes started with, and when the candidate is excluded each
part is split by that party's own preferences (e.g. Greens-origin votes sitting with One Nation go
mostly to Labor). Splitting the whole pile by the excluded candidate's own split (the original simple
version) was dropped after the B1 replays.

## Stage 4 — Monte Carlo

Each run draws all uncertain inputs, then runs Stages 2–3 for all 88 districts.

**Primaries**

```
primary[seat, party] = baseline_2022[seat, party]
                     + statewide_swing[party]        (one draw per run, shared by all seats)
                     + regional_deviation[region, party]
                     + seat_noise[seat, party]
→ renormalised to sum to 100% per seat
```

- **Statewide swing** — centred on the polling average; spread from historical polling error.
  Shared across seats so polling misses move all seats together.
- **Regional deviation** — captures uneven swings (e.g. One Nation stronger outside inner
  Melbourne). One Nation barely contested the 2022 Lower House (8,077 votes statewide), so its
  geographic pattern comes from a proxy: its 2022 Legislative Council vote by district and/or
  federal results.
- **Seat noise** — candidate effects, retirements, local issues; much wider for credible
  independents.

**Flows** — each minor flow `f` and conditional split `s` is drawn from a range around its
central estimate, mostly as one statewide draw per run (how-to-vote cards and voter attitudes are
statewide) plus small seat-level noise.

**Per run, record:** winner, final two, 2CP shares, and the core exclusion order for every seat,
plus the statewide seat count per party.

---

## Worked example (hypothetical seat)

| Candidate | Primary | Role |
|---|---|---|
| Labor | 26% | core |
| Liberal | 23% | core |
| One Nation | 22% | core |
| Greens | 12% | minor |
| Independent (low profile) | 8% | minor |
| Family First | 5% | minor |
| Animal Justice | 4% | minor |

**Stage 2** (placeholder flows):

| Minor | → Labor | → Liberal | → One Nation |
|---|---|---|---|
| Greens 12 | 80% | 12% | 8% |
| Independent 8 | 35% | 35% | 30% |
| Family First 5 | 15% | 35% | 50% |
| Animal Justice 4 | 45% | 25% | 30% |

Core totals: **Labor 41.0, Liberal 30.0, One Nation 29.1**.

**Stage 3** (placeholder splits: One Nation→Liberal 80%, Liberal→One Nation 65%), with origin
tracking — each excluded pile's own votes follow these splits, inherited minor votes follow their own
party's flows from the Stage 2 table:

- Central case: One Nation lowest (22 own + 7.1 inherited) → **Liberal 51.1 – Labor 48.9, Liberal wins.**
  (Splitting the whole pile 80/20 would give 53.2 – 46.8.)
- 1-point swing Liberal → One Nation: Liberal lowest →
  **Labor 52.5 – One Nation 47.5, Labor wins.**

A 1-point shift between the two right-of-centre parties flips the seat to Labor without Labor's
own vote moving. Stage 4 turns this into a probability by running both branches many times.

---

## Independents

In 2022 six seats finished with an independent in the final two; all six lost, three by about
1 point:

| Seat | Independent | Primary | Final 2CP | Against |
|---|---|---|---|---|
| Mornington | Kate Lardner | 22.4% | 49.3% | Liberal |
| Benambra | Jacqui Hawkins | 31.7% | 49.1% | Liberal |
| Mildura | Ali Cupper | 33.9% | 48.8% | Nationals |
| Shepparton | (Sheed's seat) | 29.4% | 43.2% | Nationals |
| Mulgrave | Ian Cook | 18.0% | 39.2% | Labor |
| Narracan | Tony Wolfe | 11.0% | 37.0% | Liberal |

Treatment in Model 2:

- Credible independents are core candidates; the core stage handles their two hurdles (finishing
  ahead of the weaker major, then winning the final two on preferences).
- Primaries come from seat-level priors (2022 result, recontesting, incumbency, overlapping
  federal results, local polling), not statewide polls.
- Seat noise is wide (e.g. 15–35% plausible range) with only a small statewide component.
- Preferences **from** independents when excluded are diffuse; wide uncertainty.
- Preferences **to** independents in a final two are strong (Hawthorn 2022 data-entered ballots:
  75.6% to independent Melissa Lowe over the Liberal).

---

## Parameters

| Parameter | Placeholder | Planned source |
|---|---|---|
| Statewide polling average per party | — | Published 2026 polls (weighted average) |
| Statewide swing SD per party | ~2–3 pts | Historical Victorian / Australian polling error |
| Regional deviation SD | ~2 pts | 2018→2022 swing variance by region |
| Seat noise SD (party candidates) | ~3–4 pts | 2018→2022 seat-level residuals |
| Seat noise range (credible independents) | 15–35% | 2022 independent results, candidate assessment |
| Minor flows `f[m → k]` | see example | 2022 VEC distributions (where m was excluded), 7 data-entered seats |
| Greens → Labor / Liberal / One Nation | 80 / 12 / 8 | 2022 VEC distributions; data-entered seats |
| One Nation → Liberal (vs Labor) | 80% (range 65–90%) | Federal / NSW flows, Victorian Upper House patterns, how-to-vote cards |
| Liberal → One Nation (vs Labor) | 65% (range 45–80%) | Few sources; data-entered seats give Liberal flows (to Greens vs Labor only); how-to-vote cards |
| Labor → Liberal (vs One Nation) | 60% (range 45–75%) | Few sources; wide uncertainty |
| Core threshold | 5% of runs in top four | Set on B1 (top three missed fourth-place winners) |
| Simulation runs | 20,000 | Enough for ±0.5% on seat probabilities |

The Liberal ↔ One Nation splits are the least observed and most influential parameters; they
should be reported with sensitivity analysis.

---

## Inputs

| Input | Location / source | Status |
|---|---|---|
| 2022 primaries by district | `data/2022/distributions/official_2022.json` | Have |
| 2022 distributions of preferences | `data/2022/distributions/full_2cp_2022.json` | Have |
| 2022 booth-level primaries | `data/2022/raw/statewide/all_district_primary_results_2022.xlsx` | Have |
| 2022 Legislative Council vote by district | VEC | Need |
| 2026 candidate lists | VEC nominations / Australian Election Tracker | Need |
| 2026 polls | Published polling | Need |
| Ballot-level files, 7 data-entered 2022 districts | VEC (on request) | Need |
| 2026 how-to-vote cards | VEC registered how-to-vote cards | Need (published close to election) |
| 2026 boundaries | Confirm unchanged from 2022 | Verify |

## Outputs

Standard files from [`predictions/modelling/README.md`](../README.md#standard-outputs), plus per seat:
`p_excluded_at_core[candidate]` — probability each core candidate is the one excluded at the core
stage, which explains *why* a seat is uncertain.

## Variants

Three count methods were compared on the 579-seat B1 replays (5,000 runs each) before settling on one:

| Method | Core | Seats | Brier | Log loss |
|---|---|---|---|---|
| `core`: whole pile split by the excluded candidate's party | top 3 | 558 | 0.052 | 0.130 |
| `full`: every candidate counted in turn, whole-pile splits | — | 559 | 0.053 | 0.126 |
| `origin`: piles tracked by original party | top 3 | 566 | 0.0381 | 0.0947 |
| `full` with origin tracking | — | 566 | 0.0380 | 0.0894 |
| **`origin`, core = top 4 (model2)** | top 4 | **566** | **0.0379** | **0.0893** |

Origin tracking is what improves the results. Counting every candidate adds nothing once the core
includes the top four: the only difference between `full`-with-origin and `origin` with a top-three
core was Finniss (SA 2026), won by an independent from fourth place. Model 2 therefore keeps only
`origin` with a top-four core.

---

## Implementation

**Flows (Stages 2–3).** Every exclusion in the 2022 VEC full distributions (`full_2cp_2022.json`,
all 88 districts counted to the final two) is one observation: the excluded candidate's party, the
continuing candidates' parties, and the votes each received. A **Luce model** is fitted per source
party (Hunter's MM algorithm): a pile from party *x* goes to each continuing candidate *k* in
proportion to a strength `w[x][party(k)]`. That gives both the minor flows `f[m → k]` (renormalised
over the core) and the conditional splits `s[x → y | {y, z}] = w[x][y] / (w[x][y] + w[x][z])` from
one set of numbers. Thinly observed parties are shrunk towards the fit pooled over all parties (a
party's own fit counts as its votes against 2,000 votes of the pooled fit). The pile of a later
exclusion includes votes it inherited, so these are pile flows, not pure first-preference flows.

**One Nation flows** use the priors in [Parameters](#parameters), drawn per run from triangular
distributions over the stated ranges, because One Nation stood in only 5 seats in 2022. Flows to One
Nation from other parties are set relative to each party's fitted strength (to Labor for the
Coalition and Greens, to the Liberals for Labor and minor parties; right-populist minors lean further
to One Nation). See `ON_PRIORS` in `model2.py`.

**Core (Stage 1).** 200 pre-pass draws of the primaries; a candidate is core if in the top four in
at least 5% of them, plus every credible independent.

**Count (Stages 2–3).** `count_seat` in `model2.py`: minor votes go to the core by their own party's
flows, piles are tracked by origin party, and every part of an excluded pile is split by its origin
party's flows. With optional preferential voting (NSW), exhausted ballots are a fitted choice (EXH)
and leave the count.

**2026 primaries (Stage 4).**
- **Baseline: the declared 2026 candidates** (VEC nominations, closed 9 Nov 2026:
  `scripts/fetch_vic2026_candidates.py` → `data/2026/candidates_vic2026.csv`), each starting from the
  2022 primaries in their district: a party's 2022 share where it stood; its 25th-percentile 2022
  share where it did not; 1% for parties new in 2026; the Coalition keeps its combined 2022 share
  (all of it to one partner if only one stands); One Nation (all 88 seats) on its 2025 federal booth
  pattern (model1's `VIC2026 (2025)` output, elasticity 0.7); credible independents from
  `data/2026/independents_vic2026.csv` (hand-entered, with sources); other independents their own 2022
  share if recontesting, otherwise the median 2022 minor-independent share. See `baseline_2026`.
- **Statewide swing:** the polling average (each pollster's latest eligible poll within 35 days of
  the newest, from the electiontracker.au register saved at `data/2026/polls_vic2026.csv`), drawn
  with ±2.5-point error per bloc (Labor, Coalition, Greens, One Nation, others).
- **Departure from the design: proportional, not additive, swing.** Labor is down about 14 points
  and One Nation up about 21, so an additive swing would push Labor below zero in a third of seats.
  Each party's share is multiplied by (drawn poll level ÷ its statewide baseline level). The
  Liberals and Nationals share the Coalition factor; minor parties share the "others" factor.
- **Regional and seat noise:** 2.0 and 3.5 points (scaled down for small shares), regions = the
  eight Legislative Council regions.
- **Credible independents:** their 2022 primary if recontesting (matched by surname in the same
  district), otherwise 15%, with SD 6 points; party shares are renormalised around them.

**Outputs.** The standard files plus `core_stage.csv` (mean primary, core flag and
`p_excluded_at_core` per candidate) and `district_counts.json` (per district: win and final-two
chances, the three most likely final pairs with each side's 2CP p10/p50/p90, the five most likely
core exclusion orders, and the central scenario counted stage by stage with every candidate excluded in
turn). The visualiser's Model 2 view reads `district_counts.json` (`scripts/build_visualiser.py --forecasts-only`).

## Results

B1 replays, 5,000 runs each (actual primaries, so these test flows and the count only; not
comparable with forecast benchmarks):

| Run | Raw seat count | Brier | Log loss | Final two | 2CP MAE (pts) |
|---|---|---|---|---|---|
| `QLD2020 (B1)` | 91 / 93 | 0.049 | 0.162 | 98.9% | 1.37 |
| `WA2021 (B1)` | 59 / 59 | 0.001 | 0.004 | 100% | 0.75 |
| `SA2022 (B1)` | 46 / 47 | 0.012 | 0.017 | 95.7% | 0.87 |
| `VIC2022 (B1)` | 86 / 88 | 0.038 | 0.101 | 100% | 1.58 |
| `NSW2023 (B1)` | 92 / 93 | 0.026 | 0.045 | 97.8% | 0.90 |
| `QLD2024 (B1)` | 90 / 93 | 0.062 | 0.153 | 98.9% | 1.33 |
| `WA2025 (B1)` | 57 / 59 | 0.039 | 0.056 | 93.2% | 1.43 |
| `SA2026 (B1)` | 45 / 47 | 0.062 | 0.109 | 93.6% | 1.50 |
| **579 seats** | **566 (97.8%)** | **0.038** | **0.089** | | |

For reference, "the primary leader wins" (stated as certain) gets 549 seats, Brier 0.104 and log loss
0.358, so the preference model's contribution is the difference. The misses are Greens wins from
third (Maiwar, South Brisbane, Prahran), independents winning from behind (Noosa, Finniss,
Wollondilly) and seats decided by a few hundred votes, several called at 97–100%: flow noise is too
small at the margin. Details: [`archive/2026-11-09_model2/`](../../benchmarking/archive/2026-11-09_model2/WRITEUP.md).

NSW uses optional preferential voting: exhausted ballots are fitted as one more choice and leave the
count. In replays One Nation's flows are fitted like any other party's; its priors are used only in
the 2026 forecast.

`VIC2026 (2022)`, 5,000 runs, on the declared candidate fields, polls to 5 Nov 2026 (ALP 22.7,
Coalition 30.7, One Nation 22.0, Greens 14.9, others 9.7 after normalising): Liberal 40.2, Labor 20.8,
One Nation 9.2, Nationals 8.8, Greens 8.1, independents 0.9 mean seats; a majority needs 45, and the
Liberals win 45+ on their own in 32% of runs. 29 seats have no candidate above 60%. These are
placeholder-parameter results, not a final forecast. Frozen copy:
[`archive/2026-11-09_model2_candidates/`](../../benchmarking/archive/2026-11-09_model2_candidates/WRITEUP.md)
(the earlier placeholder-field forecast is in `archive/2026-11-09_model2/`).

## Known limitations

- **Released independent votes.** Removing a large 2022 independent vote (Sheed 29% in Shepparton,
  Cupper 34% in Mildura) hands it to the other candidates in proportion to their shares.
- **Parties expanding into new seats** start from their 25th-percentile 2022 share (e.g. Victorian
  Socialists, 22 seats in 2022 → 88), probably too high in rural seats.
- **B2 is not run yet.** Its input now exists: notional 2018 primaries on the 2022 boundaries
  (`data/2018/notional_2022_boundaries.json`, built by `scripts/build_notional_2018.py` from 2018
  voting-centre results placed by coordinates). Still needed: the final 2022 polls and 2022
  candidate lists, and preference flows fitted on 2018 distributions only (no 2022 leakage).

- Minor-candidate exclusion order is ignored (no measurable effect on the B1 replays).
- Flows are assumed party-level and roughly uniform statewide, apart from seat noise.
- Liberal and One Nation flows are poorly observed; results in Labor/Liberal/One Nation seats
  depend heavily on them.
- Independent assessment is partly judgement-based.
- 2022 baselines assume unchanged boundaries.
