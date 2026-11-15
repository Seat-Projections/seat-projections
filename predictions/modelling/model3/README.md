# Model 3 — Booth-Mapped Federal-to-State Model

**Status:** design — not yet implemented. Parameter values are placeholders until estimated on the
backtests in [BACKTESTS.md](BACKTESTS.md). Data sources are in [DATA.md](DATA.md) and the build
plan is in [ROADMAP.md](ROADMAP.md).

Model 3 is a standalone model: it has its own primary-vote estimates, preference model, count and
Monte Carlo, and it is scored against [model1](../model1/README.md) and [model2](../model2/README.md)
on the shared benchmarks.

## Idea

Statewide polls cannot say where One Nation's vote sits, and the 2022 state results cannot either,
because One Nation barely contested the Lower House in 2022 (8,077 votes). The most recent federal
election can: One Nation stood in every Victorian division in May 2025, and the AEC publishes every
result at **polling-place** level, including a full distribution of preferences for each booth and
every Senate ballot paper.

Model 3 therefore:

1. places each federal polling place inside the state district it falls in,
2. adds booth results up into state-district primaries,
3. rescales those primaries to the latest state polling,
4. attaches a preference model estimated from the same federal data,
5. runs the full preferential count in every district, many times, to get probabilities.

```
AEC booths ──geometry──▶ district primaries ──rescale to polls──▶ 2026 primaries ─┐
AEC booth DOPs + Senate ballots ──────────────▶ party preference orders ──────────┤
2026 candidate list + independent priors ─────────────────────────────────────────┤
                                                                                  ▼
                                   run_irv_from_ballots × N draws ──▶ seat probabilities
```

The methodology choices that matter most (how to rescale, and which flows to use) are left as
**variants** and are chosen by backtesting, not by assumption.

---

## S1 — Assign booths to state districts

- Input: AEC polling places with latitude/longitude, and the state district boundaries
  (`vic_election.geo`, pure Python: EBC KMZ for Victoria, Geoscape shapefiles for other states).
- Each booth is assigned to the district polygon that contains its point (`geo.assign_point`).
- Booths that fall outside every polygon (bad coordinates, offshore islands) are snapped to the
  nearest district within `geo.NEAREST_DISTRICT_MAX_KM` and logged; model1 does not count them.
- **Refinement (optional, variant `S1b`):** booths within ~1 km of a district boundary draw voters
  from both sides. Split their votes across districts by catchment, using Voronoi cells around
  booths intersected with district polygons and weighted by ABS mesh-block population.

- **Own-division check:** a booth serves voters of its own federal division. Booths more than
  **1 km** outside their own division (AEC division boundaries) are not placed by location: these are
  mostly pre-poll centres and CBD booths taking votes for other divisions, whose voters live elsewhere.
  Their votes join the division's unlocated pool with the declaration votes (S2). In 2025 this
  affects 142 booths and 172,386 votes (5.6% of booth votes). The tolerance is a parameter.

Diagnostic recorded per district: number of booths, and the share of the district's eventual
formal vote that is covered by located booths.

## S2 — District primaries

Not every federal vote has a location:

| Vote type | Location | Treatment |
|---|---|---|
| Ordinary election-day | Booth | Assigned by S1 |
| Pre-poll (ordinary) | Early-voting centre, wide catchment | Assigned by S1, flagged; optionally re-spread like declaration votes |
| Postal, absent, provisional (declaration) | Division only | Spread across the districts that overlap the division, in proportion to each district's located vote, using the division's own party shares by vote type |

Primary for party *p* in district *d*:

```
V[d, p] = Σ_{booths b in d} V[b, p]  +  Σ_{divisions D} w[D, d] · Vdecl[D, p]
```

where `w[D, d]` is district *d*'s share of division *D*'s located vote. Shares are taken after
summing, so large pre-poll centres are not over- or under-weighted.

**Senate variant (`S2s`):** the same aggregation applied to Senate first preferences. Senate votes
depend less on individual House candidates, so they may give a cleaner party baseline, especially
for One Nation and the Greens.

## S3 — Party mapping and candidates

Federal and state ballots differ, so the federal shares are mapped onto the state candidate list:

- **Major parties:** ALP, Liberal, Nationals, Greens, One Nation map directly.
- **Three-cornered Coalition contests:** where both the Liberals and Nationals run at state level
  but not federally (or vice versa), split the Coalition vote using the most recent contest where
  both ran, falling back to a regional default.
- **Minor parties:** map by ideology to the parties actually standing (e.g. federal Trumpet of
  Patriots → state Family First / Freedom; Legalise Cannabis → Legalise Cannabis). Parties with no
  state equivalent are redistributed to an `Other right` / `Other left` bucket.
- **Federal independents** (teals in Kooyong and Goldstein, Indi, etc.) are **removed**; their vote
  is redistributed to other parties using their own booth-level 2CP flows.
- **State independents** are added from the state candidate list with a seat-specific prior
  (previous state result, incumbency, profile) and wide uncertainty, taking their vote
  proportionally from the other parties. This is the same treatment as model2.

## S4 — Rescale to state polling (variants)

