"""Model 2: Luce flow fit, the core-stage count (README worked example), One Nation priors, poll average."""
from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "predictions" / "modelling" / "model2"))
import model2  # noqa: E402  (model code lives in predictions/modelling/model2/)
from model2 import Cand  # noqa: E402


def test_luce_fit_recovers_strengths() -> None:
    true = {"ALP": 0.6, "LP": 0.3, "GRN": 0.1}
    obs = []
    for alts in (["ALP", "LP", "GRN"], ["ALP", "LP"], ["LP", "GRN"], ["ALP", "GRN"]):
        z = sum(true[a] for a in alts)
        obs.append(("D", "AJP", alts, [1000 * true[a] / z for a in alts]))
    w = model2.fit_flows(obs, iters=300)["AJP"]
    k = 3000 / (3000 + model2.SHRINK_VOTES)  # shrunk towards the pooled fit, which here is the same data
    assert w["ALP"] / w["LP"] == pytest.approx(2.0, rel=1e-3) and w["LP"] / w["GRN"] == pytest.approx(3.0, rel=1e-3)
    assert 0 < k < 1


def test_leave_one_district_out_drops_that_district() -> None:
    obs = [("A", "AJP", ["ALP", "LP"], [900.0, 100.0]), ("B", "AJP", ["ALP", "LP"], [100.0, 900.0])]
    w = model2.fit_flows(obs, exclude_district="A")["AJP"]
    assert w["LP"] > w["ALP"]


def _worked_example_strengths(on_to_lp: float, lp_to_on: float):
    """Strengths reproducing the README's worked example (Stage 2 flows, Stage 3 splits)."""
    rows = {
        "GRN": {"ALP": 80, "LP": 12, "ON": 8}, "IND*": {"ALP": 35, "LP": 35, "ON": 30},
        "FFP": {"ALP": 15, "LP": 35, "ON": 50}, "AJP": {"ALP": 45, "LP": 25, "ON": 30},
        "ON": {"LP": on_to_lp, "ALP": 1 - on_to_lp}, "LP": {"ON": lp_to_on, "ALP": 1 - lp_to_on},
    }
    return lambda src, dst: rows[src][dst]


def test_core_stage_worked_example() -> None:
    """README worked example, counted with origin tracking: One Nation's pile is part inherited minor votes."""
    seat = [Cand("ALP", "ALP", 26), Cand("LP", "LP", 23), Cand("ON", "ON", 22), Cand("GRN", "GRN", 12),
            Cand("IND", "IND*", 8), Cand("FFP", "FFP", 5), Cand("AJP", "AJP", 4)]
    core = {"ALP", "LP", "ON"}
    st = _worked_example_strengths(0.80, 0.65)
    winner, final, first = model2.count_seat(seat, core, st)
    assert first == "ON" and winner == "LP"
    # 22 One Nation votes split 80/20; the 7.1 inherited minor votes split by their own parties' flows
    assert final["LP"] == pytest.approx(51.09, abs=0.01) and final["ALP"] == pytest.approx(48.91, abs=0.01)
    # 1-point swing Liberal -> One Nation: Liberal is excluded instead and Labor wins
    swung = [Cand("LP", "LP", 22) if c.cid == "LP" else Cand("ON", "ON", 23) if c.cid == "ON" else c for c in seat]
    winner, final, first = model2.count_seat(swung, core, st)
    assert first == "LP" and winner == "ALP"
    assert final["ALP"] == pytest.approx(52.47, abs=0.01) and final["ON"] == pytest.approx(47.53, abs=0.01)


def test_origin_tracking_splits_inherited_votes_by_their_own_party() -> None:
    # Greens (minor, 10) split Labor 5, independent 4.5, Liberal 0.5. Labor (20 own + 5 Greens-origin) is then
    # excluded: its own 20 split 50/50, the 5 Greens-origin votes follow Greens flows (90:10 independent:Liberal).
    seat = [Cand("LP", "LP", 35), Cand("IND", "IND*", 35), Cand("ALP", "ALP", 20), Cand("GRN", "GRN", 10)]
    rows = {"GRN": {"ALP": 1.0, "IND*": 0.9, "LP": 0.1}, "ALP": {"LP": 0.5, "IND*": 0.5}}
    winner, final, first = model2.count_seat(seat, {"LP", "IND", "ALP"}, lambda s, d: rows[s][d])
    assert first == "ALP" and winner == "IND"
    assert final["IND"] == pytest.approx(54.0) and final["LP"] == pytest.approx(46.0)  # pile split by Labor's flows: 52-48


def test_simple_three_candidate_seat() -> None:
    seat = [Cand("ALP", "ALP", 40), Cand("LP", "LP", 35), Cand("GRN", "GRN", 25)]
    st = lambda src, dst: {"ALP": 0.8, "LP": 0.2}.get(dst, 0.5) if src == "GRN" else 0.5  # noqa: E731
    winner, final, first = model2.count_seat(seat, {"ALP", "LP", "GRN"}, st)
    assert (winner, first) == ("ALP", "GRN") and final["ALP"] == pytest.approx(60.0)


