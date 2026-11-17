# Victorian State Election 2026 — Preferential Voting Forecasts

Seat-by-seat forecasting for the Victorian Legislative Assembly (88 single-member districts), built on
an exact Instant-Runoff Voting (IRV) counting engine verified to the vote against every Victorian
Electoral Commission (VEC) count in 2018 and 2022.

- **Counting engine and shared code:** `src/vic_election/` (IRV count, ballot decomposition, VEC/AEC data,
  boundaries; `config.py` holds the repository paths, AEC event IDs and benchmark run definitions).
- **Models:** `predictions/modelling/` (one folder per model; `model1` is a "nothing changes" baseline, `model2` a core-candidate heuristic on 2026 polls).
- **Benchmarks:** `predictions/benchmarking/` (raw seat count, Brier score, log loss against past state
  elections; frozen, reproducible results in `archive/`).
- **Visualiser:** `visualiser/` (map of the 88 districts with every 2025 federal polling place, and a
  Model 1 and Model 2 views of the 2026 forecast: win chances, estimated 2CP and the count stage by stage per district).
- **Public site:** `site/` (static pages for [seatprojections.au](https://seatprojections.au), deployed by
  GitHub Pages; `scripts/build_site.py` regenerates `site/data/` from the repo's data).

Forecasts for the 28 November 2026 election will be committed and tagged before election day (benchmark
B4); the git history is the record of what was frozen when.

## Setup

```bash
uv venv .venv && uv pip install -e ".[dev]"
.venv/bin/pytest -q
```

Raw downloads are not committed. `predictions/benchmarking/archive/*/reproduce.sh` downloads every
input (cached under `data/`) and reruns the models; `data/federal/*/manifest.json` records the URL,
size and SHA-256 of every AEC file used.

## Reproducing the results

All commands run from the repository root with the `.venv` from the setup step.

**1. Download the inputs** (~950 MB of raw files, downloaded once and cached under `data/`; none are committed):

```bash
.venv/bin/python scripts/fetch_vec_2022.py            # VEC 2022 results + distributions of preferences
.venv/bin/python scripts/fetch_vec_2018.py            # VEC 2018 results
.venv/bin/python scripts/fetch_aec.py                 # AEC federal booth results/boundaries (2022 + 2025)
.venv/bin/python scripts/fetch_state_winners.py       # declared winners for the other benchmark states
.venv/bin/python scripts/fetch_state_dops.py          # other states' distributions of preferences
.venv/bin/python scripts/fetch_vic2026_candidates.py  # 2026 VEC candidate nominations
.venv/bin/python scripts/build_district_flows.py      # booth-level preference flows per state district
.venv/bin/python scripts/build_notional_2018.py       # notional 2018 results on 2022 boundaries
```

**2. Verify the count engine** (reproduces all 88 VEC 2022 distributions to the vote):

```bash
.venv/bin/python scripts/verify_counts.py --year 2022
.venv/bin/python scripts/verify_counts.py --year 2018
.venv/bin/python scripts/verify_counts.py --year 2018 --district Melton   # inspect one district
.venv/bin/python scripts/check_booth_assignment.py                      # booth → district mapping checks
```

**3. Run the models** — outputs land in `predictions/modelling/<model>/output/<run_id>/`:

```bash
.venv/bin/python predictions/modelling/model1/run_model1.py --all               # every benchmark run
.venv/bin/python predictions/modelling/model1/run_model1.py "VIC2022 (2022)"    # a single run
.venv/bin/python predictions/modelling/model2/run_model2.py --all               # default 5000 sims, seed 1
```

Model 2's `"VIC2026 (2022)"` forecast requires model 1's `"VIC2026 (2025)"` output first (its One
Nation pattern), plus `data/2026/candidates_vic2026.csv`, `independents_vic2026.csv` and
`polls_vic2026.csv`. The forecast-history snapshots behind the site's date slider are
`run_model2.py --snapshots` (every 14 days from 2026-09-01, skipping dates with no new polls) or
`--as-of YYYY-MM-DD` for a single date; outputs land in
`predictions/modelling/model2/output/VIC2026 snapshots/<date>/`.

**4. Score and archive:**

```bash
.venv/bin/python scripts/score_model.py <run>/seat_probabilities.csv --year 2022
.venv/bin/python scripts/archive_benchmarks.py model1
```

**5. Reproduce an archived forecast exactly:**

```bash
bash predictions/benchmarking/archive/<run>/reproduce.sh
```

The seed and settings are recorded in each run's `run_metadata.json`. Note that
`data/2026/polls_vic2026.csv` is the committed snapshot the archived forecast used — re-downloading
the register from electiontracker.au fetches a newer poll set and produces different numbers; only
refresh it to make a new forecast.

**6. Build and preview the site:**

```bash
.venv/bin/python scripts/build_site.py && .venv/bin/python -m http.server 8000 -d site   # → localhost:8000
.venv/bin/python scripts/build_visualiser.py && .venv/bin/python -m http.server 8001 -d visualiser
```

## How to credit

When reusing our forecasts, analysis or derived data, credit **Seat Projections**, link to
the source page and the [CC BY-SA 4.0 licence](https://creativecommons.org/licenses/by-sa/4.0/),
and state whether you made changes. Include the forecast date so readers can identify the version.

Suggested credit:

> Source: [Seat Projections](https://seatprojections.au), 2026 Victorian state election
> forecast dated [date]. Licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
> Reproduced without changes.

Replace the date and, if you adapted the material, replace the last sentence with a brief
description of your changes. Shared adaptations must use CC BY-SA 4.0 or a compatible licence.
Keep any applicable source credits for third-party data.

For code reuse, retain the copyright notice and MIT licence text from [`LICENSE`](LICENSE).
A link back to this repository is appreciated.

## License and data sources

- **Code:** MIT License ([`LICENSE`](LICENSE)).
- **Forecasts, results, writeups and derived data:** CC BY-SA 4.0 ([`LICENSE-DATA`](LICENSE-DATA)).

Third-party data used or included:

| Source | Used for | Terms |
|---|---|---|
| Australian Electoral Commission (results.aec.gov.au; AEC GIS boundaries) | Federal polling-place results, preference flows, division boundaries | © Commonwealth of Australia (Australian Electoral Commission), CC BY 4.0 |
| Victorian Electoral Commission (vec.vic.gov.au) | 2018 and 2022 Victorian results and distributions of preferences (`data/2018`, `data/2022`); 2026 candidate list, names and parties only (`data/2026/candidates_vic2026.csv`) | © State of Victoria (Victorian Electoral Commission); see vec.vic.gov.au copyright terms |
| Electoral Boundaries Commission (Victoria) | 2021 redivision district boundaries (`data/boundaries/vic_assembly_2022/`) | © State of Victoria; see ebc.vic.gov.au copyright terms |
| Geoscape Administrative Boundaries (data.gov.au) | NSW, QLD, WA and SA state district boundaries (downloaded, not committed) | Incorporates or developed using Administrative Boundaries © Geoscape Australia licensed by the Commonwealth of Australia under CC BY 4.0 |
| electiontracker.au | 2026 Victorian polling register (`data/2026/polls_vic2026.csv`) | Compiled from published polls; see electiontracker.au |
| Wikipedia | Declared winners for NSW, QLD, WA and SA elections (`data/benchmarks/winners/`, each row cites its page) | Facts compiled from pages under CC BY-SA 4.0 |
| Leaflet | Map library (`visualiser/vendor/leaflet/`, `site/vendor/leaflet/`) | BSD-2-Clause |
| Inter & Newsreader | Self-hosted site fonts (`site/assets/fonts/`) | SIL Open Font License 1.1 |
| OpenStreetMap | Visualiser basemap tiles (loaded at runtime) | © OpenStreetMap contributors, ODbL |
