# Model 2 archive — 9 November 2026

Frozen results of [model2](../../../modelling/model2/README.md), the core-candidate heuristic:
minor candidates collapsed into the core (top four on primaries, plus credible independents), the core
contest resolved for whichever exclusion order each draw produces, with **origin tracking** (every
part of an excluded pile split by the flows of the party its votes started with). Luce preference
flows fitted to distributions of preferences. 5,000 Monte Carlo runs, seed 1, placeholder noise.

**Replay benchmarks were removed on 16 Nov 2026: they were given the actual primaries and did not
measure forecasting.** Forecast backtests (previous-election inputs only) are in
[`../../forecast_backtests.csv`](../../forecast_backtests.csv); this archive keeps the frozen
`VIC2026 (2022)` forecast only.

Reproduce with [`reproduce.sh`](reproduce.sh). `results.csv` has one row per run; `runs/` holds each
run's full outputs, including `core_stage.csv` (core flag and probability of being the first core
candidate excluded). Metrics are defined in [`../../README.md`](../../README.md).

## Runs

| Run | What it is |
|---|---|
| `VIC2026 (2022)` | Forecast for 28 November 2026: 2022 primaries, proportional swing to the polling average, One Nation on its 2025 federal booth pattern, six credible independents. |

## Choosing the count method

Three count methods were compared while model2 was being built. Origin tracking was what improved
the results, and counting every candidate added nothing once the core was wide enough: the only seat
a full count recovered was Finniss (SA 2026), won by an independent from fourth place, which a
top-three core cannot elect. A top-four core recovers it. Model 2 is therefore `origin` with a
top-four core; the other methods were removed from the code. The replay scores that comparison used
are gone with the replays.

## VIC2026 (2022) — forecast, not yet scored

Polling average (each pollster's latest eligible poll within 35 days of 5 Nov 2026, normalised):
Labor 22.7, Coalition 30.7, One Nation 22.0, Greens 14.9, others 9.7.

| Liberal | Labor | One Nation | Greens | Nationals | Independents | P(Liberal ≥ 45) |
|---|---|---|---|---|---|---|
| 42.2 (p10-p90 30-54) | 18.9 (8-31) | 11.1 (3-20) | 7.7 | 7.6 | 0.7 | 40% |

28 of 88 seats have no candidate above 60%. Placeholder parameters (noise sizes, One Nation flow
priors, One Nation geographic elasticity) dominate these numbers.

**Reproducibility fix in this archive.** Regional deviations used to be drawn in the iteration order
of a Python `set`, which changes between processes, so the same seed gave slightly different 2026
results run to run. They are now drawn in sorted order; two runs with different hash seeds give
byte-identical outputs.

## Known limitations

- Removed 2022 independents' votes are shared out in proportion (e.g. Shepparton, Mildura).
- Candidate lists for 2026 are 2022's plus One Nation in every seat until the VEC ballot draw.
- Liberal ↔ One Nation splits in the 2026 forecast are priors; SA 2026 and QLD 2024 now give fitted
  estimates that could replace them.
- Pile flows: a later exclusion's pile includes inherited votes, so fitted flows mix origins, and
  origin tracking then applies them as if they were pure.
