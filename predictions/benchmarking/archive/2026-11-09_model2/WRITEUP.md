# Model 2 benchmark archive — 9 November 2026

Frozen results of [model2](../../../modelling/model2/README.md), the core-candidate heuristic:
minor candidates collapsed into the core (top four on primaries, plus credible independents), the core
contest resolved for whichever exclusion order each draw produces, with **origin tracking** (every
part of an excluded pile split by the flows of the party its votes started with). Luce preference
flows fitted to distributions of preferences. 5,000 Monte Carlo runs, seed 1, placeholder noise.

Reproduce with [`reproduce.sh`](reproduce.sh). `results.csv` has one row per run; `runs/` holds each
run's full outputs, including `core_stage.csv` (core flag and probability of being the first core
candidate excluded). Metrics are defined in [`../../README.md`](../../README.md).

## Runs

| Run | What it is |
|---|---|
| `<STATEyyyy> (B1)` | Benchmark B1 on every single-member state election model1 is scored on: that election's **actual** primaries, flows fitted to its own distributions of preferences **without the scored district** (leave-one-district-out). Tests flows and count mechanics only. |
| `VIC2026 (2022)` | Forecast for 28 November 2026: 2022 primaries, proportional swing to the polling average, One Nation on its 2025 federal booth pattern, six credible independents. |

## Data

Every state's district distributions come from its electoral commission (`scripts/fetch_state_dops.py`,
parsers in `src/vic_election/state_dop.py`):

| Election | Source | Districts | Exclusions | Exhausted |
|---|---|---|---|---|
| QLD 2020, 2024 | ECQ results archive XML | 93, 93 | 411, 339 | 0% (full preferential) |
| WA 2021, 2025 | WAEC results API | 59, 59 | 345, 280 | 0.04%, 0.06% |
| SA 2022 | ECSA final-distribution CSVs | 47 | 146 | 0% |
| VIC 2022 | VEC (full distributions incl. indicative) | 88 | — | 0% |
| NSW 2023 | NSWEC Virtual Tally Room | 93 | 376 | **11.4%** (optional preferential) |
| SA 2026 | ECSA results API | 47 | 294 | 0% |

Checks, all passing: every district is counted to the final two; every exclusion moves exactly the
excluded pile (transfers + exhausted); progressive totals reproduce the final count; and **the
commissions' own counts give the same winner as `data/benchmarks/winners/` in all 491 districts**.
That independently confirms the Wikipedia-derived winner files that model1 is scored on.

NSW uses optional preferential voting, so exhausted ballots are fitted as one more choice (EXH) and
leave the count when drawn. In replays One Nation's flows are fitted from data like every other party's;
the One Nation priors are only used in the 2026 forecast, where One Nation has no Victorian history.

## B1 results

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
| **All 579 seats** | **566 (97.8%)** | **0.038** | **0.089** | | |
| *Baseline: primary leader wins (certain)* | 549 (94.8%) | 0.104 | 0.358 | | |

**Close seats** (finished within 47–53 after preferences; 87 seats, chosen after the fact):
the primary-leader baseline wins 68 (Brier 0.437, log loss 1.509).

## Choosing the count method

Before this archive, three count methods were compared on the same replays (5,000 runs each):

| Method | Core | Seats | Brier | Log loss |
|---|---|---|---|---|
| `core`: whole pile split by the excluded candidate's party | top 3 | 558 | 0.052 | 0.130 |
| `full`: every candidate counted in turn, whole-pile splits | — | 559 | 0.053 | 0.126 |
| `origin`: piles tracked by original party | top 3 | 566 | 0.0381 | 0.0947 |
| `full` with origin tracking | — | 566 | 0.0380 | 0.0894 |
| **`origin`, core = top 4 (model2)** | top 4 | **566** | **0.0379** | **0.0893** |

- **Origin tracking is what improves the results** (558 → 566 seats, log loss 0.13 → 0.09). It
  matters where a large pile carries many inherited minor-party votes (Queensland, WA 2025, SA 2026).
- **Counting every candidate adds nothing** once the core is wide enough. The only seat where
  `full`-with-origin beat top-3 `origin` was Finniss (SA 2026), won by an independent from fourth
  place, which a top-three core cannot elect. A top-four core recovers it. Model 2 is therefore
  `origin` with a top-four core; the other methods were removed from the code.

## What the results show

- **The remaining misses are the hard three-way seats the model exists for:**
  - *Greens from third*: Maiwar (QLD 2020, 2024), South Brisbane (QLD 2020), Prahran (VIC 2022).
  - *Independents from behind*: Noosa (QLD 2020, 2024), Finniss (SA 2026), Wollondilly (NSW 2023).
  - *Very narrow seats*: Kalamunda (WA 2025, 82 votes), Pilbara (207 votes), Bundaberg, Currumbin.
- **Probabilities are overconfident at the margin.** Several misses were given 97–100%. Flow noise
  (log-SD 0.15 statewide, 0.05 by seat) is too small for seats decided by a few hundred votes, and
  seat-specific preference behaviour (local how-to-vote cards, candidate effects) is not modelled.
  Calibrating flow noise on these 579 seats is the obvious next step.
- **Not comparable with model1's scores.** B1 is given the actual primaries; model1 forecasts from
  federal votes. B1 bounds the error from preferences and the count alone: about 2% of seats.

## VIC2026 (2022) — forecast, not yet scored

Polling average (each pollster's latest eligible poll within 35 days of 5 Nov 2026, normalised):
Labor 22.7, Coalition 30.7, One Nation 22.0, Greens 14.9, others 9.7.

| Liberal | Labor | One Nation | Greens | Nationals | Independents | P(Liberal ≥ 45) |
|---|---|---|---|---|---|---|
| 42.2 (p10–p90 30–54) | 18.9 (8–31) | 11.1 (3–20) | 7.7 | 7.6 | 0.7 | 40% |

28 of 88 seats have no candidate above 60%. Placeholder parameters (noise sizes, One Nation flow
priors, One Nation geographic elasticity) dominate these numbers.

**Reproducibility fix in this archive.** Regional deviations used to be drawn in the iteration order
of a Python `set`, which changes between processes, so the same seed gave slightly different 2026
results run to run. They are now drawn in sorted order; two runs with different hash seeds give
byte-identical outputs. Replays were not affected.

## Known limitations

- Removed 2022 independents' votes are shared out in proportion (e.g. Shepparton, Mildura).
- Candidate lists for 2026 are 2022's plus One Nation in every seat until the VEC ballot draw.
- Liberal ↔ One Nation splits in the 2026 forecast are priors; SA 2026 and QLD 2024 now give fitted
  estimates that could replace them.
- Pile flows: a later exclusion's pile includes inherited votes, so fitted flows mix origins, and
  origin tracking then applies them as if they were pure.
