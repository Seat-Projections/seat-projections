"""
Checks the counting engine against the real VEC Lower House results, district by district.

Each dataset is skipped if it hasn't been fetched yet (scripts/fetch_vec_2018.py, scripts/fetch_vec_2022.py).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pytest

from vic_election.decomposition import decompose_distribution_to_ballots
from vic_election.irv import run_irv_from_ballots
from vic_election.models import DistributionTable
from vic_election.verify import load_distribution_dataset, verify_distribution_table

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# (year, file stem, counting mode, expected district count)
DATASETS = [
    ("2018", "official_2018", "official", 88),
    ("2022", "official_2022", "official", 88),
    ("2022", "full_2cp_2022", "full_2cp", 88),
    ("2022", "indicative_39_2022", "full_2cp", 39),
]


def _path(year: str, stem: str) -> Path:
    return DATA_DIR / year / "distributions" / f"{stem}.json"


def _load(year: str, stem: str) -> dict[str, DistributionTable]:
    path = _path(year, stem)
    if not path.exists():
        pytest.skip(f"{path.name} not fetched; run scripts/fetch_vec_{year}.py")
    return load_distribution_dataset(path)


_CASES = [
    pytest.param(year, stem, mode, district, id=f"{stem}-{district}")
    for year, stem, mode, _ in DATASETS
    if _path(year, stem).exists()
    for district in sorted(load_distribution_dataset(_path(year, stem)))
]


@pytest.mark.parametrize(("year", "stem", "mode", "expected"), [d for d in DATASETS])
def test_dataset_complete(year: str, stem: str, mode: str, expected: int) -> None:
    tables = _load(year, stem)
    assert len(tables) == expected
    assert all(t.declared_winner for t in tables.values()), "every district needs the VEC's 'Elected member'"
    if stem.startswith("full_2cp") or stem.startswith("indicative"):
        assert all(len(t.final_totals) == 2 for t in tables.values())


@pytest.mark.parametrize(("year", "stem", "mode", "district"), _CASES)
def test_district_exact(year: str, stem: str, mode: str, district: str) -> None:
    """Every first preference, exclusion, transfer, progressive total, final total and the winner match."""
    table = _load(year, stem)[district]
    v, _, _ = verify_distribution_table(table, mode=mode)  # type: ignore[arg-type]
    assert v.passed, v.errors


@pytest.mark.parametrize(("year", "stem", "mode", "district"), _CASES)
def test_district_unassisted(year: str, stem: str, mode: str, district: str) -> None:
    """Without the VEC's round count or exclusion order, the engine finds the same path and winner itself."""
    table = _load(year, stem)[district]
    r = run_irv_from_ballots(decompose_distribution_to_ballots(table), table.candidates, mode=mode)  # type: ignore[arg-type]
    assert r.elimination_order == [s.excluded_candidate for s in table.steps]
    assert {k: int(v) for k, v in r.final_totals.items()} == table.final_totals
    assert r.winner == table.declared_winner


# VEC statewide Lower House figures: formal votes and seats won per party
STATEWIDE = {
    "2018": (
        3_514_474,
        {"AUSTRALIAN LABOR PARTY": 55, "LIBERAL": 21, "THE NATIONALS": 6, "AUSTRALIAN GREENS": 3, "Independent": 3},
    ),
    # 87 general-election districts (3,617,000) + Narracan supplementary election (37,205)
    "2022": (
        3_617_000 + 37_205,
        {"Australian Labor Party - Victorian Branch": 56, "Liberal": 19, "The Nationals": 9, "Australian Greens": 4},
    ),
}


@pytest.mark.parametrize("year", sorted(STATEWIDE))
def test_statewide_totals(year: str) -> None:
    tables = _load(year, f"official_{year}")
    formal, seats = STATEWIDE[year]
    assert sum(t.formal_votes for t in tables.values()) == formal
    won = Counter({c.candidate_id: c.party for c in t.candidates}[t.declared_winner] for t in tables.values())
    assert dict(won) == seats


def test_2022_first_preferences_match_booth_workbook() -> None:
    """Independent source: VEC booth-level primary workbook, aggregated by district and ballot position."""
    openpyxl = pytest.importorskip("openpyxl")
    path = DATA_DIR / "2022" / "raw" / "statewide" / "all_district_primary_results_2022.xlsx"
    if not path.exists():
        pytest.skip("2022 booth workbook not fetched")
    votes: dict[tuple[str, int], int] = defaultdict(int)
    for e, _, ctype, _, _, order, _, _, v, *_ in openpyxl.load_workbook(path, read_only=True).active.iter_rows(
        min_row=2, values_only=True
    ):
        if ctype == "First Preference" and isinstance(order, int) and order < 900 and v:
            votes[(e, order)] += v

    tables = _load("2022", "official_2022")
    mismatches = [
        (d, c.candidate_id, votes[(d, c.ballot_position)], t.first_preferences[c.candidate_id])
        for d, t in tables.items()
        if d != "Narracan"  # supplementary election, not in the general-election workbook
        for c in t.candidates
        if votes[(d, c.ballot_position)] != t.first_preferences[c.candidate_id]
    ]
    assert not mismatches
