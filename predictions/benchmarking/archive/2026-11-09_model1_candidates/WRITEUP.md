# Model 1 archive — 9 November 2026, on the declared candidate fields

Same model as [`../2026-11-08_model1/`](../2026-11-08_model1/WRITEUP.md) ("nothing changes": 2025 federal
polling-place votes inside each district, counted with federal preferences; 1,000 runs, seed 1). The nine
benchmark runs are **identical** to that archive (same raw seat counts, Brier and log loss); they are
included so this archive is complete. The one change is the 2026 forecast.

Reproduce with [`reproduce.sh`](reproduce.sh).

## What changed: `VIC2026 (2025)` uses the declared 2026 candidates

Nominations closed at noon on Monday 9 November 2026. Each district's federal vote is now restricted to the
parties actually standing (`data/2026/candidates_vic2026.csv`, from the VEC's list; `apply_state_field` in
`model1.py`):

- a federal party with no 2026 candidate has its votes handed on as if excluded first: to its Coalition
  partner if one of the Liberals/Nationals is missing, otherwise by its fitted federal preferences;
- the pooled federal independent vote is kept only where an independent stands;
- a party standing with no federal vote in the district gets none ("nothing changes").

| `VIC2026 (2025)` | Labor | Liberal | Nationals | Independents | Greens | One Nation |
|---|---|---|---|---|---|---|
| 2025 federal parties (2026-11-08 archive) | 57.8 | 9.2 | 9.3 | 9.0 | 2.7 | 0 |
| **Declared 2026 field** | **59.1** | **10.2** | **9.8** | **6.8** | **2.1** | **0** |

As a Coalition (Liberal + National seats added up in each simulation, `statewide_blocs.csv`): 19.9 seats
(p10–p90 15–26); Labor 59.1 (53–65), majority in 99.9% of runs. The 2026 run was re-run after making its
random draws independent of Python's hash seed (`apply_state_field` built a set); results moved by
under 0.1 seat.

- **Shepparton and Mildura** have no Liberal candidate, so the Liberals' federal vote goes to the Nationals.
- **Independents fall from 9.0 to 6.8** where no state independent stands to inherit a federal one's vote.
  Where one does (Benambra from Indi, Kew from Kooyong), the federal independent vote carries over in full:
  model1's known flaw, now limited to seats with an independent on the ballot.
- **One Nation still wins nothing**: about 6% federally, with no rescaling to the state polls.

This remains a baseline, not a forecast. `run/VIC2026 (2025)/district_primaries.csv` is the raw federal vote
(model2 reads One Nation's pattern from it); `field_primaries.csv` is the vote after the field is applied;
`district_counts.json` feeds the visualiser's Model 1 view.
