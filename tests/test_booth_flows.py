"""Collating per-booth federal preference flows into state districts."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vic_election.booth_flows import FIRST, IND, AecCandidate, BoothFlows, assign_booths, collate, collate_district
from vic_election.geo import District

DATA = Path(__file__).resolve().parent.parent / "data" / "federal"

CANDS = {c.id: c for c in [
    AecCandidate("a1", "LAB, A", "ALP", "Alpha"), AecCandidate("a2", "LIB, A", "LP", "Alpha"), AecCandidate("a3", "GRN, A", "GRN", "Alpha"),
    AecCandidate("a4", "SMITH, Jo", "IND", "Alpha"), AecCandidate("a5", "JONES, Al", "NAFD", "Alpha"),
    AecCandidate("b1", "RYAN, M", "IND", "Beta"), AecCandidate("b2", "LIB, B", "LP", "Beta"), AecCandidate("b3", "LAB, B", "ALP", "Beta"),
    AecCandidate("b4", "GRN, B", "GRN", "Beta"), AecCandidate("b5", "BROWN, K", "IND", "Beta"),
]}


def booth(ppid: str, division: str, finalists: tuple[str, str], votes: dict[tuple[str, str], int]) -> BoothFlows:
    return BoothFlows(ppid, ppid, division, finalists, votes)


# Division Alpha: final two Labor v Liberal. Division Beta: final two independent (Ryan) v Liberal.
BOOTH_A = booth("1", "Alpha", ("a1", "a2"), {
    (FIRST, "a1"): 100, (FIRST, "a2"): 80, ("a3", "a1"): 30, ("a3", "a2"): 5,
    ("a4", "a1"): 6, ("a4", "a2"): 4, ("a5", "a1"): 3, ("a5", "a2"): 7,
})
BOOTH_B = booth("2", "Beta", ("b1", "b2"), {
    (FIRST, "b1"): 50, (FIRST, "b2"): 60, ("b3", "b1"): 20, ("b3", "b2"): 5,
    ("b4", "b1"): 9, ("b4", "b2"): 1, ("b5", "b1"): 2, ("b5", "b2"): 2,
})


def test_votes_are_summed_by_party_across_divisions() -> None:
    m = collate([BOOTH_A, BOOTH_B], CANDS)
    assert m["total"] == 384
    assert [(c["key"], c["votes"]) for c in m["columns"]] == [("LP", 164), ("ALP", 139), (IND, 81)]
    rows = {r["key"]: r for r in m["rows"]}
    assert rows[FIRST]["votes"] == [140, 100, 50]
    assert rows["GRN"]["votes"] == [6, 30, 9] and rows["GRN"]["total"] == 45
    # Labor's own votes only flowed in Beta, where Labor was not in the final two: no Labor column there
    assert rows["ALP"]["votes"] == [5, None, 20] and rows["ALP"]["pct"][1] is None
    assert sum(r["total"] for r in m["rows"]) == m["total"] == sum(c["votes"] for c in m["columns"])


def test_independents_are_pooled_and_merges_flagged() -> None:
    m = collate([BOOTH_A, BOOTH_B], CANDS)
    ind_row = next(r for r in m["rows"] if r["key"] == IND)
    assert ind_row["individual"] and ind_row["merged"]
    assert ind_row["candidates"] == ["BROWN, K (Beta)", "JONES, Al (Alpha)", "SMITH, Jo (Alpha)"]  # non-affiliated pooled too
    assert ind_row["votes"] == [13, 9, 2]
    ind_col = next(c for c in m["columns"] if c["key"] == IND)
    assert ind_col["individual"] and not ind_col["merged"] and ind_col["candidates"] == ["RYAN, M (Beta)"]
    single = collate([BOOTH_B], CANDS)
    assert not next(r for r in single["rows"] if r["key"] == IND)["merged"]  # one independent: asterisk, no merge


def test_two_independent_finalists_are_kept_apart() -> None:
    b = booth("3", "Beta", ("b1", "b5"), {(FIRST, "b1"): 10, (FIRST, "b5"): 8, ("b2", "b1"): 3, ("b2", "b5"): 4})
    m = collate([b], CANDS)
    assert {c["key"] for c in m["columns"]} == {"IND* RYAN", "IND* BROWN"}
    assert all(c["individual"] for c in m["columns"])


def test_district_reports_divisions_and_each_final_two_pairing() -> None:
    d = collate_district([BOOTH_A, BOOTH_B], CANDS, pre_poll={"2"})
    assert [(x["division"], x["votes"], x["pair"]) for x in d["divisions"]] == [("Alpha", 235, "ALP v LP"), ("Beta", 149, "IND* v LP")]
    assert d["pre_poll_share"] == round(100 * 149 / 384, 2)
    assert set(d["by_pair"]) == {"ALP v LP", "IND* v LP"}
    assert d["by_pair"]["ALP v LP"]["total"] + d["by_pair"]["IND* v LP"]["total"] == d["total"]
    assert "by_pair" not in collate_district([BOOTH_A], CANDS, pre_poll=set())


def _square(name: str, x0: float, y0: float, size: float) -> District:
    ring = [(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size), (x0, y0)]
    return District(name, "", [[ring]], (x0, y0, x0 + size, y0 + size))


def test_booths_far_outside_their_own_division_are_not_counted() -> None:
    districts = [_square("Inner", 145.0, -38.0, 0.2)]
    divisions = [_square("Alpha", 145.0, -38.0, 0.05)]  # covers only the south-west corner of the district
    places = {
        "1": {"Latitude": "-37.99", "Longitude": "145.01", "DivisionNm": "Alpha"},    # inside its division
        "2": {"Latitude": "-37.99", "Longitude": "145.055", "DivisionNm": "Alpha"},   # ~0.4 km outside
        "3": {"Latitude": "-37.85", "Longitude": "145.15", "DivisionNm": "Alpha"},    # ~13 km outside
        "4": {"Latitude": "", "Longitude": "", "DivisionNm": "Alpha"},
    }
    loc = assign_booths(places, districts, divisions)
    assert [loc[p].counted for p in "1234"] == [True, True, False, False]
    assert loc["3"].district == "Inner" and loc["3"].division_km > 10
    assert assign_booths(places, districts, divisions, tolerance_km=20)["3"].counted


@pytest.mark.parametrize("year", [2022, 2025])
def test_stored_district_flows_conserve_votes(year: int) -> None:
    path = DATA / str(year) / "district_flows_VIC.json"
    if not path.exists():
        pytest.skip("run scripts/build_district_flows.py")
    r = json.loads(path.read_text())
    assert len(r["districts"]) == 88
    assert r["counted_votes"] + sum(e["votes"] for e in r["excluded_booths"]) == r["booth_votes"]
    assert sum(d["total"] for d in r["districts"].values()) == r["counted_votes"]
    for name, d in r["districts"].items():
        assert d["total"] > 0, name
        assert sum(c["votes"] for c in d["columns"]) == d["total"] == sum(x["total"] for x in d["rows"])
        assert sum(x["votes"] for x in d["divisions"]) == d["total"]
        for row in d["rows"]:
            assert abs(sum(p for p in row["pct"] if p is not None) - 100) < 0.05, (name, row["key"])
            assert row["merged"] == (row["individual"] and len(row["candidates"]) > 1)
