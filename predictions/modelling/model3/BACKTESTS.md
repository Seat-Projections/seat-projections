# Model 3 — Backtests

Two backtests run the full model3 pipeline using only information that was available before a
real state election, then score it against the actual result. They bracket the error expected for
Victoria 2026:

| ID | Federal → state | Gap | Role |
|---|---|---|---|
| **B5** | Victoria: 2022 federal (21 May 2022) → 2022 state (26 Nov 2022) | ~6 months | **Lower bound** on error |
| **B6** | South Australia: 2025 federal (3 May 2025) → 2026 state (21 Mar 2026) | ~10.5 months | **Realistic error benchmark**, including a One Nation surge |

Victoria 2026 (28 Nov 2026) is ~19 months after the 2025 federal election, longer than either
backtest, and One Nation's state polling has kept rising since March. Both backtests should be read
as optimistic.

---

## B5 — Victoria 2022 federal → 2022 state (lower bound)

**Why it is a lower bound**

- Only six months between the two elections, so movement is small (state Labor fell ~6 points).
- Preference flows in May and November 2022 come from largely the same voters and similar
  how-to-vote cards, so flow error will look small.
- One Nation was negligible at both elections, so the hardest parts of the 2026 problem (where a
  surging party's vote comes from, and how it preferences) are not tested.

**What it does test**

- Booth → district assignment and declaration-vote spreading (S1-S2).
- The federal-state gap at seat level: incumbents, local candidates, state vs federal Labor.
- Rescaling of a moderate swing (S4) — expect R1-R3 to perform similarly.
- Minor-party and Greens flows (S5).
- Independents: the federal teals (Kooyong, Goldstein) vs state contests in Kew, Hawthorn and
  Brighton; state-only independents (Mornington, Benambra, Mildura, Shepparton).

**Facts**

- Boundaries: both elections use the 2021 redivision state boundaries (Vicmap `STATE_ASSEMBLY_2022`).
- Federal data: AEC Tally Room event `27966`.
- Actual state results: `data/2022/distributions/full_2cp_2022.json` (88/88 verified).
- Seats: 88, majority 45.

## B6 — South Australia 2025 federal → 2026 state (realistic benchmark)

**Why it is the main test**

- Same federal baseline year as Victoria 2026 (the May 2025 election).
- A One Nation surge comparable to Victoria's: from a small 2025 federal base to **22.9%** of the
  state primary vote.
- A collapsing Liberal vote (18.9%, −16.8), producing exactly the three-way problem model3 is
  built for. One Nation made the three-candidate stage in 40 of 47 seats; the final pair was
  ALP-ON in 25 seats.
- Full distributions of preferences are published for all 47 seats, so flow variants can be scored
  directly.

**Result to score against (House of Assembly, 21 Mar 2026)**

| Party | Primary % | Seats |
|---|---|---|
| Labor | 37.5 | 34 |
| One Nation | 22.9 | 4 |
| Liberal | 18.9 | 5 |
| Greens | 10.4 | 0 |
| Independent | 5.5 | 4 |

Seats: 47, majority 24.

**Caveats specific to SA**

- **Shorter gap** than Victoria 2026 (10.5 vs ~19 months).
- **Different state dynamics:** a dominant first-term Labor Premier and a weak Liberal brand. The
  Victorian picture (Coalition ahead, Labor in the low 20s) is different, so B6 tests the
  *methods*, not the specific swing.
- **SA ballot savings provision:** SA is full preferential, but incomplete ballots can be saved by
  following a registered party voting ticket. Part of SA's preference flow therefore follows
  tickets rather than voter choice. Confirm the share of ticket-saved votes before comparing
  flows, and treat this as a known difference from Victoria.
- **New boundaries:** the 2024 SA redistribution (EDBC report, December 2024) applies from 2026;
  use the 2026 boundaries, not the 2022 ones.
- **No ballot-level SA state data:** flows are scored against the published distributions, not
  against individual ballots.

---

## Leakage rules

A backtest is only valid if the model sees nothing from after the state election's information
cutoff.

| | B5 (Vic 2022) | B6 (SA 2026) |
|---|---|---|
| Cutoff | 25 Nov 2022 (day before polling) | 20 Mar 2026 (day before polling) |
| Federal results | AEC 2022 House booth files, Senate formal preferences | AEC 2025 House booth files, Senate formal preferences |
| Polls | Final pre-election state polls fielded before cutoff | Final pre-election SA polls fielded before cutoff |
| Candidates | VEC 2022 nominations (closed 11 Nov 2022) | ECSA 2026 nominations |
| How-to-vote cards | 2022 registered state cards | 2026 registered state cards |
| Previous state results | 2018 (not on 2022 boundaries; use only via notional estimates) | 2022 SA (use notional 2026-boundary estimates) |
| **Forbidden** | Any 2022 state result, booth or count | Any 2026 SA result, booth or count |

Independent priors must be set from information before the cutoff (previous results, incumbency,
media profile), not tuned to the result. Tuning any parameter on the scored election converts the
backtest into a fit; each parameter's source must be recorded in `run_metadata.json`.

---

## Test modes

Primary-vote error and flow error are measured separately, so a good result in one does not hide a
bad result in the other.

| Mode | Model is given | Model predicts | Isolates |
|---|---|---|---|
| **T1 Primaries** | Federal data + polls (S1-S4) | District primaries | Booth mapping, party mapping, rescaling |
| **T2 Flows** | **Actual** district primaries (oracle) + S5 preferences | Three-candidate set, final pair, 2CP share, winner | Preference model only |
| **T3 Full** | Everything permitted by the leakage rules | Standard outputs (probabilities) | The whole pipeline |

T2 is the "flow test": with primaries fixed at the truth, any error comes from the preference model.
It is the direct comparison of F0-F3.

---

## Experiment grid

| | F0 state 2CP flows | F1 booth DOPs | F2 Senate rankings | F3 origin-reweighted |
|---|---|---|---|---|
| **R0** no rescale | T3 | T3 | T3 | — |
| **R1** uniform | T3 | T3 | T3 | — |
| **R2** proportional | T3 | T3 | T3 | — |
| **R3** logit | T3 | T3 | T3 | — |
| **R4** transition | T3 | T3 | T3 | T3 |

- T1 is run once per R variant (flows do not affect primaries).
- T2 is run once per F variant (primaries are fixed at the truth). F3 in T2 needs a transition
  matrix, so it uses R4's matrix.
- **model2** is scored on the same T3 inputs for comparison.
- R4/F3 require crosstabs by past federal vote. If no pre-cutoff poll published them for a test,
  that cell is marked unavailable rather than estimated from the result.
- Optional add-ons scored separately: `S1b` (boundary splitting), `S2s` (Senate baseline), `+H`
  (how-to-vote adjustment).

---

## Metrics

The standard metrics in [`predictions/modelling/README.md`](../README.md#metrics) apply to T3. Additional
diagnostics:

| Metric | Mode | Definition |
|---|---|---|
| **Primary MAE by party** | T1 | Mean over districts of \|estimated − actual primary\| for each party, in points |
| **One Nation seat-level MAE** | T1 | As above, for One Nation only; reported separately because it drives B6 |
| **Top-three set accuracy** | T1 | Share of districts where the three highest estimated primaries are the actual top three |
| **Three-candidate-set accuracy** | T2, T3 | Share of districts where the predicted last three candidates match the count |
| **Final-pair accuracy** | T2, T3 | Share of districts where the predicted final two match the count |
| **2CP MAE** | T2, T3 | Mean absolute error of the final 2CP share where the final pair is correct |
| **Flow error** | T2 | For each excluded party and recipient pair observed in the count, \|predicted − actual split\| in points, vote-weighted |
| **Winner accuracy** | T2, T3 | Share of districts with the correct winner |

Results are reported for all seats and for **three-way seats** (three candidates within 10 points
at the three-candidate stage), since that is where variants are expected to differ.

---

## Using the results

1. **Pick the variant mainly on B6.** Rank R×F combinations by T3 Brier and log loss on B6, then
   check T1 (One Nation MAE) and T2 (three-candidate-set accuracy, flow error) to understand why.
2. **Check B5 does not regress.** A variant that wins B6 but is clearly worse on B5 is overfitting
   SA-specific behaviour.
3. **Calibrate S7 noise from residuals.** Seat- and regional-level primary residuals from T1 set the
   Monte Carlo spreads: B5 residuals are the floor, B6 residuals the central estimate, inflated for
   the longer Victorian gap (~19 vs ~10.5 months).
4. **Freeze.** Record the chosen variant, noise parameters and every input version, then run B4
   (Victoria 2026 live) from a tagged commit before 28 Nov 2026.

## Expected outcome (to be replaced by results)

- **B5:** small differences between R1-R3 and between F0-F2; most error from independents and
  candidate effects.
- **B6:** R0/R1 should do badly on One Nation geography; R3/R4 should do best. F0/F1 should miss
  splits in ALP-ON and LIB-ON contests; F2/F3 should recover them, subject to the SA ticket-vote
  caveat.
