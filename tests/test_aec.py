"""AEC federal booth-level data: download filtering, and consistency of the stored files (skipped if not fetched)."""
from __future__ import annotations

from collections import Counter

import pytest

from vic_election.aec import _subdir, _wanted
from vic_election.aec import read_aec_csv as _rows
from vic_election.config import AEC_EVENTS, FEDERAL_DATA_DIR

DATA_DIR = FEDERAL_DATA_DIR
CASES = [(2022, AEC_EVENTS[2022], "VIC"), (2025, AEC_EVENTS[2025], "VIC"), (2025, AEC_EVENTS[2025], "SA")]


def _is_informal(r: dict[str, str]) -> bool:
    return r.get("Surname", "").lower() == "informal"


def test_state_filter_and_subdirs() -> None:
    assert _wanted("HouseDopByPPDownload-31496-VIC.zip", ("VIC",))
    assert not _wanted("HouseDopByPPDownload-31496-NSW.zip", ("VIC", "SA"))
    assert _wanted("HouseTppByPollingPlaceDownload-31496.csv", ("VIC",))  # national file: always kept
    assert _subdir("aec-senate-formalpreferences-31496-VIC.zip") == "senate"
    assert _subdir("GeneralPollingPlacesDownload-31496.csv") == "general"


@pytest.mark.parametrize(("year", "event", "state"), CASES, ids=[f"{y}-{s}" for y, _, s in CASES])
def test_booth_dops_add_up_to_division_formal_votes(year: int, event: int, state: str) -> None:
    house = DATA_DIR / str(year) / "house"
    dop_dir = house / f"HouseDopByPPDownload-{event}-{state}"
    if not dop_dir.exists():
        pytest.skip(f"AEC {year} {state} not fetched; run scripts/fetch_aec.py")

    formal = Counter()
    for r in _rows(house / f"HouseFirstPrefsByCandidateByVoteTypeDownload-{event}.csv"):
        if r["StateAb"] == state and not _is_informal(r):
            formal[r["DivisionNm"]] += int(r["TotalVotes"])

    booth_total, located = Counter(), Counter()
    for f in dop_dir.glob("*.csv"):
        for r in _rows(f):
            if r["CalculationType"] == "Preference Count" and r["CountNum"] == "0":
                booth_total[r["DivisionNm"]] += int(r["CalculationValue"])
                if r["PPId"] != "0":  # PPId 0 = division-wide ABSENT/POSTAL/PRE_POLL/PROVISIONAL
                    located[r["DivisionNm"]] += int(r["CalculationValue"])

    assert booth_total == formal
    ordinary = Counter()
    for r in _rows(house / f"HouseStateFirstPrefsByPollingPlaceDownload-{event}-{state}.csv"):
        if not _is_informal(r):
            ordinary[r["DivisionNm"]] += int(r["OrdinaryVotes"])
    assert ordinary == located


@pytest.mark.parametrize(("year", "event", "state"), CASES, ids=[f"{y}-{s}" for y, _, s in CASES])
def test_polling_places_have_coordinates(year: int, event: int, state: str) -> None:
    path = DATA_DIR / str(year) / "general" / f"GeneralPollingPlacesDownload-{event}.csv"
    if not path.exists():
        pytest.skip("AEC polling places not fetched")
    places = [r for r in _rows(path) if r["State"] == state]
    # Only mobile and hospital teams (types 2-4) lack coordinates; every fixed booth and pre-poll centre has them
    assert places and all(r["Latitude"] and r["Longitude"] for r in places if r["PollingPlaceTypeID"] in ("1", "5"))


def test_blocked_page_is_detected_and_real_page_is_not() -> None:
    from vic_election.http_cache import _looks_blocked

    assert _looks_blocked(b"<html><body><p>Access Denied<br>Your request has been blocked by our security system.</p></body></html>")
    assert not _looks_blocked(b"<html><title>Preference distribution</title>" + b"x" * 5000 + b"Access Denied")
