from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_site  # noqa: E402


def test_baseline_2022_seat_tally():
    baseline = build_site.load_baseline()
    assert len(baseline["districts"]) == 88
    assert baseline["seats"] == {"ALP": 56, "LP": 19, "NP": 9, "GRN": 4}
    # every district has a real two-candidate final and a positive margin
    for name, d in baseline["districts"].items():
        assert len(d["final_two"]) == 2, name
        assert d["final_two"][0]["name"] == d["winner"], name
        assert d["margin_pct"] > 0, name
        assert d["formal_votes"] > 0 and d["enrolment"] > 0, name