def test_central_count_records_every_stage_and_conserves_votes() -> None:
    seat = [Cand("ALP", "ALP", 40), Cand("LP", "LP", 35), Cand("GRN", "GRN", 20), Cand("AJP", "AJP", 5)]
    st = lambda src, dst: {"ALP": 0.7, "LP": 0.2, "GRN": 0.6}.get(dst, 0.1)  # noqa: E731
    c = model2.central_count(seat, st)
    assert [s["excluded"] for s in c["stages"]] == [["AJP"], ["GRN"]]  # one candidate per stage, lowest first
    for s in c["stages"]:
        assert sum(s["transfers"].values()) == pytest.approx(s["pile"]) and sum(s["totals"].values()) == pytest.approx(100.0)
    assert set(c["final"]) == {"ALP", "LP"} and sum(c["final"].values()) == pytest.approx(100.0) and c["winner"] == "ALP"
    order: list = []
    model2.count_seat(seat, {"ALP", "LP", "GRN"}, st, order=order)
    assert order == ["GRN"]


def test_exhausted_votes_leave_the_count() -> None:
    seat = [Cand("ALP", "ALP", 40), Cand("LP", "LP", 35), Cand("GRN", "GRN", 25)]
    st = lambda src, dst: {"ALP": 0.6, "LP": 0.1, model2.EXH: 0.3}.get(dst, 0.5) if src == "GRN" else 0.5  # noqa: E731
    winner, final, _ = model2.count_seat(seat, {"ALP", "LP", "GRN"}, st, exhaust=True)
    assert winner == "ALP" and final["ALP"] == pytest.approx(55.0) and final["LP"] == pytest.approx(37.5)


def test_exhaustion_is_fitted_as_an_alternative() -> None:
    tables = {"D": {"candidates": [{"candidate_id": c, "party": p} for c, p in (("a", "ALP"), ("l", "LP"), ("g", "GRN"))],
                    "steps": [{"excluded_candidate": "g", "transfers": {"a": 60.0, "l": 10.0}, "exhausted": 30.0}]}}
    obs = model2.flow_observations(tables, exhaust=True)
    assert obs == [("D", "GRN", ["ALP", "LP", model2.EXH], [60.0, 10.0, 30.0])]
    w = model2.fit_flows(obs, iters=200)["GRN"]
    assert w[model2.EXH] / w["ALP"] == pytest.approx(0.5, rel=1e-3)


def test_replay_strengths_ignore_one_nation_priors() -> None:
    w = {model2.POOLED: {"ALP": 0.5, "LP": 0.5}, "ON": {"ALP": 0.3, "LP": 0.7}}
    assert model2.strength_fn(w, None)("ON", "LP") == pytest.approx(0.7)


def test_one_nation_priors_set_conditional_splits() -> None:
    w = {model2.POOLED: {"ALP": 0.5, "LP": 0.4, "GRN": 0.1}, "LP": {"ALP": 0.7, "GRN": 0.3}, "ALP": {"LP": 0.4, "GRN": 0.6}}
    draw = model2.central_on_priors()
    st = lambda s, d: model2.on_strength(w, s, d, draw)  # noqa: E731
    assert st("ON", "LP") / (st("ON", "LP") + st("ON", "ALP")) == pytest.approx(0.80)
    assert st("LP", "ON") / (st("LP", "ON") + st("LP", "ALP")) == pytest.approx(0.65)
    assert st("ALP", "LP") / (st("ALP", "LP") + st("ALP", "ON")) == pytest.approx(0.60)


def test_poll_average_uses_latest_per_pollster_in_window() -> None:
    rows = [
        {"pollster": "a", "fieldwork_end": "2026-10-01", "alp": "30", "lnp": "30", "onp": "20", "grn": "10", "others": "10", "eligible_for_average": "true"},
        {"pollster": "a", "fieldwork_end": "2026-11-01", "alp": "20", "lnp": "40", "onp": "20", "grn": "10", "others": "10", "eligible_for_average": "true"},
        {"pollster": "b", "fieldwork_end": "2026-10-20", "alp": "24", "lnp": "36", "onp": "20", "grn": "10", "others": "10", "eligible_for_average": "true"},
        {"pollster": "c", "fieldwork_end": "2026-11-02", "alp": "0", "lnp": "0", "onp": "0", "grn": "0", "others": "100", "eligible_for_average": "false"},
        {"pollster": "d", "fieldwork_end": "2026-08-01", "alp": "50", "lnp": "10", "onp": "20", "grn": "10", "others": "10", "eligible_for_average": "true"},
    ]
    avg = model2.poll_average(rows, window_days=35)
    assert avg["ALP"] == pytest.approx(22.0) and avg["LNP"] == pytest.approx(38.0)
    assert len(avg["_polls"]) == 2


