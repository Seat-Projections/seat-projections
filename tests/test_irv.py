from __future__ import annotations

from vic_election.irv import (
    compute_majority_threshold,
    run_irv_from_ballots,
    run_irv_from_transfer_matrix,
)
from vic_election.models import BallotBundle


def test_majority_threshold() -> None:
    assert compute_majority_threshold(20000) == 10001
    assert compute_majority_threshold(40512) == 20257
    assert compute_majority_threshold(39507) == 19754


def test_three_cornered_elimination_order_sensitivity() -> None:
    """
    Verifies that in a 3-way contest (Labor, Liberal, One Nation all in the low 20s),
    changing who finishes 2nd vs 3rd changes the elimination sequence and final winner.
    """
    # Case 1: ALP 26%, LIB 24%, ONP 23%, GRN 17%, FFP 10%
    # FFP (10%) excluded first -> flows 80% to ONP, 20% to LIB:
    #   ONP becomes 23 + 8 = 31%, LIB becomes 24 + 2 = 26%, ALP = 26%, GRN = 17%
    # GRN (17%) excluded second -> flows 80% to ALP, 20% to LIB:
    #   ALP becomes 26 + 13.6 = 39.6%, ONP = 31%, LIB becomes 26 + 3.4 = 29.4%
    # Now LIB (29.4%) is excluded 3rd instead of ONP (31.0%)!
    ballots = [
        BallotBundle(("ALP", "GRN", "LIB", "ONP", "FFP"), 2600),
        BallotBundle(("LIB", "ONP", "ALP", "FFP", "GRN"), 1800),
        BallotBundle(("LIB", "ALP", "ONP", "FFP", "GRN"), 600),
        BallotBundle(("ONP", "LIB", "FFP", "ALP", "GRN"), 2300),
        BallotBundle(("GRN", "ALP", "LIB", "ONP", "FFP"), 1360),
        BallotBundle(("GRN", "LIB", "ALP", "ONP", "FFP"), 340),
        BallotBundle(("FFP", "ONP", "LIB", "ALP", "GRN"), 800),
        BallotBundle(("FFP", "LIB", "ONP", "ALP", "GRN"), 200),
    ]
    res = run_irv_from_ballots(
        ballots,
        candidates=["ALP", "LIB", "ONP", "GRN", "FFP"],
        district="ThreeCorneredTest",
        mode="full_2cp",
    )
    assert res.total_formal_votes == 10000
    assert res.majority_threshold == 5001
    # Check elimination order: FFP (1000), then GRN (1700), then LIB (2940)
    assert res.elimination_order == ["FFP", "GRN", "LIB"]
    # Final 2CP is ONP vs ALP:
    # ONP has 2300 + 800 (from FFP) + 1800 (from LIB) + 200 (from FFP->LIB->ONP) = 5100
    # ALP has 2600 + 1360 (from GRN) + 600 (from LIB) + 340 (from GRN->LIB->ALP) = 4900
    assert res.final_totals == {"ALP": 4900, "ONP": 5100}
    assert res.winner == "ONP"


def test_statutory_tie_breaking_lookback() -> None:
    """
    Tests Electoral Act 2002 (Vic) s 114(5): when two candidates are tied for
    lowest in round r, exclude the one who had fewer votes at the most recent
    preceding round where they differed.
    """
    # Round 0: A=400, B=350, C=120, D=110, E=20 (Total = 1000)
    # Round 1: E (20) excluded -> 15 go to D, 5 go to C
    # Progressive after Round 1: A=400, B=350, C=125, D=125 (C and D tied at 125!)
    # Lookback to Round 0: D had 110 < C's 120, so D must be excluded in Round 2.
    ballots = [
        BallotBundle(("A", "B"), 400),
        BallotBundle(("B", "A"), 350),
        BallotBundle(("C", "B", "A"), 120),
        BallotBundle(("D", "A", "B"), 110),
        BallotBundle(("E", "D", "A", "B"), 15),
        BallotBundle(("E", "C", "B", "A"), 5),
    ]
    res = run_irv_from_ballots(
        ballots,
        candidates=["A", "B", "C", "D", "E"],
        mode="full_2cp",
    )
    assert res.elimination_order == ["E", "D", "C"]
    assert res.final_totals == {"A": 525, "B": 475}
    assert res.winner == "A"


