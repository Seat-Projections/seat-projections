# Prediction Models

Each model lives in `predictions/modelling/<model_name>/` with a `README.md` describing its method and
assumptions. Every model produces the same output files, so models can be scored and compared side by
side with the metrics in [`../benchmarking/README.md`](../benchmarking/README.md).

| Model | Status | Summary |
|---|---|---|
| [`model1`](model1/README.md) | Implemented | "Nothing changes" baseline: federal polling-place votes added up inside each state district and the preferential count replayed with federal preferences, unchanged. Monte Carlo noise only. |
| [`model2`](model2/README.md) | Implemented | Core-candidate heuristic (2022 VEC baseline swung to 2026 polls): collapse minor candidates into the core, resolve the core contest for every possible exclusion order, Monte Carlo over primaries and preference flows. |
| [`model3`](model3/README.md) | Implemented (research model, not on the site) | Booth-mapped federal-to-state model: model1's booth mapping plus rescaling to state polls, preferences from federal booth counts and Senate ballots, full count with Monte Carlo. |

---

## Standard outputs

Each model writes to `predictions/modelling/<model_name>/output/<run_id>/`:

**`seat_probabilities.csv`** — one row per (district, candidate)

| Column | Meaning |
|---|---|
| `district` | District name as used by the electoral commission (e.g. VEC `Sandringham`, ECSA `Hammond`) |
| `candidate` | Candidate name as on the ballot (`SURNAME, Given`); models that forecast parties put the party-group label here |
| `party` | Party-group code (`ALP`, `LP`, `NP`, `GRN`, `ON`, `IND*`, …) |
| `p_win` | Probability the candidate wins the seat (sums to 1 per district) |
| `p_final_two` | Probability the candidate is in the final two |
| `tcp_p10`, `tcp_p50`, `tcp_p90` | Final two-candidate-preferred (2CP) share percentiles, conditional on reaching the final two |

**`statewide_seats.csv`** — one row per party

| Column | Meaning |
|---|---|
| `party` | Party-group code, as in `seat_probabilities.csv` (independents grouped as `IND*`) |
| `seats_mean`, `seats_p10`, `seats_p50`, `seats_p90` | Seat-count distribution across simulation runs |
| `p_majority` | Probability of winning a majority alone (Victoria ≥ 45 of 88; SA ≥ 24 of 47) |

**`run_metadata.json`** — model name, run timestamp, git commit (`null` if run outside a checkout),
number of simulation runs, random seed, noise parameters, and the provenance of every input dataset
(for AEC downloads the `manifest.json` source and retrieval date; polls, candidate lists and flow
estimates as models add them).

---

## Benchmarks

The 2026 result is only known after election day (Saturday 28 November 2026), so models are
first scored on 2022 backtests, then frozen and scored on 2026.

| ID | Name | What the model is given | What it tests |
|---|---|---|---|
| **B2** | 2022 forecast | Only information available before 28 Nov 2022 (2018 results on 2022 boundaries, final 2022 polls, 2022 candidate lists) | The full pipeline, including primary-vote modelling |
| **B3** | Counterfactual flows | The 7 districts whose ballots were data-entered in 2022 (Brighton, Hawthorn, Melton, Northcote, Point Cook, Preston, Werribee) | Whether the model's flows are right for exclusions that **didn't** happen in the official count (e.g. Liberal votes when the Liberal is excluded). Requires the ballot-level files from the VEC. |
| **B4** | 2026 live | Model frozen before election day (tagged commit) | The real thing |
| **B5** | Vic 2022 federal → state | 2022 federal booth results mapped into state districts, final 2022 state polls; no state results | **Lower bound** on error: short gap, similar flows, no One Nation. See [model3/BACKTESTS.md](model3/BACKTESTS.md#b5--victoria-2022-federal--2022-state-lower-bound) |
| **B6** | SA 2025 federal → 2026 state | 2025 federal booth results mapped into SA districts, final SA polls; no SA state results | **Realistic error** in a One Nation surge (22.9% statewide); compares rescaling and flow methods. See [model3/BACKTESTS.md](model3/BACKTESTS.md#b6--south-australia-2025-federal--2026-state-realistic-benchmark) |

B5 and B6 can be run by any model, not only model3. Their leakage rules and test modes (T1
primaries, T2 flows with actual primaries, T3 full pipeline) are defined in
[model3/BACKTESTS.md](model3/BACKTESTS.md).

## Metrics

All metrics are computed against the electoral commission's declared results (VEC or ECSA; full
2CP distribution where available).

The three headline metrics, **raw seat count**, **Brier score** and **log loss**, are defined and
implemented in [`../benchmarking/README.md`](../benchmarking/README.md), which also holds the results
table. The following are additional diagnostics:

| Metric | Definition | Better |
|---|---|---|
| **Final-two accuracy** | Share of districts where the two most likely finalists were the actual final two | Higher |
| **2CP margin MAE** | Mean absolute error of the median 2CP share, over districts where the final two was predicted correctly | Lower |
| **Seat-count error** | \|seats_p50 − actual seats\| per major party; and whether the actual total falls within p10-p90 | Lower / inside |
| **Calibration** | Bin p_win into 0-10%, 10-20%, …; compare mean predicted vs observed win rate per bin | Closer to diagonal |
| **Three-way seat Brier** | Brier score restricted to districts where ≥ 3 candidates were within 10 points at the core stage | Lower |

The three-way seat Brier is reported separately because those seats are where models are expected
to differ most, and they are diluted in the 88-seat average.

Optional diagnostics (primary MAE by party, three-candidate-set accuracy, final-pair accuracy, flow
error) are defined in [model3/BACKTESTS.md](model3/BACKTESTS.md#metrics) and should be reported
for B5 and B6.
