"""Model 3: soft booth->district splitting and poll rescaling."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "predictions" / "modelling" / "model3"))
sys.path.insert(0, str(ROOT / "predictions" / "modelling" / "model1"))

import model3  # noqa: E402
from vic_election.geo import District  # noqa: E402


def square(name: str, x0: float, x1: float, y0: float = 0.0, y1: float = 1.0) -> District:
    ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    return District(name, "", [[ring]], (x0, y0, x1, y1))


# Two districts sharing the edge lon=0.01 (~1.11 km wide each)
A = square("A", 0.0, 0.01)
B = square("B", 0.01, 0.02)
DISTRICTS = [A, B]


def test_lam0_one_hot() -> None:
    dists = model3.nearby_districts(0.005, 0.5, DISTRICTS)
    assert model3.split_weights(dists, 0, "A") == {"A": 1.0}


def test_boundary_point_splits_evenly() -> None:
    dists = model3.nearby_districts(0.01, 0.5, DISTRICTS)  # exactly on the shared edge
    w = model3.split_weights(dists, 1.18, "A")
    assert w["A"] == pytest.approx(0.5)
    assert w["B"] == pytest.approx(0.5)


def test_one_km_inside_gives_70_30() -> None:
    # ~1 km inside A from the shared edge: own weight ~0.70 at lam = 1.18 km
    lon = 0.01 - 1.0 / (model3.KM_PER_DEGREE_LON * math.cos(math.radians(0.5)))
    dists = model3.nearby_districts(lon, 0.5, DISTRICTS)
    w = model3.split_weights(dists, 1.18, "A")
    assert w["A"] == pytest.approx(0.70, abs=0.01)


def test_weights_sum_to_one() -> None:
    for lon in (0.002, 0.005, 0.008, 0.01):
        w = model3.split_weights(model3.nearby_districts(lon, 0.5, DISTRICTS), 0.5, "A")
        assert sum(w.values()) == pytest.approx(1.0)


def test_c1_drops_neighbour_outside_division() -> None:
    # Own division ends at lon=0.005; district B's nearest point (0.01, .) is ~0.55 km outside -> dropped
    div = square("Div", -0.005, 0.005)
    assert model3.clip_keep(0.008, 0.5, B, div) is False
    # ... but a division reaching B's boundary keeps it
    assert model3.clip_keep(0.008, 0.5, B, square("Div2", -0.005, 0.012)) is True


def _two_district_primaries():
    return {"D1": {"ALP": 600.0, "LP": 400.0}, "D2": {"ALP": 300.0, "LP": 300.0, "NP": 200.0, "GRN": 200.0}}


def _shares(prim):
    return model3._statewide_shares(prim, False)


def test_r2_hits_target() -> None:
    target = {"ALP": 0.45, "LNP": 0.40, "GRN": 0.10, "OTH": 0.05}
    prim = _two_district_primaries()
    prim["D2"]["UAPP"] = 0.0  # OTH needs a member to absorb a positive target
    prim["D2"]["UAPP"] = 100.0
    out = model3.rescale_r2(prim, target)
    got = _shares(out)
    for c, t in target.items():
        assert got[c] == pytest.approx(t, abs=1e-6)
    # district totals preserved
    for d in prim:
        assert sum(out[d].values()) == pytest.approx(sum(prim[d].values()))


def test_r3_hits_target() -> None:
    target = {"ALP": 0.45, "LNP": 0.40, "GRN": 0.10, "OTH": 0.05}
    prim = _two_district_primaries()
    prim["D2"]["UAPP"] = 100.0
    out = model3.rescale_r3(prim, target)
    got = _shares(out)
    for c, t in target.items():
        assert got[c] == pytest.approx(t, abs=1e-6)


def test_shares_stay_in_unit_interval() -> None:
    prim = _two_district_primaries()
    prim["D2"]["UAPP"] = 100.0
    for fn in (model3.rescale_r2, model3.rescale_r3):
        out = fn(prim, {"ALP": 0.45, "LNP": 0.40, "GRN": 0.10, "OTH": 0.05})
        for d, pv in out.items():
            for p, v in pv.items():
                s = v / sum(pv.values())
                assert 0 < s < 1 or v == 0


def test_category_members_scale_together() -> None:
    prim = _two_district_primaries()
    prim["D2"]["UAPP"] = 100.0
    target = {"ALP": 0.30, "LNP": 0.55, "GRN": 0.10, "OTH": 0.05}
    # R2: one factor per category -> member ratio exactly preserved
    out = model3.rescale_r2(prim, target)
    assert out["D2"]["LP"] / out["D2"]["NP"] == pytest.approx(prim["D2"]["LP"] / prim["D2"]["NP"], rel=1e-9)
    # R3: equal logit constant per member -> their log-odds gap is unchanged
    out = model3.rescale_r3(prim, target)
    gap = math.log(out["D2"]["LP"] / out["D2"]["NP"])
    old = math.log(prim["D2"]["LP"] / prim["D2"]["NP"])
    assert gap == pytest.approx(old, abs=0.05)


def test_poll_target_with_and_without_on() -> None:
    rows = [{"alp": "40", "lnp": "30", "grn": "10", "onp": "12"},
            {"alp": "36", "lnp": "34", "grn": "12", "onp": "10"}]
    t = model3.poll_target(rows)
    assert t["ON"] == pytest.approx(0.11)
    assert t["ALP"] == pytest.approx(0.38)
    assert sum(t.values()) == pytest.approx(1.0)
    rows[0]["onp"] = rows[1]["onp"] = ""
    t = model3.poll_target(rows)
    assert "ON" not in t
    assert t["OTH"] == pytest.approx(1 - t["ALP"] - t["LNP"] - t["GRN"])
    # a blank ON row is averaged only over rows reporting ON
    rows = [{"alp": "40", "lnp": "30", "grn": "10", "onp": "20"},
            {"alp": "36", "lnp": "34", "grn": "12", "onp": ""}]
    assert model3.poll_target(rows)["ON"] == pytest.approx(0.20)


@pytest.mark.skipif(not (ROOT / "data" / "federal" / "2022").exists(), reason="AEC 2022 data not fetched")
def test_lam0_matches_model1_primaries() -> None:
    import run_model3  # noqa: E402
    import model1  # noqa: E402
    ctx = run_model3.setup("VIC2022 (2022)")
    prim, _ = run_model3.primaries_for(ctx, 0, "C0")
    expected = model1.district_primaries(ctx["booths"], ctx["candidates"], ctx["assignment"])
    assert set(prim) == set(expected)
    for d in prim:
        for p, v in expected[d].items():
            assert prim[d][p] == pytest.approx(v)