def test_transfer_matrix_mode() -> None:
    first_prefs = {"ALP": 10000, "LIB": 10000, "ONP": 8000, "GRN": 4000}
    flows = {
        "GRN": {"ALP": 0.80, "LIB": 0.15, "ONP": 0.05},
        "ONP": {"LIB": 0.75, "ALP": 0.25},
    }
    res = run_irv_from_transfer_matrix(
        first_prefs,
        flows,
        candidates=["ALP", "LIB", "ONP", "GRN"],
        round_transfers_to_int=True,
    )
    assert res.elimination_order == ["GRN", "ONP"]
    # Round 1: GRN (4000) -> ALP +3200 (13200), LIB +600 (10600), ONP +200 (8200)
    # Round 2: ONP (8200) -> LIB +6150 (16750), ALP +2050 (15250)
    assert res.final_totals == {"ALP": 15250, "LIB": 16750}
    assert res.winner == "LIB"



def test_three_cornered_contest_flips_on_exclusion_order() -> None:
    """
    Labor 25%, Liberal 23.5%, One Nation 21.5%, Greens 21.5%, Family First 8.5%: the Liberal finishes
    ahead of One Nation at the three-candidate stage, One Nation's preferences (80% Liberal) elect the
    Liberal. Moving 2% of the electorate from Liberal to One Nation reverses the exclusion order, and the
    Liberal's 30% leak to Labor elects Labor instead.
    """
    shared = [
        BallotBundle(("ALP", "GRN", "LIB", "ONP", "FFP"), 10000),
        BallotBundle(("GRN", "ALP", "LIB", "ONP", "FFP"), 7000),
        BallotBundle(("GRN", "LIB", "ALP", "ONP", "FFP"), 1600),
        BallotBundle(("FFP", "ONP", "LIB", "ALP", "GRN"), 2400),
        BallotBundle(("FFP", "LIB", "ONP", "ALP", "GRN"), 1000),
    ]
    liberal_ahead = shared + [
        BallotBundle(("LIB", "ONP", "FFP", "ALP", "GRN"), 6580),
        BallotBundle(("LIB", "ALP", "ONP", "FFP", "GRN"), 2820),
        BallotBundle(("ONP", "LIB", "FFP", "ALP", "GRN"), 6880),
        BallotBundle(("ONP", "ALP", "LIB", "FFP", "GRN"), 1720),
    ]
    one_nation_ahead = shared + [
        BallotBundle(("LIB", "ONP", "FFP", "ALP", "GRN"), 6020),
        BallotBundle(("LIB", "ALP", "ONP", "FFP", "GRN"), 2580),
        BallotBundle(("ONP", "LIB", "FFP", "ALP", "GRN"), 7520),
        BallotBundle(("ONP", "ALP", "LIB", "FFP", "GRN"), 1880),
    ]
    candidates = ["ALP", "LIB", "ONP", "GRN", "FFP"]
    a = run_irv_from_ballots(liberal_ahead, candidates=candidates, mode="full_2cp")
    b = run_irv_from_ballots(one_nation_ahead, candidates=candidates, mode="full_2cp")
    assert a.elimination_order == ["FFP", "GRN", "ONP"] and a.winner == "LIB"
    assert b.elimination_order == ["FFP", "GRN", "LIB"] and b.winner == "ALP"

    matrix = run_irv_from_transfer_matrix(
        {"ALP": 10000, "LIB": 8600, "ONP": 9400, "GRN": 8600, "FFP": 3400},
        {"FFP": {"ONP": 2400 / 3400, "LIB": 1000 / 3400}, "GRN": {"ALP": 7000 / 8600, "LIB": 1600 / 8600},
         "LIB": {"ONP": 0.70, "ALP": 0.30}, "ONP": {"LIB": 0.80, "ALP": 0.20}},
        candidates=candidates,
        round_transfers_to_int=True,
    )
    assert matrix.elimination_order == b.elimination_order and matrix.winner == "ALP"
