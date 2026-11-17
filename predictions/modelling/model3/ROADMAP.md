# Model 3 — Code Roadmap

How model3 will be built, in the order that produces useful results earliest. Module and function
names are proposals to confirm at build time. Methodology is in [README.md](README.md), test
protocol in [BACKTESTS.md](BACKTESTS.md), data in [DATA.md](DATA.md).

**Timeline:** Victoria votes on 28 Nov 2026. B4 requires a frozen model before then, so steps 1-6
are the critical path; anything marked *optional* can wait.

---

## Modules

### `src/vic_election/aec.py` — AEC fetchers and parsers (**done** for fetching)

- Uses `CachedSession` from `http_cache.py` (download once, read locally unless `refresh=True`).
- `fetch_aec_event(event_id, out_dir, states, …)` downloads every House and Senate file listed in
  DATA.md; `read_aec_csv` reads the title-line-prefixed CSVs. Event IDs and states live in `config.py`.
- Still to write: `load_booth_primaries(path) -> dict[booth_id, dict[party, votes]]`;
  `load_booth_dops(dir) -> dict[booth_id, DistributionTable]`, reusing the existing model so the
  booth counts can be verified with `verify_distribution_table`;
  `iter_senate_ballots(zip_path) -> Iterator[(division, collection_point, party_ranking)]`, which
  streams the large CSV without loading it, collapsing below-the-line preferences to a party order.

### `src/vic_election/geo.py` and `booth_flows.py` — booth → district assignment (**done**)

- Pure Python (no GIS dependency): KMZ, MID/MIF and shapefile parsers, point-in-polygon with holes,
  ring simplification. `load_state_districts(state, date)` and `fetch_national_divisions(year)` load
  boundaries; `booth_flows.load_polling_places` and `assign_booths` place booths (point-in-polygon,
  snap-to-nearest fallback within `NEAREST_DISTRICT_MAX_KM`, own-division distance).
- `split_boundary_booths(...)` — *optional*, `S1b`; would need a real geometry library (`shapely`).

### `src/vic_election/ecsa.py` — SA 2026 results

- Fetch and parse ECSA House of Assembly results and distributions of preferences into
  `DistributionTable`, so `verify_counts.py` can check all 47 SA counts the same way it checks
  Victoria.
- Record ticket-saved vote counts where published.

### `src/vic_election/model3/`

| File | Contents |
|---|---|
| `primaries.py` | S2 aggregation (booths + spread declaration votes), S3 party mapping and independent handling |
| `rescale.py` | R0-R4: `rescale(primaries, target, method, regional_targets=None, transitions=None)` |
| `flows.py` | F0-F3: build per-district weighted party preference orders |
| `simulate.py` | S6 ballot construction + `run_irv_from_ballots`; S7 Monte Carlo; writes standard outputs |
| `backtest.py` | T1/T2/T3 scoring against a `DistributionTable` dataset; metrics from BACKTESTS.md |
| `config.py` | Per-test settings: cutoff dates and variant choices (event IDs, boundary paths and seat counts come from `vic_election.config`) |

A per-test config keeps Victoria and SA on the same code path:

```python
TESTS = {
    "B5": dict(event=27966, state="VIC", boundaries="data/boundaries/vic_assembly_2022", seats=88, cutoff="2022-11-25"),
    "B6": dict(event=31496, state="SA",  boundaries="data/boundaries/sa_assembly_2026", seats=47, cutoff="2026-03-20"),
    "VIC2026": dict(event=31496, state="VIC", boundaries="data/boundaries/vic_assembly_2022", seats=88, cutoff="2026-11-27"),
}
```

### Scripts

- `scripts/fetch_aec.py --year 2022 2025 --states VIC SA` (**done**)
- Boundaries download on first use (`geo.fetch_state_districts`, `geo.fetch_national_divisions`); SA 2026 boundaries still to add
- `scripts/fetch_ecsa_2026.py`
- `scripts/run_model3.py --test B5|B6|VIC2026 --variant R3F2 [--runs 20000 --seed 1]`
- `scripts/run_backtest.py --test B5|B6 --mode T1|T2|T3 --grid` (writes a comparison table to
  `predictions/modelling/model3/output/backtests/`)

### Tests (`tests/test_model3_*.py`)

- Booth assignment on a synthetic square-polygon fixture; snap fallback.
- Declaration spreading conserves each division's total votes.
- Each rescale method hits the statewide target exactly and keeps shares in [0, 1].
- Senate ballot parsing on a small fixture (above- and below-the-line).
- Flow builder: preference-order weights per party sum to 1.
- AEC booth DOPs and ECSA DOPs reproduce exactly through `verify_distribution_table` (same
  guarantee as the VEC data).
- Empirical, skipped when data is missing: sum of district primaries equals the state's federal
  total; every district receives at least one booth.

---

## Build order

| Step | Work | Output | Risk |
|---|---|---|---|
| 1 | **Done.** `aec.py` fetch (2019, 2022, 2025); boundary fetch; `geo.py` / `booth_flows.py` assignment | `data/federal/2025/booth_districts_VIC.csv`, `district_flows_VIC.json` | Done; 140 mobile/hospital teams have no coordinates |
| 2 | `primaries.py` + `rescale.py` (R0-R3); **B5 T1** | First error numbers (lower bound) | Medium; federal-independent handling |
| 3 | `ecsa.py`; SA boundaries; 2025 SA booth files; SA poll file; **B6 T1** | One Nation geography error in a real surge | Medium; ECSA format unknown |
| 4 | `flows.py` F0-F2 (Senate parsing); **B5/B6 T2** | Flow-variant comparison | Medium; Senate file size, SA ticket votes |
| 5 | R4 + F3 if crosstabs exist; `simulate.py` Monte Carlo; **B5/B6 T3** + model2 comparison | Variant choice, calibrated noise | Medium; crosstab availability |
| 6 | Victoria 2026 run with chosen variant; freeze (tagged commit, metadata) | **B4** forecast | Depends on 2026 candidate list timing |
| 7 | *Optional:* `S1b` catchment splitting, `S2s` Senate baseline, `+H` how-to-vote adjustment, blend with 2022 state baseline | Refinements scored on B5/B6 | Low priority |

Each step ends with its tests passing and, for steps 2-5, a short results section appended to
BACKTESTS.md (replacing the "Expected outcome" placeholders).

## Open decisions

- **Spatial dependency:** resolved for S1 (pure Python in `geo.py`); `shapely` only if `S1b` is built.
- **Where model3 code lives:** `src/vic_election/model3/` (importable, testable) is proposed over
  `predictions/modelling/model3/` scripts.
- **State-baseline blend:** whether the final model mixes the federal-derived estimate with a
  swing from the 2022 state result; decided by B5/B6 performance.
- **SA ticket votes:** whether to remove ticket-saved votes from the flow comparison or model them.
