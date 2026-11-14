"""2018 first preferences by voting centre, and the 2018 -> 2022 boundary remap."""
from __future__ import annotations

import json
from collections import Counter

import pytest

from vic_election.config import DATA_DIR
from vic_election.geo import District
from vic_election.vec_booths import DistrictBooths, notional, parse_fpv_by_voting_centre, remap

PAGE = """<html><h2>Albert Park District</h2><table>
<tr><th></th><th>A, One</th><th>B, Two</th><th></th><th></th></tr>
<tr><td>Voting Centres</td><td>LIBERAL</td><td>AUSTRALIAN LABOR PARTY</td><td>Informal votes</td><td>Total votes polled</td></tr>
<tr><td>North</td><td>10</td><td>30</td><td>2</td><td>42</td></tr>
<tr><td>South</td><td>20</td><td>40</td><td>1</td><td>61</td></tr>
<tr><td>Ordinary Votes Total</td><td>30</td><td>70</td><td>3</td><td>103</td></tr>
<tr><td>Early Votes</td><td>50</td><td>50</td><td>4</td><td>104</td></tr>
<tr><td>Total</td><td>80</td><td>120</td><td>7</td><td>207</td></tr>
<tr><td>Percentage of formal vote polled by candidate</td><td>40%</td><td>60%</td><td></td><td></td></tr>
</table></html>"""


def test_parse_recheck_page() -> None:
    b = parse_fpv_by_voting_centre(PAGE)
    assert b.candidates == [("A, One", "LIBERAL"), ("B, Two", "AUSTRALIAN LABOR PARTY")]
    assert b.centres == {"North": {"A, One": 10, "B, Two": 30}, "South": {"A, One": 20, "B, Two": 40}}
    assert b.declaration == {"early": {"A, One": 50, "B, Two": 50}} and b.total == 200


def _square(name: str, x0: float, x1: float) -> District:
    ring = [(x0, 0.0), (x1, 0.0), (x1, 1.0), (x0, 1.0), (x0, 0.0)]
    return District(name, "", [[ring]], (x0, 0.0, x1, 1.0))


def test_notional_places_centres_and_conserves_votes() -> None:
    b = parse_fpv_by_voting_centre(PAGE)
    b.district = "Old"
    old = [_square("Old", 0, 2)]
    new = [_square("West", 0, 1), _square("East", 1, 2)]
    locations = {("Old", "North"): (0.5, 0.5, "Voting Centre"), ("Old", "South"): (1.5, 0.5, "Voting Centre")}
    m = remap({"Old": b}, locations, old, new)
    assert m["weights"]["Old"] == pytest.approx({"West": 0.4, "East": 0.6})
    n = notional({"Old": b}, {"Old": {"A, One": "LP", "B, Two": "ALP"}}, m)
    assert n["West"]["LP"] == pytest.approx(10 + 50 * 0.4) and n["East"]["ALP"] == pytest.approx(40 + 50 * 0.6)
    assert sum(sum(c.values()) for c in n.values()) == pytest.approx(200)


def test_centre_outside_own_district_is_spread_not_placed() -> None:
    b = DistrictBooths("Old", [("A", "")], centres={"In": {"A": 60}, "Over the line": {"A": 40}})
    m = remap({"Old": b}, {("Old", "In"): (0.5, 0.5, ""), ("Old", "Over the line"): (2.5, 0.5, "")},
              [_square("Old", 0, 2)], [_square("West", 0, 1), _square("Far", 2, 3)])
    assert m["unlocated"] == [("Old", "Over the line", 40, "outside own district")]
    assert notional({"Old": b}, {"Old": {"A": "IND*"}}, m) == {"West": Counter({"IND*": 100})}


NOTIONAL = DATA_DIR / "2018" / "notional_2022_boundaries.json"


@pytest.mark.skipif(not NOTIONAL.exists(), reason="run scripts/build_notional_2018.py")
def test_notional_2018_file_conserves_the_official_count() -> None:
    n = json.loads(NOTIONAL.read_text())
    official = json.loads((DATA_DIR / "2018" / "distributions" / "official_2018.json").read_text())
    assert len(n["districts"]) == 88
    assert sum(sum(c.values()) for c in n["districts"].values()) == pytest.approx(sum(t["formal_votes"] for t in official.values()), abs=50)
