"""Benchmark metrics and Model 1's preference fit and simulation."""
from __future__ import annotations

import math
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "predictions" / "modelling" / "model1"))
import model1  # noqa: E402  (model code lives in predictions/modelling/model1/)
from vic_election.benchmark import party_group, score
from vic_election.booth_flows import FIRST, AecCandidate, BoothFlows


def test_score_metrics() -> None:
    forecast = {"A": {"ALP": 0.7, "LP": 0.3}, "B": {"LP": 0.6, "ALP": 0.4}, "C": {"ALP": 1.0}}
    winners = {"A": "ALP", "B": "ALP", "C": "GRN"}
    s = score(forecast, winners)
    assert s["raw_seat_count"] == 1 and s["districts"] == 3
    brier = ((0.3**2 + 0.3**2) + (0.6**2 + 0.6**2) + (1.0**2 + 1.0**2)) / 3
    assert s["brier"] == round(brier, 4)
    assert s["log_loss"] == round((-math.log(0.7) - math.log(0.4) - math.log(1e-3)) / 3, 4)  # winner at p=0 is floored
    assert score({"A": {"ALP": 1.0}}, {"A": "ALP"}) == {"districts": 1, "raw_seat_count": 1, "brier": 0.0, "log_loss": 0.0}


def test_winner_parsers_and_district_matching() -> None:
    from vic_election.benchmark import align_districts
    from vic_election.wiki_winners import parse_members_table, parse_pendulum
    pendulum = "|-\n| style=x|[[Electoral district of Penrith|Penrith]]\n| [[Karen McKeown]]\n| style=y|ALP\n| 1.6%\n|-\n" \
               "| [[Electoral district of Monaro]]\n| [[Nichole Overall]]\n| NAT\n| 2.3%"
    assert parse_pendulum(pendulum) == {"Penrith": "ALP", "Monaro": "NP"}
    members = "|-\n|[[Electoral district of Collie-Preston|Collie-Preston]]\n| {{Australian party style|Labor WA}} |\n" \
              "|-\n|[[Electoral district of Collie-Preston|Collie-Preston]]\n| {{Australian party style|Independent}} |"
    assert parse_members_table(members) == {"Collie-Preston": "ALP"}  # first member listed is the one elected
    assert align_districts({"Collie-Preston": "ALP"}, ["Collie - Preston"]) == {"Collie - Preston": "ALP"}


def test_party_group_mapping() -> None:
    assert party_group("Australian Labor Party - Victorian Branch") == "ALP"
    assert party_group("THE NATIONALS") == "NP" and party_group("Independent") == "IND*"


CANDS = {c.id: c for c in [AecCandidate("a", "A", "ALP", "D"), AecCandidate("l", "L", "LP", "D"), AecCandidate("g", "G", "GRN", "D"),
                           AecCandidate("o", "O", "ON", "D")]}


def test_bradley_terry_reproduces_observed_split() -> None:
    booth = BoothFlows("1", "1", "D", ("a", "l"), {(FIRST, "a"): 400, (FIRST, "l"): 350, ("g", "a"): 80, ("g", "l"): 20,
                                                    ("o", "a"): 30, ("o", "l"): 70})
    w = model1.preference_weights([booth], CANDS)
    assert w["GRN"]["ALP"] / (w["GRN"]["ALP"] + w["GRN"]["LP"]) == pytest.approx(0.8, abs=1e-6)
    assert w["ON"]["LP"] / (w["ON"]["ALP"] + w["ON"]["LP"]) == pytest.approx(0.7, abs=1e-6)
    assert model1._strength(w, "ALP", "GRN") == model1.UNOBSERVED_WEIGHT  # never seen as a final-two recipient


def test_simulation_without_noise_replays_the_count() -> None:
    weights = {"GRN": {"ALP": 0.8, "LP": 0.2}, model1.POOLED: {"ALP": 0.5, "LP": 0.5}}
    primaries = {"D": Counter({"ALP": 40, "LP": 45, "GRN": 15})}
    sim = model1.simulate(primaries, weights, runs=20, noise={"state": 0, "seat": 0, "flow": 0})
    assert sim["wins"]["D"] == Counter({"ALP": 20})  # 40 + 12 beats 45 + 3
    assert sim["tcp"]["D"]["ALP"][0] == pytest.approx(52.0)


def test_apply_state_field_hands_on_non_standing_parties() -> None:
    from collections import Counter as C
    weights = {model1.POOLED: {"ALP": 0.5, "LP": 0.5}, "GRN": {"ALP": 0.8, "LP": 0.2}}
    prim = {"D": C({"ALP": 400, "LP": 300, "NP": 100, "GRN": 100, "IND*": 100})}
    field = {"D": {"ALP", "LP", "ON"}}  # no National, Green or independent stands
    out, notes = model1.apply_state_field(prim, field, weights)
    assert out["D"]["LP"] == pytest.approx(300 + 100 + 100 * 0.2 + 50)  # Nationals -> Liberal; Greens 80/20; independents pooled 50/50
    assert out["D"]["ALP"] == pytest.approx(400 + 80 + 50) and "ON" not in out["D"]  # One Nation had no federal vote here
    assert sum(out["D"].values()) == pytest.approx(1000) and notes["D"]["no_federal_vote"] == ["ON"]


def test_model1_central_count_stages_sum_to_100() -> None:
    from collections import Counter as C
    weights = {model1.POOLED: {"ALP": 0.5, "LP": 0.5, "GRN": 0.5}, "GRN": {"ALP": 0.8, "LP": 0.2}}
    c = model1.central_count(C({"ALP": 40, "LP": 45, "GRN": 15}), weights)
    assert [s["excluded"] for s in c["stages"]] == [["GRN"]] and c["winner"] == "ALP"
    assert c["final"]["ALP"] == pytest.approx(52.0) and sum(c["final"].values()) == pytest.approx(100.0)


def test_bloc_seats_sums_coalition_run_by_run() -> None:
    from vic_election.benchmark import bloc_seats
    blocs = bloc_seats({"LP": [40, 30, 50], "NP": [8, 9, 7], "ALP": [30, 40, 20]})
    assert blocs == {"COAL": [48, 39, 57], "ALP": [30, 40, 20]}
