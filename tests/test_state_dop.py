"""Other states' distributions of preferences: parsers and the cached, validated datasets."""
from __future__ import annotations

import json

import pytest

from vic_election.benchmark import align_districts, load_winners_csv
from vic_election.config import DATA_DIR, WINNERS_DIR
from vic_election.state_dop import _sa2022_csv, validate

SA_CSV = '''\ufeff"Electoral Commission SA, 2022 State Election, House of Assembly",,,,,
Final Distribution of Preferences for the District of Black,,,,,
Absolute Majority (50% + 1) = 11843,,,,,
"Names of Candidates with Affiliations, in ballot paper order",,,,,
,,DIGHTON,TIDEMANN,SPEIRS,"TOTAL
FORMAL
VOTES"
,Votes transferred,ALP,GRN,LIB,
1st preference votes,,9037,2785,11862,23684
1st excluded candidate TIDEMANN,2785,2154,-2785,631,0
FINAL DISTRICT TOTALS,,11191,Excluded,12493,23684
'''


def test_sa2022_csv_parser() -> None:
    district, t = _sa2022_csv(SA_CSV.lstrip("\ufeff"))
    assert district == "Black"
    assert [(c["candidate_id"], c["party"]) for c in t["candidates"]] == [("DIGHTON", "ALP"), ("TIDEMANN", "GRN"), ("SPEIRS", "LP")]
    assert t["steps"] == [{"excluded_candidate": "TIDEMANN", "exhausted": 0.0, "transfers": {"DIGHTON": 2154.0, "SPEIRS": 631.0}}]
    assert t["final_totals"] == {"DIGHTON": 11191.0, "SPEIRS": 12493.0} and validate({"Black": t}) == []


def test_validate_flags_unconserved_exclusion() -> None:
    t = {"first_preferences": {"a": 50, "b": 30, "c": 20}, "steps": [{"excluded_candidate": "c", "transfers": {"a": 5, "b": 5}, "exhausted": 0}],
         "final_totals": {}}
    assert validate({"X": t}) == ["X: excluding c moved 10 of 20"]


ELECTIONS = {"QLD2020": 93, "WA2021": 59, "SA2022": 47, "NSW2023": 93, "QLD2024": 93, "WA2025": 59, "SA2026": 47}


@pytest.mark.parametrize("run,seats", ELECTIONS.items())
def test_cached_distributions_are_complete_and_match_declared_winners(run: str, seats: int) -> None:
    path = DATA_DIR / run / "distributions" / f"dop_{run}.json"
    if not path.exists():
        pytest.skip("run scripts/fetch_state_dops.py")
    tables = json.loads(path.read_text())
    assert len(tables) == seats and validate(tables) == []
    declared = align_districts(load_winners_csv(WINNERS_DIR / f"{run}.csv"), list(tables))
    for d, t in tables.items():
        assert len(t["first_preferences"]) - len(t["steps"]) == 2, d  # counted to the final two
        party = {c["candidate_id"]: c["party"] for c in t["candidates"]}
        assert party[max(t["final_totals"], key=t["final_totals"].get)] == declared[d], d
