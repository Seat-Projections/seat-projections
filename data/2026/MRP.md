# Midyear MRP comparison: input preparation

Status: the YouGov-only regional comparison and seat scenario are complete.
RedBridge's full table has now been recovered, but the published comparisons
still use YouGov alone. The published forecast has not changed. This analysis
uses primary votes, not MRP winners or preference flows.

## YouGov

The Common Threads report supplies all 88 districts on pages 29 to 32.
Fieldwork ran from 16 June to 10 July 2026, with 4,003 respondents.

[Source report](https://actionnetwork.org/user_files/user_files/000/146/615/original/yougov-vic-mrp-treaty-report-state-voting-intetion-treaty-support.pdf)

Save the PDF as `data/2026/raw/mrp/yougov.pdf`, then run:

```sh
python scripts/extract_yougov_mrp.py
```

Requires Poppler's `pdftotext`. The output is
`data/2026/raw/mrp/yougov_primaries.csv`. Raw inputs and this extraction remain
ignored by Git. The script validates the district names against the boundary
file and preserves the seven reported primary-vote columns.

The printed percentages are rounded. Row totals range from 98% to 101%.
Normalisation will be required before combining them. The report gives Labor
0% in Narracan, so multiplicative updating alone would keep Labor at zero.
That entry needs an explicit treatment before a candidate-level forecast.

## RedBridge / Accent

The full seat-level primary-vote table is available from the public
[Datawrapper dataset](https://datawrapper.dwcdn.net/NunPy/2/dataset.csv)
embedded in the AFR's 16 July article. The dataset was located through an
archived copy of the article's chart metadata. It supplies Labor, Coalition,
Greens and One Nation first preferences, plus a predicted winner, for every
seat. Others must be inferred as 100 minus the four published shares.

Fetch it into `data/2026/raw/mrp/redbridge_afr_primaries.tsv`. Keep the raw
file out of Git because it reproduces a paywalled publisher's table. SHA-256:
`ea1e4e74f67452c610aa5ef94e5fbd47b48d4f075d5fbe9c8ca56a3a593e3916`.

Validation on 18 November 2026:

- exactly 88 populated district rows and no unknown or missing district names;
- four article category rows, which are not data;
- all four-party row totals are between 70% and 100%, leaving a nonnegative
  residual for Others;
- predicted winners total Labor 35, Liberal 33, Nationals 6, One Nation 12
  and Greens 2, exactly matching the AFR's median-case totals;
- the unweighted four-party means are Labor 25.69%, Coalition 26.30%,
  Greens 12.39% and One Nation 27.20%.

[The Tally Room's analysis](https://www.tallyroom.com.au/65163) independently
says it used all 88 seats. Its downloadable charts contain statewide scenarios
and seat totals rather than this underlying district table.

The AFR says the MRP surveyed about 6,500 people in June and July while a
Financial Review/RedBridge/Accent survey was in the field. The existing June
AFR and July Trades Hall poll-register entries should therefore not be counted
as independent polls. The article's Greens figure varies between 12% and 13%
in public accounts; the district table's own figures must be used.

## Polling alignment

A provisional check uses the existing polling-average rule: latest eligible
poll per pollster within 35 days of the newest eligible poll, with fieldwork
ending at least two days before the cutoff. Exclude both disputed RedBridge
entries from the independent midyear reference pending clarification.

At cutoffs of 30 June and 12 July, the remaining register supplies DemosAU
(11 June), Freshwater (8 June) and Resolve (12 June):

| Reference | Labor | Coalition | One Nation | Greens | Others |
|---|---:|---:|---:|---:|---:|
| Provisional midyear average | 23.33 | 27.67 | 24.00 | 13.67 | 11.33 |
| Current registered average at preparation | 21.90 | 31.30 | 21.60 | 14.30 | 10.90 |

These cutoffs are fieldwork-based proxies, not verified publication dates.
The midyear reference is only as complete as the existing poll register.

Run `python scripts/compare_yougov_mrp.py` after extraction. Outputs are
`predictions/benchmarking/yougov_regional_comparison.csv` and its JSON metadata
file. Seat rows are normalised to 100% and combined into the eight Legislative
Council regions, weighted by 2022 formal votes as a proxy for district size.
Independent, other-left and other-right votes are combined into Others.

The regional table is calibrated first to midyear polling, then current
polling, using iterative proportional fitting. Regional totals are preserved.
The published model's regional primary estimates are also calibrated to the
same current statewide target so the comparison isolates geography.

With this multiplicative method, calibration through the intermediate polling
target gives the same final result as calibration directly to current polling.
The script checks this. Midyear polling is an audit step, not an extra source
of regional information. No regional shrinkage or time decay has been applied.

Largest differences at the same statewide target:

- Southern Metropolitan: Greens 15.4% versus the model's 20.5%, Coalition
  41.0% versus 38.4%.
- Western Metropolitan: Greens 15.4% versus 11.4%.
- North-Eastern Metropolitan: One Nation 18.3% versus 15.5%.
- South-Eastern Metropolitan: Greens 12.5% versus 9.9%.
- Northern Metropolitan: Labor 26.4% versus 24.3%.

These are regional primary-vote differences, not changes in expected seats.
Aggregation avoids making a seat forecast directly from rounded MRP rows,
including Narracan's zero Labor entry, but does not remove the underlying
limitations of the source.

## Separate seat scenario

Run `python scripts/run_yougov_scenario.py` after the comparison script.
Outputs go only to
`predictions/modelling/model2/output/VIC2026 (YouGov regional)/`.
The website and the published state forecast are not rebuilt.

This scenario fits fixed region/party-group multipliers to the published
forecast's mean district primaries. They match the YouGov regional targets
above at current polling. The same multipliers are then applied to each
ordinary forecast draw and the district shares normalised to 100%.
Within-region local differences remain. The preference model, uncertainty
settings, 5,000 simulations and seed 1 remain the same.

All candidates receive their group adjustment, including independents within
Others. Independent priors are drawn as usual, but their resulting shares can
change after adjustment. This is a material assumption, particularly for
Footscray. It does not constitute candidate-specific evidence from the MRP.

| Bloc | Published mean seats | MRP scenario mean seats |
|---|---:|---:|
| Coalition | 52.25 | 50.70 |
| Labor | 18.10 | 20.45 |
| One Nation | 8.72 | 9.19 |
| Greens | 7.92 | 7.29 |
| Independents | 1.00 | 0.38 |

The Coalition wins a majority in 74.76% of scenario draws, compared with
79% in the published forecast. Sixteen districts change their favourite,
including several contests where the new favourite has less than 50% chance.
Large changes include Greens win chances in Albert Park (49.78% to 6.38%)
and Footscray (32.56% to 77.24%), and One Nation in Mill Park (22.34% to 50.70%).

The simulated mean regional shares are within 0.052 percentage points of
the requested regional targets. Targets are not forced on each draw, so
regional uncertainty is retained. No additional uncertainty for the MRP
estimation or its age is included. These probabilities are scenario results,
not a better-calibrated forecast.

This is an assumption that local patterns persist, not evidence that they do.
Keep the comparison separate from the published forecast until it is reviewed.

## Combined YouGov + RedBridge seat scenario

Run `python scripts/compare_combined_mrp.py`, then
`python scripts/run_yougov_scenario.py combined`. Output:
`predictions/modelling/model2/output/VIC2026 (MRP combined regional)/`.
Same method as the YouGov-only scenario, with the 50/50 combined regional
targets. Mean seats: Coalition 51.03, Labor 20.09, One Nation 9.31,
Greens 7.24, Independents 0.33. Coalition majority in 75.26% of draws.

## Partial, uncertain MRP scenario

`python scripts/run_yougov_scenario.py partial` writes
`predictions/modelling/model2/output/VIC2026 (MRP partial regional)/`.
Current polling sets the statewide level. Each simulation applies a random
fraction of the combined MRP regional adjustment, drawn per region and party
group from N(0.3, 0.3) and clipped to [-0.3, 1], plus extra regional noise
(log-sd 0.06). On average about 30% of the MRP signal is used, with wide
uncertainty because the MRPs are from June and July.
Mean seats: Coalition 51.74 (Liberal 43.0, Nationals 8.7), Labor 18.74,
One Nation 9.09, Greens 7.68, Independents 0.76. Coalition majority 77.46%.

## Uniform-swing MRP scenario (seat level)

`python scripts/run_yougov_scenario.py uniform` writes
`predictions/modelling/model2/output/VIC2026 (MRP uniform swing)/`.
The method used by DemosAU, RedBridge and The Tally Room: each district's
YouGov and RedBridge primaries are normalised and averaged 50/50, then one
additive statewide swing per party group moves them to current polling
(Labor -2.08, Coalition +5.04, Greens +2.07, One Nation -4.49, Others -0.54
points; floor 0.5%). The model's preference flows, candidate fields and
usual uncertainty then produce seat probabilities. The Coalition is split
into Liberal and National using the model's own shares within each seat.
Mean seats: Coalition 52.28 (Liberal 43.87, Nationals 8.41), Labor 20.93,
One Nation 9.49, Greens 5.28, Independents 0.02. Coalition majority 80.72%.
