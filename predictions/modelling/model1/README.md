# Model 1 — "Nothing Changes" Baseline

**Status:** implemented (`model1.py` and `run_model1.py` in this folder). A deliberately
primitive baseline that the other models must beat.

## Idea

Take the most recent federal election, put every polling place's votes into the state district it
sits in, and replay each district's preferential count **assuming nothing changes**: the same parties
stand, voters give the same first preferences and the same preferences. Small random noise around
those inputs turns the single replay into seat probabilities.

There is no polling, no swing and no candidate information. It should do reasonably well when the
federal and state elections are close together and nothing unusual happens (Victoria 2022, six months
apart), and badly when something big has changed (One Nation in 2026).

## Method

1. **District votes.** Federal polling places are assigned to state districts by location
   (`booth_flows`): booths inside the district and within 1 km of their own federal division. Each
   district's first preferences are the sum of those booths' votes by party group. Declaration votes
   (absent, postal, provisional, declaration pre-poll) have no location and are left out; vote shares
   are what matter, so this only matters if those voters differ.
2. **Preferences.** The AEC publishes, for every booth, how each party's ballots split between that
   division's final two. From every split statewide, a Bradley-Terry strength is fitted for each
   (from-party, to-party) pair, so that, for example, Greens voters' strengths for Labor and Liberal
   reproduce the observed 80/20 split. When a party is excluded, its votes go to the continuing parties
   in proportion to these strengths (Luce's choice rule). This gives a transfer for **any** set of
   continuing parties, including combinations never seen federally.
   - A party never seen as a final-two recipient gets a small strength (`UNOBSERVED_WEIGHT` = 0.02,
     against observed strengths that sum to 1).
   - A party whose own transfers were never observed uses strengths pooled over all parties.
3. **Count.** Each district is counted with `run_irv_from_transfer_matrix` (full count to the final two).
4. **Monte Carlo** (1,000 runs, seed 1). In each run every party's vote is multiplied by a statewide
   factor (shared by all districts, log-sd 0.08) and a district factor (log-sd 0.12), and every
   party's attractiveness as a preference recipient by a statewide factor (log-sd 0.15). The noise
   sizes are placeholders, not fitted (`NOISE` in `model1.py`; `--noise-state`, `--noise-seat` and
   `--noise-flow` on the command line).

Independents are one `IND*` group, so a federal independent's vote stays in the district as an
"independent" even if no independent stands at state level. That is the "nothing changes" assumption
taken literally, and it is this model's biggest weakness.

## Running

```bash
.venv/bin/python predictions/modelling/model1/run_model1.py "VIC2022 (2022)" "SA2026 (2025)"   # selected runs (quote the names)
.venv/bin/python predictions/modelling/model1/run_model1.py --all            # every run, scored where the election has happened
```

Runs are defined in `RUNS` in `src/vic_election/config.py` (state, federal election, state election date,
winners), shared with `scripts/check_booth_assignment.py`. Inputs: AEC polling-place results (`fetch_aec_event`), AEC national division boundaries and
state district boundaries (cached by `vic_election.geo`), and declared winners
(`scripts/fetch_state_winners.py`). The full reproduction recipe is in the benchmark archive's
`reproduce.sh`.

## Outputs

`output/<run_id>/` holds the standard files from [`../README.md`](../README.md#standard-outputs).
`candidate` is the party-group label and `party` the group code, because this model forecasts parties.
Extra files: `district_primaries.csv` (the replayed first preferences) and, for scored runs,
`scores.json`.

| Run | Federal votes | Scored against |
|---|---|---|
| `VIC2022 (2022)` | May 2022 (AEC event 27966) | VEC 2022 declared winners |
| `NSW2023 (2022)`, `QLD2024 (2022)`, `WA2025 (2022)` | May 2022 | The next state election in each state |
| `SA2026 (2025)` | May 2025 (AEC event 31496) | SA 2026 declared winners |
| `VIC2026 (2025)` | May 2025 | Not yet (election 28 Nov 2026) |

Results for every run, with analysis, are in
[`../../benchmarking/archive/2026-11-08_model1/WRITEUP.md`](../../benchmarking/archive/2026-11-08_model1/WRITEUP.md)
(a historical archive — it still includes elections dropped from the scored set).
Across the five scored runs the raw seat count ranges from 69% (NSW 2023) to 82% (Victoria 2022).
The SA 2026 run misses all four One Nation seats.

## Results

**2022 backtest (`VIC2022 (2022)`).** Same inputs as B5 but with no rescaling to polls (model3's
`R0`), so this is the no-change reference B5 is measured against. Metrics from
[`../../benchmarking/README.md`](../../benchmarking/README.md).

| Raw seat count | Brier | Log loss |
|---|---|---|
| 72 / 88 | 0.238 | 0.436 |

| Party | Mean seats (p10-p90) | Actual 2022 |
|---|---|---|
| Labor | 57.2 (52-63) | 56 |
| Liberal | 13.8 (8-20) | 19 |
| Independents | 7.2 (5-9) | 0 |
| Nationals | 6.5 (6-7) | 9 |
| Greens | 3.3 (3-4) | 4 |

Labor's seat total is close. Of the 16 misses, 9 are seats given to an independent because a
federal independent did well in the overlapping division (Helen Haines in Indi → Benambra, Ovens
Valley, Eildon; Zoe Daniel in Goldstein → Brighton, Sandringham; Monique Ryan in Kooyong → Hawthorn,
Kew; also Shepparton and South-West Coast). Every one was actually won by the Liberals or Nationals.
The other 7 are close Labor/Liberal seats (Caulfield, Croydon, Hastings, Pakenham, Polwarth),
Nationals vs Liberal (Euroa) and Labor vs Greens (Prahran).

**2026 forecast (`VIC2026 (2025)`, not a serious forecast), on the declared candidates.** Since
nominations closed (9 Nov 2026), each district's federal vote is restricted to the parties actually
standing (`data/2026/candidates_vic2026.csv`, `apply_state_field` in `model1.py`): a federal party
with no state candidate has its votes handed on as if excluded first (to its Coalition partner if one
of the Liberals or Nationals is missing, otherwise by its fitted preferences); the pooled federal
independent vote is kept only where an independent stands; a party standing with no federal vote
in the district gets none. Labor 59.1, Liberal 10.2, Nationals 9.8, independents 6.8, Greens 2.1 mean
seats (before the declared field: 57.8, 9.2, 9.3, 9.0, 2.7). One Nation wins nothing, because it polled
about 6% at the 2025 federal election and this model ignores the state polls that put it near 22%.
`district_primaries.csv` keeps the raw federal vote (model2 reads One Nation's pattern from it);
`field_primaries.csv` is the vote after the field is applied, and `district_counts.json` feeds the
visualiser's Model 1 view. Frozen copy:
[`archive/2026-11-09_model1_candidates/`](../../benchmarking/archive/2026-11-09_model1_candidates/WRITEUP.md).

## Known limitations

- Ignores all change since the federal election: polls, swings, One Nation's rise.
- Federal independents are carried into state districts where they are not standing.
- Federal ≠ state: candidates, incumbency and party brands differ.
- Preferences are statewide, not local, and inherited votes follow the excluded party's preferences
  rather than their original party's.
- Noise sizes are guesses, so probabilities are not calibrated.