The federal baseline is out of date and federal behaviour differs from state behaviour. Each
variant forces the statewide total to match the **final pre-election poll average**, optionally
also matching regional figures (e.g. Roy Morgan Upper House regions, DemosAU Melbourne/regional).

| Variant | Rule | Strength | Weakness |
|---|---|---|---|
| **R0** | No rescale | Shows how much rescaling adds | Ignores all movement since the federal election |
| **R1** | Uniform additive swing per party | Simple; matches the pendulum convention | One Nation +16 everywhere, including inner Melbourne; can go negative |
| **R2** | Proportional (multiply shares, renormalise) | Swings largest where a party is already strong | Overshoots in very strong booths (a 6% → 22% party ×3.7) |
| **R3** | Logit swing: shift `logit(share)` by a party constant solved to hit the statewide target | Bounded in (0, 1); largest swings in mid-range areas | Still assumes one movement pattern per party |
| **R4** | **Vote-transition matrix**: `share2026[d, q] = Σ_p share2025[d, p] · T[p → q]`, with `T` from poll crosstabs by past federal vote, then a small R3 correction to hit the poll average | Models where One Nation's new voters come from; feeds F3 | Needs crosstabs by past vote, which are not always published |

R4 is the variant expected to matter in a One Nation surge, because it decides whether One Nation
grows at Labor's expense (outer suburbs) or the Coalition's (regional areas), which decides who
finishes third.

## S5 — Preference model (variants)

Every variant produces, for each district, a set of **party-level preference orders** with weights
(e.g. "Greens voters: 78% GRN > ALP > LIB > ONP, 12% GRN > ALP > ONP > LIB, …"). These go straight
into the count, so votes inherited from excluded candidates carry their own preferences forward.

| Variant | Source | What it can and cannot see |
|---|---|---|
| **F0** | Statewide federal 2CP flows by party (AEC) | One split per party, toward whichever two finished; no conditional splits |
| **F1** | Booth-level federal House distributions of preferences, aggregated to districts | Local variation in minor-party flows; still never sees Liberal or Labor votes distributed in most seats |
| **F2** | **Senate formal-preference file**: full party rankings from every ballot, aggregated to districts by collection point | Every conditional split, including Liberal → One Nation vs Labor; but it is Senate, not House, behaviour |
| **F3** | F2, with **new One Nation voters** (from R4's matrix) given the rankings of their origin party rather than of 2025 One Nation voters | Accounts for the composition change in a surging party |

F2 and F3 are the only variants that can price the splits that decide three-way seats. The
backtests check whether Senate rankings, applied to the House, reproduce observed House flows.

**How-to-vote adjustment (optional, `+H`):** where the state how-to-vote cards for a party differ
from its federal cards, shift that party's flows by the historical effect of a recommendation
change (e.g. Liberal preferencing in Northcote 2022). Off by default.

## S6 — Count

For each district and each draw, the S4 primaries and S5 preference orders are expanded into
weighted `BallotBundle`s and counted with `run_irv_from_ballots(mode="full_2cp")`. There is no
core/minor collapse: every candidate is counted, so exclusion order is always exact for the given
inputs. This is the main structural difference from model2.

## S7 — Uncertainty (Monte Carlo)

Each draw perturbs:

```
logit(share[d, p]) = logit(estimate[d, p])
                   + statewide[p]          (shared by all districts)
                   + regional[r(d), p]
                   + seat[d, p]            (wider for credible independents)
flows: party-pair splits jittered, mostly statewide, small seat component
```

The sizes of these error terms are **calibrated from backtest residuals**, not chosen by hand:
B5 gives a floor, B6 gives the realistic size in a One Nation surge (see
[BACKTESTS.md](BACKTESTS.md#using-the-results)).

Each draw records winner, final two, 2CP shares, three-candidate set and exclusion order per
district, plus the statewide seat count.

---

## Variants and naming

A run is named by its choices, e.g. `model3-R3F2`, `model3-R4F3`, `model3-R4F3+S2s`. The
backtests evaluate the grid R0–R4 × F0–F3; the best-performing combination on B6 (with no
regression on B5) becomes the frozen `model3` for Victoria 2026.

## Outputs

The standard files from [`predictions/modelling/README.md`](../README.md#standard-outputs), plus:

| File | Contents |
|---|---|
| `district_primaries.csv` | Point-estimate primaries per district and party after S1–S4, before noise |
| `booth_assignment.csv` | Booth → district, method (point / snapped / split), weight |
| `flows.csv` | Party-pair conditional splits used, by district where they vary |
| `diagnostics.json` | Located-vote coverage per district, rescale constants, flow source |

## Known limitations

- **Federal ≠ state.** Candidate effects, state-specific party brands and incumbency are only
  partly captured by rescaling; a state-baseline blend is an option (see ROADMAP).
- **Declaration and pre-poll votes** cannot be placed exactly; their spread is an assumption.
- **Senate preferences are a proxy** for House preferences (ticket-like above-the-line voting,
  exhaustion, different how-to-vote cards).
- **Vote-transition matrices** depend on published crosstabs by past vote, which are sparse.
- **Independents** remain partly judgement-based.
- **Time gap.** Victoria 2026 is ~19 months after the 2025 federal election; the SA backtest gap
  is ~10.5 months, so B6 may understate the error.
