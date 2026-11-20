# Model 2 — Core-Candidate Heuristic

**Status:** implemented (`model2.py`, `run_model2.py`). Parameter values are still the placeholders
below; [Implementation](#implementation) records how each stage was built and where it departs from
the design. Model 2 counts with **origin tracking** (Stage 3); the earlier `core` and `full` variants
were compared on the benchmarks and removed (see [Variants](#variants)).

```bash
.venv/bin/python predictions/modelling/model2/run_model2.py --all          # every run
.venv/bin/python predictions/modelling/model2/run_model2.py "VIC2026 (2022)" --runs 20000
```

| Run | What it is | Scored |
|---|---|---|
| `<STATEyyyy> (F)` | Forecast backtest: previous-election baseline and flows, final-poll target (`VIC2022 (F)`, `QLD2024 (F)`) | Declared winners |
| `VIC2026 (2022)` | 2026 forecast: 2022 primaries swung to the 2026 polling average | After 28 Nov 2026 |

The bracket names the data the run starts from (for model1 it is the federal election year).

## Idea

A preferential count only has a few decisions that change the winner. Minor candidates are
almost always excluded first, and the order they go out in barely matters. What matters is the
**core stage**: when 2-4 serious candidates remain, who is excluded next, and where their votes go.

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
candidate win, as Finniss did in SA 2026.) Independents are core only if flagged credible
(e.g. high-profile, recontesting, or strong in 2022) — see [Independents](#independents).

## Stage 2 — Collapse minor candidates into the core

Victoria is full preferential, so every minor vote eventually reaches a core candidate. Each minor
party *m* has a flow vector `f[m → k]` over the core candidates *k* in that seat (renormalised over
whichever core candidates are actually running).

Core total before the core stage:

```
T[k] = primary[k] + Σ_m primary[m] · f[m → k]
```

Approximation: ignores the order minor candidates are excluded in.
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
version) was dropped after benchmarking.

## Stage 4 — Monte Carlo

Each run draws all uncertain inputs, then runs Stages 2-3 for all 88 districts.

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

- Central case: One Nation lowest (22 own + 7.1 inherited) → **Liberal 51.1 - Labor 48.9, Liberal wins.**
  (Splitting the whole pile 80/20 would give 53.2 - 46.8.)
- 1-point swing Liberal → One Nation: Liberal lowest →
  **Labor 52.5 - One Nation 47.5, Labor wins.**

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
- Seat noise is wide (e.g. 15-35% plausible range) with only a small statewide component.
- Preferences **from** independents when excluded are diffuse; wide uncertainty.
- Preferences **to** independents in a final two are strong (Hawthorn 2022 data-entered ballots:
  75.6% to independent Melissa Lowe over the Liberal).

---

## Parameters

| Parameter | Placeholder | Planned source |
|---|---|---|
| Statewide polling average per party | — | Published 2026 polls (weighted average) |
| Statewide swing SD per party | ~2-3 pts | Historical Victorian / Australian polling error |
| Regional deviation SD | ~2 pts | 2018→2022 swing variance by region |
| Seat noise SD (party candidates) | ~3-4 pts | 2018→2022 seat-level residuals |
| Seat noise range (credible independents) | 15-35% | 2022 independent results, candidate assessment |
| Minor flows `f[m → k]` | see example | 2022 VEC distributions (where m was excluded), 7 data-entered seats |
| Greens → Labor / Liberal / One Nation | 80 / 12 / 8 | 2022 VEC distributions; data-entered seats |
| One Nation → Liberal (vs Labor) | 80% (range 65-90%) | Federal / NSW flows, Victorian Upper House patterns, how-to-vote cards |
| Liberal → One Nation (vs Labor) | 65% (range 45-80%) | Few sources; data-entered seats give Liberal flows (to Greens vs Labor only); how-to-vote cards |
| Labor → Liberal (vs One Nation) | 60% (range 45-75%) | Few sources; wide uncertainty |
| Core threshold | 5% of runs in top four | Top three missed fourth-place winners (e.g. Finniss) |
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

## Forecast history snapshots

`run_model2.py` can run the `VIC2026 (2022)` forecast retrospectively. A poll enters the polling
average once its fieldwork ended at least 2 days before the as-of date (a proxy for publication);
the usual rule — each pollster's latest eligible poll within 35 days of the newest remaining poll —
then applies unchanged. Candidate fields, independents and all model settings are whatever is in the
repository at run time, so snapshots are *retrospective estimates*, not forecasts published on those
dates (`run_metadata.json` records `as_of`, `generated`, `poll_cutoff` and `retrospective`).

```bash
run_model2.py --as-of 2026-10-13          # one date → output/VIC2026 snapshots/2026-10-13/
run_model2.py --snapshots                 # every 14 days from 2026-09-01 to today
run_model2.py --snapshots --force         # regenerate existing snapshot dirs
```

`--snapshots` skips a date whose polling set is identical to the previous kept snapshot's (roughly
monthly when few polls are published) and never overwrites an existing snapshot without `--force`.
Same runs/seed as the main forecast (5,000 / 1). `site/data/snapshots/` and the date slider on the
site are built from these outputs by `scripts/build_site.py`.

## Variants

Three count methods were compared on the benchmarks before settling on one:

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

**Flows (Stages 2-3).** Every exclusion in the 2022 VEC full distributions (`full_2cp_2022.json`,
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

**Count (Stages 2-3).** `count_seat` in `model2.py`: minor votes go to the core by their own party's
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
- **Regional and seat noise:** 2.0 and 3.5 points (scaled down for small shares). Regions are the
  eight Legislative Council regions in Victoria and ABS ASGS Edition 3 SA4 groups elsewhere
  (`data/benchmarks/regions/`; each district takes the SA4 group holding the largest share of its
  counted federal booth votes at the preceding federal election).
- **Credible independents:** their 2022 primary if recontesting (matched by surname in the same
  district), otherwise a starting estimate of 10%, with SD 6 points. This is not a cap;
  a simulated primary can exceed 10%. Party shares are renormalised around them.

**Outputs.** The standard files plus `core_stage.csv` (mean primary, core flag and
`p_excluded_at_core` per candidate) and `district_counts.json` (per district: win and final-two
chances, the three most likely final pairs with each side's 2CP p10/p50/p90, the five most likely
core exclusion orders, and the central scenario counted stage by stage with every candidate excluded in
turn). The visualiser's Model 2 view reads `district_counts.json` (`scripts/build_visualiser.py --forecasts-only`).

## Results

Forecast backtests (`(F)` runs, previous-election inputs only — see
[forecast_backtests.csv](../../benchmarking/forecast_backtests.csv)):

| Run | Seats right | Accuracy | Brier | Log loss | FP error (pp) | Final two |
|---|---|---|---|---|---|---|
| `VIC2022 (F)` | 81 / 88 | 92.0% | 0.162 | 0.354 | 3.56 | 48.9% |
| `NSW2023 (F)` | 76 / 93 | 81.7% | 0.282 | 0.656 | 3.57 | 77.4% |
| `QLD2024 (F)` | 79 / 93 | 84.9% | 0.234 | 0.410 | 2.66 | 94.6% |
| `WA2025 (F)` | 55 / 59 | 93.2% | 0.134 | 0.264 | 3.16 | 74.6% |
| `SA2026 (F)` | 38 / 47 | 80.9% | 0.242 | 0.581 | 3.85 | 83.0% |

The federal-baseline variants (`(F fed<year>)`) use the preceding federal election as the baseline:
first preferences are that election's votes in each state district, built by
`scripts/build_fed_primaries.py` as located booth votes plus each division's declaration and
unlocated votes raked by iterative proportional fitting so each district part keeps its own
located party mix while party totals stay exact (`inputs/fed_primaries_<state><year>.csv`), and flows are
fitted on the AEC's round-by-round federal distributions (`state_dop.aec_division_dops`). The pooled
federal `IND*` group matches no state candidate, so independent baseline information (recontesting
shares and the minor-independent median) is read from the same seats the state variant uses
(`baseline_2026(ind_source=...)`); the pooled vote drops out like any non-standing party. Everything
else is identical, including the candidate list, credible-independent rule, poll target, regions and
noise.
NSW's optional-preferential exception: party-to-party strengths come from the federal counts but
each source party's EXH strength is imported from the NSW state counts, scaled by that party's
state EXH/ALP strength ratio (`merge_state_exhaustion` in run_model2.py). Federal pseudo-candidates
whose party group stands nowhere (including pooled federal independents) drop out of the baseline
and their votes are redistributed when each draw renormalises.

| Run | Seats right | Accuracy | Brier | Log loss | FP error (pp) | Final two |
|---|---|---|---|---|---|---|
| `VIC2022 (F fed2022)` | 78 / 88 | 88.6% | 0.159 | 0.278 | 3.41 | 47.7% |
| `NSW2023 (F fed2022)` | 72 / 93 | 77.4% | 0.380 | 0.943 | 4.23 | 86.0% |
| `QLD2024 (F fed2022)` | 80 / 93 | 86.0% | 0.195 | 0.297 | 3.05 | 95.7% |
| `WA2025 (F fed2022)` | 50 / 59 | 84.7% | 0.266 | 0.841 | 3.16 | 79.7% |
| `SA2026 (F fed2025)` | 38 / 47 | 80.9% | 0.257 | 0.611 | 3.60 | 80.9% |

All five beat model1's federal-booth replay (72/88, 64/93, 76/93, 42/59, 36/47) and model3's
poll-rescaled federal votes on seat-level metrics. The NSW baseline blends each old district's
actual 2019 primaries by the official elector-transfer table in the 2021 redistribution report,
unlike the located-booth remaps used for SA and WA. Regional deviations outside Victoria now use ABS ASGS Edition 3
SA4 groups (`data/benchmarks/regions/`); the experiment grid in
`predictions/benchmarking/region_experiment.csv` found that grouping improved mean log loss only
slightly (0.412 -> 0.402 across the four non-Victorian runs) with seats right unchanged, and SA4 groups beat the
coarser Greater-Capital/rest split. The replays that used to be here were removed on
16 Nov 2026: given the actual primaries, they did not measure forecasting.

`VIC2026 (2022)`, 5,000 runs, on the declared candidate fields, polls to 10 Nov 2026 (ALP 21.9,
Coalition 31.3, One Nation 21.6, Greens 14.3, others 10.9 after normalising): Liberal 43.2, Labor 18.1,
Nationals 9.1, One Nation 8.7, Greens 7.9, independents 1.0 mean seats; a majority needs 45, and the
Liberals win 45+ on their own in 45% of runs. 25 seats have no candidate above 60%. These are
placeholder-parameter results, not a final forecast. Frozen copy of the 9 Nov run (polls to 5 Nov):
[`archive/2026-11-09_model2_candidates/`](../../benchmarking/archive/2026-11-09_model2_candidates/WRITEUP.md)
(the earlier placeholder-field forecast is in `archive/2026-11-09_model2/`).

## Known limitations

- **Released independent votes.** Removing a large 2022 independent vote (Sheed 29% in Shepparton,
  Cupper 34% in Mildura) hands it to the other candidates in proportion to their shares.
- **Parties expanding into new seats** start from their 25th-percentile 2022 share (e.g. Victorian
  Socialists, 22 seats in 2022 → 88), probably too high in rural seats.
- **The `(F)` backtests** are the B2-style check: each uses previous-election primaries on the
  scored boundaries (notional where boundaries changed: `data/*/notional_*_boundaries.json`),
  previous-election flows, the final polls and the scored candidate list. All noise sizes are still
  placeholders; on the VIC and QLD runs the model's most likely final pair was right in 130 of 181
  districts and the winner's 80% 2CP range contained the result about 63% of the time there, so
  treat ranges as minimum uncertainty.

- Minor-candidate exclusion order is ignored.
- Flows are assumed party-level and roughly uniform statewide, apart from seat noise.
- Liberal and One Nation flows are poorly observed; results in Labor/Liberal/One Nation seats
  depend heavily on them.
- Independent assessment is partly judgement-based.
- 2022 baselines assume unchanged boundaries.
