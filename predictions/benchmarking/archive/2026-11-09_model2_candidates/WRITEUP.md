# Model 2 archive — 9 November 2026, on the declared candidate fields

Same model as [`../2026-11-09_model2/`](../2026-11-09_model2/WRITEUP.md) (origin-tracking count, core = top
four, 5,000 runs, seed 1). The one change is the **2026 forecast's candidates**: instead of the 2022 field
plus a placeholder One Nation candidate, every district now has the candidates who nominated, from the
VEC's list published after nominations closed at noon on Monday 9 November 2026 (734 candidates in 88
districts, `scripts/fetch_vic2026_candidates.py` → `data/2026/candidates_vic2026.csv`). The B1 replays are
unchanged and are included here only so the archive is complete.

Reproduce with [`reproduce.sh`](reproduce.sh).

## How the declared fields enter the baseline

Each 2026 candidate starts from the 2022 primaries in their district (`model2.baseline_2026`):

| Candidate | Baseline share |
|---|---|
| Party stood here in 2022 | Its 2022 share here |
| Party stood elsewhere in 2022 | Its 25th-percentile 2022 share (parties contest their best seats first) |
| Party new in 2026 | 1% |
| Liberal or National, one partner standing | The Coalition's whole 2022 share here |
| Liberal and National both standing, one new | The newcomer takes its mean 2022 share from the other |
| One Nation (all 88 seats) | Its 2025 federal booth pattern, scaled to its poll level |
| Credible independent (hand-entered list) | Seat prior: 2022 primary if recontesting, otherwise 15% ± 6 |
| Other independent | Own 2022 share if recontesting, otherwise the median 2022 minor-independent share |

2022 candidates whose party does not stand again drop out; their votes are shared out when each draw
renormalises. 2026 party names are mapped to the 2022 groups they continue (e.g. "Libertarian Party
(formerly Liberal Democrats)" → LDP), so 2022 shares and preference flows carry over.

What the declared fields changed:

- **Mildura:** Ali Cupper is not on the ballot and no independent stands; Nationals v One Nation.
- **Shepparton:** no Liberal candidate, so the Nationals inherit the Coalition's 2022 share.
- **Three-cornered seats:** 12 Nationals stand, including Ripon, which now has both a Liberal and a National.
- **All six credible independents** (Kew, Hawthorn, Mornington, Benambra, Essendon, Footscray) nominated.
- **One Nation, Labor, Greens and Victorian Socialists** stand in all 88 districts; the Liberals in 77.

## VIC2026 (2022) — forecast, not yet scored

Polling average: Labor 22.7, Coalition 30.7, One Nation 22.0, Greens 14.9, others 9.7.

| | Liberal | Labor | One Nation | Nationals | Greens | Independents | P(Liberal ≥ 45) | Seats < 60% |
|---|---|---|---|---|---|---|---|---|
| Placeholder fields (earlier archive) | 42.2 | 18.9 | 11.1 | 7.6 | 7.7 | 0.7 | 40% | 28 |
| **Declared fields** | **40.2** | **20.8** | **9.2** | **8.8** | **8.1** | **0.9** | **32%** | **29** |

**As a Coalition** (Liberal + National seats added up in each simulation, `statewide_blocs.csv`): **49.0 seats
(p10–p90 37–62), majority (45+) in 67% of runs**; Labor 20.8 (9–34), majority 1%.

Seven seats change favourite:

| District | Before | Now |
|---|---|---|
| Footscray | Labor 39% | Independent (Marsh) 35% |
| Narre Warren South | One Nation 45% | Liberal 37% |
| Preston | Greens 51% | Labor 48% |
| Ripon | Liberal 58% | One Nation 68% (Liberal and National both standing) |
| St Albans | Liberal 41% | Labor 45% |
| Tarneit | Liberal 42% | Labor 48% |
| Werribee | One Nation 41% | Labor 43% |

## Known limitations

- **Parties expanding into new seats** start from their 25th-percentile 2022 result. Victorian Socialists
  (22 seats in 2022, all 88 now) average about 3.8% across districts, likely too high in rural seats.
  The total "others" vote is still fixed by the polls.
- **Independents not on the credible list** get a small default share, even if locally prominent.
- **One Nation's flows** are still priors; how-to-vote cards (registered 10–20 November) are not used yet.
- All noise sizes remain placeholders; on the B1 replays the 80% 2CP intervals contain the result only
  44% of the time, so this forecast is overconfident.
