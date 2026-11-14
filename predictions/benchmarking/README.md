# Benchmarking

Every model writes a standard `seat_probabilities.csv` (see
[`../modelling/README.md`](../modelling/README.md#standard-outputs)): for each district, a probability
for each candidate (or party group) to win. These three metrics score that file against the declared
result.

## Metrics

| Metric | Definition | Range | Better |
|---|---|---|---|
| **Raw seat count** | Number of districts where the candidate given the highest probability actually won, out of all districts (88 in Victoria) | 0–88 | Higher |
| **Brier score** | For each seat, add up (p − o)² over the candidates, where p is the probability given to a candidate and o is 1 if they won and 0 if not. Average across seats. | 0–2 | Lower (0 is perfect) |
| **Log loss** | The average of −ln(p) for the candidate who actually won | 0–∞ | Lower (0 is perfect) |

Details:

- **Missing outcomes.** A candidate the model gave no row counts as p = 0, so a winner the model
  ignored scores (0 − 1)² = 1 in the Brier sum.
- **Log loss floor.** A winner with p = 0 would make log loss infinite, so p is floored at **0.001**
  (a cost of 6.9 for that seat).
- **What the metrics reward.** The raw seat count only looks at the favourite. Brier and log loss also
  reward calibrated confidence: a 55% call that loses costs little, a 99% call that loses costs a lot
  (log loss punishes it much harder than Brier).
- **Matching.** Outcomes are matched by **party group** (`ALP`, `LP`, `NP`, `GRN`, `ON`, `IND*`, …)
  or by **candidate name**. Party matching suits models that forecast parties (model1); independents
  are a single `IND*` group, so a federal independent and a different state independent count as the
  same outcome.

## Running

```bash
.venv/bin/python scripts/score_model.py <run>/seat_probabilities.csv --year 2022 [--key party|candidate]
```

Prints the three metrics and writes `scores.json` next to the forecast. Code:
`src/vic_election/benchmark.py`; declared winners come from `data/{year}/distributions/official_{year}.json`.

## Benchmark elections

Runs are named `STATEyyyy (federal year)`: the state election, and the federal election whose
polling-place results feed the model. Each federal election is paired with the next state election
in each state held before the following federal election (SA 2026 is run from both 2022 and 2025).
Tasmania uses multi-member Hare-Clark and is excluded. Victorian winners come from the VEC; the others
from `data/benchmarks/winners/` (`scripts/fetch_state_winners.py`, totals checked against the official
results). The polling place → district assignment behind every run is checked in
[`booth_assignment_checks.md`](booth_assignment_checks.md) (`scripts/check_booth_assignment.py`).

| Run | State election | Seats |
|---|---|---|
| `QLD2020 (2019)` | Queensland, 31 Oct 2020 | 93 |
| `WA2021 (2019)` | Western Australia, 13 Mar 2021 | 59 |
| `SA2022 (2019)` | South Australia, 19 Mar 2022 | 47 |
| `VIC2022 (2022)` | Victoria, 26 Nov 2022 | 88 |
| `NSW2023 (2022)` | New South Wales, 25 Mar 2023 | 93 |
| `QLD2024 (2022)` | Queensland, 26 Oct 2024 | 93 |
| `WA2025 (2022)` | Western Australia, 8 Mar 2025 | 59 |
| `SA2026 (2022)` | South Australia, 21 Mar 2026 | 47 |
| `SA2026 (2025)` | South Australia, 21 Mar 2026 | 47 |

Since the May 2025 federal election the only state general elections have been Tasmania
(19 July 2025, Hare-Clark) and South Australia (21 March 2026).

## Results

| Model | Run | Raw seat count | Brier | Log loss |
|---|---|---|---|---|
| [model1](../modelling/model1/README.md) | `QLD2020 (2019)` | 50 / 93 | 0.751 | 1.688 |
| model1 | `WA2021 (2019)` | 20 / 59 | 1.193 | 3.029 |
| model1 | `SA2022 (2019)` | 37 / 47 | 0.359 | 0.906 |
| model1 | `VIC2022 (2022)` | 72 / 88 | 0.238 | 0.436 |
| model1 | `NSW2023 (2022)` | 64 / 93 | 0.507 | 1.282 |
| model1 | `QLD2024 (2022)` | 76 / 93 | 0.272 | 0.507 |
| model1 | `WA2025 (2022)` | 42 / 59 | 0.400 | 1.020 |
| model1 | `SA2026 (2022)` | 35 / 47 | 0.444 | 1.427 |
| model1 | `SA2026 (2025)` | 36 / 47 | 0.425 | 1.397 |

**Replay benchmark (B1).** The model is given each election's actual primaries and fits flows to that
election's own distributions of preferences, leaving out the scored district, so only the preference
model and the count are tested; scores are not comparable with the forecast runs above. Distributions
come from each commission (`scripts/fetch_state_dops.py`).

| Model | Run | Raw seat count | Brier | Log loss | Final-two accuracy | 2CP MAE |
|---|---|---|---|---|---|---|
| [model2](../modelling/model2/README.md) | `QLD2020 (B1)` | 91 / 93 | 0.049 | 0.162 | 98.9% | 1.37 |
| model2 | `WA2021 (B1)` | 59 / 59 | 0.001 | 0.004 | 100% | 0.75 |
| model2 | `SA2022 (B1)` | 46 / 47 | 0.012 | 0.017 | 95.7% | 0.87 |
| model2 | `VIC2022 (B1)` | 86 / 88 | 0.038 | 0.101 | 100% | 1.58 |
| model2 | `NSW2023 (B1)` | 92 / 93 | 0.026 | 0.045 | 97.8% | 0.90 |
| model2 | `QLD2024 (B1)` | 90 / 93 | 0.062 | 0.153 | 98.9% | 1.33 |
| model2 | `WA2025 (B1)` | 57 / 59 | 0.039 | 0.056 | 93.2% | 1.43 |
| model2 | `SA2026 (B1)` | 45 / 47 | 0.062 | 0.109 | 93.6% | 1.50 |
| *Baseline: primary leader wins* | all 579 seats | 549 / 579 | 0.104 | 0.358 | | |
| **model2** | **all 579 seats** | **566 / 579** | **0.038** | **0.089** | | |

The baseline gives the candidate leading on first preferences probability 1. Details and the
method comparison that settled model2 on origin tracking are in
[`archive/2026-11-09_model2/`](archive/2026-11-09_model2/WRITEUP.md).

Frozen results, with the analysis and a script to reproduce them, are archived in
[`archive/2026-11-08_model1/`](archive/2026-11-08_model1/WRITEUP.md) (2026 forecast re-run on the declared candidates in
[`archive/2026-11-09_model1_candidates/`](archive/2026-11-09_model1_candidates/WRITEUP.md)) and
[`archive/2026-11-09_model2/`](archive/2026-11-09_model2/WRITEUP.md) (2026 forecast re-run on the declared candidates in
[`archive/2026-11-09_model2_candidates/`](archive/2026-11-09_model2_candidates/WRITEUP.md)). Each model's live outputs are in
`predictions/modelling/<model>/output/` and are overwritten on every run; the archive is the frozen
copy. Archive a model's runs with `.venv/bin/python scripts/archive_benchmarks.py <model>`.

Reference points: always picking the 2022 winner's party with certainty would score 88, 0 and 0;
giving every seat a 50/50 between Labor and the Coalition would score about 0.5 (Brier) and 0.69
(log loss) where one of them won.
