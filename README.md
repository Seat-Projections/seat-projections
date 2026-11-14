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
| Leaflet | Map library (`visualiser/vendor/leaflet/`) | BSD-2-Clause |
| OpenStreetMap | Visualiser basemap tiles (loaded at runtime) | © OpenStreetMap contributors, ODbL |