def test_draw_primaries_sum_to_100_with_credible_independent() -> None:
    seats = {"A": model2.Seat("A", "R", [Cand("a", "ALP", 400), Cand("l", "LP", 350), Cand("g", "GRN", 150), Cand("i", "IND*", 100)])}
    field = [{"district": "A", "candidate": c, "party_group": p} for c, p in
             (("NEW, Labor", "ALP"), ("NEW, Lib", "LP"), ("NEW, Green", "GRN"), ("NEW, ON", "ON"), ("NEW, Ind", "IND*"))]
    base = model2.baseline_2026(seats, field, {"A": 5.0}, [{"district": "A", "candidate": "NEW, Ind", "credible": "Y", "prior_mean": "20", "prior_sd": "1"}])
    assert "i" not in base.shares["A"] and "NEW, Ind" in base.seats["A"].credible
    assert base.shares["A"]["NEW, Labor"] == pytest.approx(40.0) and base.shares["A"]["NEW, Lib"] == pytest.approx(35.0)
    polls = {"ALP": 25, "LNP": 30, "GRN": 15, "ON": 20, "OTH": 10}
    draw = model2.draw_primaries(base, polls, random.Random(0))["A"]
    assert sum(draw.values()) == pytest.approx(100.0) and 15 < draw["NEW, Ind"] < 25


def test_baseline_coalition_keeps_its_share_when_one_partner_stands() -> None:
    seats = {"S": model2.Seat("S", "R", [Cand("n", "NP", 300), Cand("l", "LP", 200), Cand("a", "ALP", 500)])}
    field = [{"district": "S", "candidate": "NAT, New", "party_group": "NP"}, {"district": "S", "candidate": "ALP, New", "party_group": "ALP"}]
    base = model2.baseline_2026(seats, field, {"S": 1.0}, [])
    assert base.shares["S"]["NAT, New"] == pytest.approx(50.0)  # the Nationals inherit the absent Liberals' 20%


def _poll(pollster, end, eligible="true", alp="30", lnp="30", onp="20", grn="10", others="10"):
    return {"pollster": pollster, "fieldwork_end": end, "alp": alp, "lnp": lnp,
            "onp": onp, "grn": grn, "others": others, "eligible_for_average": eligible}


def test_poll_average_as_of_publication_lag() -> None:
    rows = [_poll("a", "2026-10-11"), _poll("b", "2026-10-12"), _poll("a", "2026-10-01")]
    avg = model2.poll_average(rows, as_of="2026-10-13")          # ends 11 Oct: +2 = 13 Oct, counts
    assert avg["_polls"] == ["a 2026-10-11"]
    avg = model2.poll_average(rows, as_of="2026-10-14")          # ends 12 Oct: +2 = 14 Oct, counts
    assert sorted(avg["_polls"]) == ["a 2026-10-11", "b 2026-10-12"]
    avg = model2.poll_average(rows, as_of="2026-10-12")          # 11/12 Oct still unpublished; 1 Oct poll stands
    assert avg["_polls"] == ["a 2026-10-01"]
    with pytest.raises(ValueError):
        model2.poll_average(rows, as_of="2026-10-02")            # nothing published yet


def test_poll_average_as_of_none_unchanged() -> None:
    rows = [_poll("a", "2026-10-01"), _poll("a", "2026-11-01", alp="20", lnp="40"),
            _poll("b", "2026-10-20", alp="24", lnp="36"), _poll("d", "2026-08-01")]
    avg = model2.poll_average(rows)
    assert avg["ALP"] == pytest.approx(22.0) and len(avg["_polls"]) == 2


def test_poll_average_as_of_window_anchors_to_newest_remaining() -> None:
    # as_of cuts the newest poll; the 35-day window re-anchors to the poll before it.
    rows = [_poll("a", "2026-11-01"), _poll("b", "2026-08-01"),
            _poll("c", "2026-09-05", alp="40", lnp="20")]
    avg = model2.poll_average(rows, as_of="2026-10-01")
    assert sorted(avg["_polls"]) == ["b 2026-08-01", "c 2026-09-05"]  # a excluded; window anchored to c, b within 35d
    avg = model2.poll_average(rows, as_of="2026-09-01")
    assert avg["_polls"] == ["b 2026-08-01"]                          # only b published; window anchored to it


def test_snapshot_schedule_every_14_days_and_dedupe() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "predictions" / "modelling" / "model2"))
    import run_model2  # noqa: E402
    rows = [_poll("a", "2026-08-20"), _poll("b", "2026-09-10"), _poll("c", "2026-10-01")]
    dates = run_model2.snapshot_schedule(rows, start="2026-09-01", today=__import__("datetime").date(2026, 10, 15))
    # dates every 14 days from start; 09-29 skipped: its poll set {a,b} is identical to 09-15's
    assert dates == [__import__("datetime").date(2026, 9, 1), __import__("datetime").date(2026, 9, 15),
                     __import__("datetime").date(2026, 10, 13)]
    # a poll published (end+2) before 09-29 changes that date's set, so 09-29 is kept too
    rows3 = rows + [_poll("e", "2026-09-17")]
    d = run_model2.snapshot_schedule(rows3, start="2026-09-01", today=__import__("datetime").date(2026, 10, 15))
    assert d == [__import__("datetime").date(2026, 9, 1), __import__("datetime").date(2026, 9, 15),
                 __import__("datetime").date(2026, 9, 29), __import__("datetime").date(2026, 10, 13)]
