# Model 3 — Data Register

Every input model3 needs, where it comes from, where it will be stored, and whether it may be used
in each backtest. Paths are relative to the repository root. "Leak date" is the date after which
data about the scored election exists; anything dated after a backtest's cutoff is forbidden in
that backtest (see [BACKTESTS.md](BACKTESTS.md#leakage-rules)).

## Federal election data (AEC Tally Room)

**Status: fetched** with `.venv/bin/python scripts/fetch_aec.py` (`src/vic_election/aec.py`). The
elections, states and event IDs are in `vic_election.config` (`AEC_EVENTS`, `AEC_STATES`): 2019 (event
24310) for QLD, WA and SA; 2022 (event 27966) for VIC, NSW, QLD, WA and SA; 2025 (event 31496) for VIC
and SA. Ballot-level Senate files are fetched for Victoria only. Model 3 uses the 2022 and 2025 Victorian
and 2025 SA files; the rest feed the model1 benchmarks. Every CSV and ZIP linked from the
House and Senate download menus is stored under its original AEC name; files published per state
are kept only for those states, national files are kept whole. `manifest.json` in each year folder
records the URL, size and SHA-256 of every file.

```
data/federal/{2019,2022,2025}/
  manifest.json
  house/     HouseStateFirstPrefsByPollingPlaceDownload-{event}-{STATE}.csv   booth primaries (ordinary votes)
             HouseDopByPPDownload-{event}-{STATE}/  (+ .zip)                  full distribution of preferences per booth, one CSV per division
             HouseTcpFlowByPPDownload-{event}-{STATE}/  (+ .zip)              per-booth flow from every candidate to the final two
             HouseTcpByCandidateByPollingPlaceDownload / HouseTppByPollingPlaceDownload   booth 2CP / 2PP (national files)
             HouseDopByDivisionDownload, HouseFirstPrefsByCandidateByVoteTypeDownload, flows by party/state, candidates, turnout, informal, …
  senate/    aec-senate-formalpreferences-{event}-{STATE}.zip                 every formal Senate ballot (kept zipped)
             first_prefs_by_polling_place/{STATE}/SenateDivisionFirstPrefsByPollingPlaceDownload-{event}-{divId}.csv
             SenateDopDownload-{event}.zip, SenateCandidatesDownload, first prefs by state/division/group/vote type, …
  general/   GeneralPollingPlacesDownload-{event}.csv                          booth IDs, type, address, latitude/longitude
             enrolment and declaration-vote files
  _menus/    cached download-menu pages
```

| Dataset | 2022 VIC | 2025 VIC | 2025 SA |
|---|---|---|---|
| Divisions | 39 | 38 | 10 |
| Polling places (incl. pre-poll centres, mobile teams) | 1,939 | 2,072 | 750 |
| Formal House votes | 3,746,433 | 4,053,064 | 1,132,238 |
| Share cast at a located polling place | 76.1% | 75.7% | 79.7% |
| Senate formal ballots (rows in the preference file) | 3.82 M | 4.10 M | 1.16 M |
| Files / size on disk | 98 files, ~182 MB with extracted booth zips | 111 files (VIC + SA), ~173 MB | (included) |

**What the booth files contain**

- **Booth distributions of preferences** (`HouseDopByPPDownload`): for every booth, the division's
  count replayed on that booth's ballots: preference count, transfer count and percentages per
  candidate per count. They follow the **division's** exclusion order, so they are not independent
  IRV counts per booth. Division-wide declaration votes appear as pseudo-booths with `PPId 0`
  named `ABSENT`, `POSTAL`, `PRE_POLL` and `PROVISIONAL`.
- **Booth 2CP flows** (`HouseTcpFlowByPPDownload`): for every booth and every candidate, how that
  candidate's ballots split between the division's final two. This is the per-booth preference
  flow table.
- Ordinary (located) votes are about 76-80% of the formal vote; the remainder (absent, postal,
  declaration pre-poll, provisional) is known only per division.
- Polling places without coordinates are only mobile and hospital teams (types 2-4): 7 in 2022 VIC,
  140 in 2025 VIC, 63 in 2025 SA, together under 1% of located votes. All fixed booths (type 1)
  and pre-poll centres (type 5) have coordinates.

**Checks** (`tests/test_aec.py`): for every division, booth-DOP first counts (booths plus
declaration pseudo-booths) equal the division's formal votes, and booth-level ordinary first
preferences equal the located booth totals. The booth-DOP final counts summed over booths also
equal the division-level distribution of preferences.

Notes: the AEC files begin with a title line before the CSV header. The vote-type and booth
first-preference files include an `Informal` pseudo-candidate row, which must be excluded when
totalling formal votes. Senate group order is in the header of each formal-preference file
(`A:Liberal/The Nationals,…`) and in `SenateCandidatesDownload-{event}.csv`.

Federal files are dated before both state elections, so all are permitted in both backtests.

## Boundaries

| Dataset | URL | Format | Used for | Path | Status |
|---|---|---|---|---|---|
| Victorian Lower House boundaries, 2021 redivision (used 2022 and 2026) | EBC: https://www.ebc.vic.gov.au/files/2021-boundaries/resources/New%20districts%20and%20regions.kmz (same boundaries as Vicmap `STATE_ASSEMBLY_2022`) | KMZ → GeoJSON (WGS84) | B5 and Victoria 2026 | `data/boundaries/vic_assembly_2022/districts.geojson` (88 districts, names match VEC) | **Have** (`src/vic_election/geo.py`) |
| AEC federal division boundaries (2021 redistribution → 2022 election; 2024/2025 → 2025; per-state 2016-2018 files → 2019) | https://www.aec.gov.au/Electorates/gis/gis_datadownload.htm (national MID/MIF zips; `geo.AEC_NATIONAL_DIVISIONS`, `geo.AEC_2019_DIVISIONS`) | MapInfo MID/MIF or ESRI shapefile, parsed in pure Python | Checks whether a booth lies in its own division (S1); one loader for the flow matrices, visualiser and every model1 run | `data/boundaries/federal/` (zips, cached) | **Have** (`geo.fetch_national_divisions`) |
| 2025 booth → state district assignment (VIC) | Derived: point-in-polygon on AEC coordinates, plus distance outside the booth's own federal division | CSV | Model3 S1 | `data/federal/2025/booth_districts_VIC.csv` (columns include `KmOutsideOwnDivision`, `CountedInDistrict`) | **Have**: 1,751 counted; 142 inside a district but more than 1 km outside their own division (pre-poll centres, CBD booths taking other divisions' votes: 172,386 votes); 1 within 5 km of a district (Albury PPVC); 38 EAV centres; 140 mobile/hospital teams without coordinates |
| Collated preference-flow matrices per state district | Derived from `HouseTcpFlowByPPDownload` + the assignment above (`src/vic_election/booth_flows.py`, `scripts/build_district_flows.py`) | JSON + long CSV | Model3 S5 (F1), visualiser district panel | `data/federal/{2022,2025}/district_flows_VIC.json`, `.csv` | **Have** for 2022 and 2025 (see below) |

**District flow matrices.** For each district, every counted booth's two-candidate-preferred flows are
summed by party (rows: the finalists' own votes, then each party group of excluded candidates; columns:
the finalist party groups). Summing counts weights each booth and each contributing federal division by
its votes. Each district also lists its contributing divisions (booths, votes, share, final two), each
distinct final-two pairing with its share, and a separate matrix per pairing when there is more than
one (34 of 88 districts in 2025), because a combined matrix mixes flows towards different pairs.
A cell is empty when that party was not in the final two at any booth where the row's votes were cast.
Independents and non-affiliated candidates are pooled into one `IND*` group; every pooled group lists
its candidates, and `merged` is set where several different independents were combined (36 districts
in 2025). Excluded booths and division-level declaration votes are listed per division
(`unlocated_by_division`) so they can be apportioned later. Counted votes: 2,874,969 of 3,069,088
booth votes in 2025 (93.7%); 2,675,801 of 2,849,569 in 2022 (93.9%).
| Victorian Upper House regions 2022 (`STATE_COUNCIL_2022`) | Vicmap Admin series | SHP | Regional poll calibration | `data/boundaries/vic_council_2022/` | Optional |
| SA House of Assembly boundaries 2026 (Geoscape Administrative Boundaries, Feb 2026 release) | https://data.gov.au/data/dataset/sa-state-electoral-boundaries | SHP (CC-BY 4.0) | B6 | `data/boundaries/sa_assembly_2026/` | To fetch |
| ABS mesh blocks + population | ABS ASGS | SHP + CSV | `S1b` catchment splitting | `data/boundaries/abs_meshblocks/` | Optional |

Before using the 2026 Victorian boundaries, confirm no redivision has occurred since 2022 (the EBC
states the 2021 boundaries apply until the 2030 writs unless triggered sooner).

## State results (scoring targets)

| Dataset | URL | Format | Path | Leak date | Status |
|---|---|---|---|---|---|
| VEC 2022 Lower House results and distributions | VEC results pages and indicative full-preference workbooks (`scripts/fetch_vec_2022.py`, `src/vic_election/data_fetcher.py`) | JSON (parsed) | `data/2022/distributions/` | 26 Nov 2022 | **Have** (88/88 verified) |
| ECSA 2026 House of Assembly results and distributions of preferences | https://result.ecsa.sa.gov.au/ | HTML/CSV (to confirm) | `data/sa2026/` | 21 Mar 2026 | To fetch; parse into `DistributionTable` |
| ECSA 2026 voting tickets (savings provision) | ECSA | PDF/HTML | `data/sa2026/tickets/` | Lodged before polling | To fetch; needed to interpret SA flows |
| SA 2022 results on 2026 boundaries (notional) | Antony Green / ECSA | HTML | `data/sa2026/notional_2022.csv` | Pre-cutoff | Optional (state-baseline blend) |

## Polls

| Dataset | Source | Use | Path | Status |
|---|---|---|---|---|
| Victorian 2022 final pre-election polls | Wikipedia "Opinion polling for the 2022 Victorian state election"; The Poll Bludger; pollster releases | B5 rescale target | `data/polls/vic2022.csv` | To compile (fielded before 25 Nov 2022 only) |
| SA 2026 final pre-election polls | Wikipedia SA 2026 polling page; Ace Strategies SA series; pollster releases | B6 rescale target | `data/polls/sa2026.csv` | To compile (fielded before 20 Mar 2026 only) |
| Victorian 2026 polls | plainpolitics.com.au/data/polls-victoria.csv, cross-checked with acestrategies.au/assets/dataviz-v6/victoria-polls-2026.csv | Victoria 2026 rescale target | `data/polls/vic2026.csv` | To compile |
| Crosstabs by past federal vote | DemosAU PDF reports; RedBridge/Accent reports where published | R4 transition matrix | `data/polls/transitions_{test}.csv` | To compile; may be unavailable for B5 |
| Regional splits | Roy Morgan (Upper House regions), DemosAU (Melbourne/regional) | Regional calibration | `data/polls/regional_{test}.csv` | To compile |

Poll-source rules (from the aggregator audit): use the pollster's own document where one exists;
remove duplicate entries of the same MRP; exclude party- or union-commissioned polls and MRPs from
the rescale target; record every row's source URL.

## Candidates and how-to-vote cards

| Dataset | Source | Path | Status |
|---|---|---|---|
| VEC 2022 candidate list | Already embedded in `data/2022/distributions/` | — | Have |
| ECSA 2026 candidate list | ECSA | `data/sa2026/candidates.csv` | To fetch |
| VEC 2026 candidate list | VEC nominations (close mid-Nov 2026) / electiontracker.au | `data/2026/candidates.csv` | To fetch when published |
| Registered how-to-vote cards (Vic 2022, SA 2026, Vic 2026) | VEC / ECSA | `data/htv/{test}/` | Optional (`+H` variant) |
| Independent priors | Compiled by hand from pre-cutoff information | `data/priors/independents_{test}.csv` | To compile; source recorded per row |
