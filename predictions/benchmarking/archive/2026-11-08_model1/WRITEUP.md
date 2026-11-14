# Model 1 benchmark archive — 8 November 2026

Frozen results of [model1](../../../modelling/model1/README.md) ("nothing changes": federal
polling-place votes added up inside each state district, the count replayed with federal preferences,
1,000 Monte Carlo runs, seed 1). Each run is named `STATEyyyy (federal year)` and is scored against
the next state election after that federal election. Metrics are defined in [`../../README.md`](../../README.md).

Reproduce everything with [`reproduce.sh`](reproduce.sh). `results.csv` has one row per run; `runs/`
holds each run's full outputs; `winners/` holds the declared winners used for scoring;
[`booth_assignment_checks.md`](booth_assignment_checks.md) checks the polling place → district
assignment behind every run.

## Results

| Run | State election | Gap | Seats | Raw seat count | Brier | Log loss |
|---|---|---|---|---|---|---|
| `QLD2020 (2019)` | Queensland, Oct 2020 | 1.5 years | 93 | 50 (53.8%) | 0.751 | 1.688 |
| `WA2021 (2019)` | Western Australia, Mar 2021 | 1.8 years | 59 | 20 (33.9%) | 1.193 | 3.029 |
| `SA2022 (2019)` | South Australia, Mar 2022 | 2.8 years | 47 | 37 (78.7%) | 0.359 | 0.906 |
| `VIC2022 (2022)` | Victoria, Nov 2022 | 6 months | 88 | 72 (81.8%) | 0.238 | 0.436 |
| `NSW2023 (2022)` | New South Wales, Mar 2023 | 10 months | 93 | 64 (68.8%) | 0.507 | 1.282 |
| `QLD2024 (2022)` | Queensland, Oct 2024 | 2.4 years | 93 | 76 (81.7%) | 0.272 | 0.507 |
| `WA2025 (2022)` | Western Australia, Mar 2025 | 2.8 years | 59 | 42 (71.2%) | 0.400 | 1.020 |
| `SA2026 (2022)` | South Australia, Mar 2026 | 3.8 years | 47 | 35 (74.5%) | 0.444 | 1.427 |
| `SA2026 (2025)` | South Australia, Mar 2026 | 10 months | 47 | 36 (76.6%) | 0.425 | 1.397 |
| `VIC2026 (2025)` | Victoria, Nov 2026 | 19 months | 88 | not yet | | |

Which elections are included:

- **After the 2019 federal election** (18 May 2019), only Queensland, WA and SA voted before the 2022
  federal election. Victoria (Nov 2022) and NSW (Mar 2023) are paired with 2022 instead; NSW's March
  2019 election came before the federal one.
- **After the 2022 federal election**, every mainland state; SA's next election (2026) also follows
  the 2025 federal election, so it is run from both.
- **Tasmania** is excluded throughout: its multi-member Hare-Clark electorates cannot be represented
  by this single-member model.

## Seat totals (model mean vs actual)

| Run | Model | Actual |
|---|---|---|
| `QLD2020 (2019)` | LNP 73.7, ALP 16.3, KAP 3.0 | ALP 52, LNP 34, KAP 3, GRN 2, ON 1, IND 1 |
| `WA2021 (2019)` | LP 40.9, ALP 18.1 | ALP 53, NP 4, LP 2 |
| `SA2022 (2019)` | ALP 25.1, LP 18.9, Centre Alliance 3.0 | ALP 27, LP 16, IND 4 |
| `VIC2022 (2022)` | ALP 57.2, LP 13.8, IND 7.2, NP 6.5, GRN 3.3 | ALP 56, LP 19, NP 9, GRN 4 |
| `NSW2023 (2022)` | ALP 50.1, LP 21.5, NP 14.3, IND 6.9, GRN 0.2 | ALP 45, LP 25, NP 11, IND 9, GRN 3 |
| `QLD2024 (2022)` | LNP 54.0, ALP 28.6, GRN 6.6, KAP 3.0, IND 0.7 | LNP 52, ALP 36, KAP 3, GRN 1, IND 1 |
| `WA2025 (2022)` | ALP 40.7, LP 15.5, IND 2.8 | ALP 46, LP 7, NP 6 |
| `SA2026 (2025)` | ALP 34.4, LP 8.9, Centre Alliance 3.7 | ALP 34, LP 5, ON 4, IND 4 |

## What the results show

- **A no-change model fails when state and federal politics diverge.** The 2019 federal election was
  a Coalition win, strongest in Queensland and WA; the next state elections there were Labor
  landslides (WA 2021: 53 of 59 seats during COVID). Model 1 called both for the conservatives
  (20/59 in WA, log loss 3.0). Where federal and state moods matched (Victoria 2022, Queensland 2024,
  SA 2022) it reaches about 80%.
- **Independents at the wrong level.** Federal independents are carried into state seats where they
  are not standing (Victoria 2022: 9 of 16 misses), state-only independents are invisible (NSW 2023:
  9 elected), and Centre Alliance's federal vote in Mayo gives it 3–4 SA seats it did not contest.
- **One Nation's surge is invisible.** SA 2026: One Nation won 4 seats on 22.9%; the model gave none.
- **Coalition partners differ by level.** WA 2025: the Nationals won 6 seats the model gave to the
  Liberals, because the WA Nationals barely contest federal seats.
- **Probabilities are overconfident.** Log loss above 1 in six runs; the noise sizes are placeholders.

## Booth assignment checks

Full report: [`booth_assignment_checks.md`](booth_assignment_checks.md). In every run the district
totals add up exactly to the counted booth votes, every district has at least one counted booth, and
every federal division has a boundary. 93.7–96.8% of polling-place votes are counted. Problems found
and fixed while preparing this archive:

- **Enclaves.** Queensland's Bundaberg district sits entirely inside Burnett. Holes were not being
  subtracted, so 18–22 Bundaberg booths were inside both polygons (assigned correctly only because
  "Bundaberg" sorts first). Shapefile holes are now subtracted.
- **WA 2021 names.** Geoscape's pre-2023 WA names carry region suffixes ("Churchlands, Nm"); these
  are now stripped so districts match the declared winners.

Remaining flags, all judged genuine rather than errors:

- **Doubleview (WA 2021)** sits on the Churchlands/Scarborough boundary and falls inside both after
  boundary simplification (2,824 votes; assigned to Churchlands).
- **North West Central (WA 2021)** has a third of the median counted vote: it is a vast remote seat
  with far fewer electors, by design.
- **Caulfield (Victoria 2025 votes)** has 37% of the median counted vote: few federal polling places
  sit inside it (12,310 votes from Goldstein and Macnamara booths).

## Data sources

- Federal: AEC Tally Room polling-place two-candidate-preferred flows (events 24310, 27966, 31496);
  AEC division boundaries (2019: state files for QLD 2018, WA 2016 and SA 2018; 2022 and 2025:
  national MID/MIF).
- State boundaries: Victoria, Electoral Boundaries Commission (2021 redivision); NSW, QLD, WA, SA,
  Geoscape Administrative Boundaries (data.gov.au, CC BY 4.0), versions in force on each election day.
- Winners: VEC 2022 parsed results; Wikipedia post-election pendulums (QLD 2020, NSW 2023, QLD 2024)
  and members-elected tables (WA 2021, SA 2022, WA 2025, SA 2026), each checked against official seat
  totals before scoring.
