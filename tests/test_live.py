from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import live  # noqa: E402
import build_site  # noqa: E402


FORECAST = {
    "frozen_at": "2026-11-25T22:04:47+00:00", "run_id": "VIC2026 (2022)",
    "git_commit": "abc", "seats": {"LP": 46.0, "ALP": 15.4},
    "blocs": {"COAL": {"seats_mean": 55.4, "p_majority": 0.88},
              "ALP": {"seats_mean": 15.4, "p_majority": 0.0},
              "ON": {"seats_mean": 8.7, "p_majority": 0.0},
              "GRN": {"seats_mean": 8.1, "p_majority": 0.0},
              "IND*": {"seats_mean": 0.4, "p_majority": 0.0}},
    "districts": {
        "Kew": {"slug": "kew", "fav_party": "LP", "fav_name": "Jess Wilson", "p_win": 0.96},
        "Preston": {"slug": "preston", "fav_party": "GRN", "fav_name": "Sam Llop", "p_win": 0.46},
        "Melton": {"slug": "melton", "fav_party": "ALP", "fav_name": "Steve McGhie", "p_win": 0.8},
    },
}


def make_live(entries=()):
    return {"title": "Live: 2026 Victorian election results",
            "coverage_start": "2026-11-28T18:00:00+11:00", "entries": list(entries)}


def entry(i, text, district=None, call=None, time="2026-11-28T21:42:00+11:00"):
    e = {"id": str(i), "time": time, "text": text}
    if district:
        e["district"] = district
    if call:
        e["call"] = call
    return e


def test_norm_party_aliases():
    assert live.norm_party("LP") == "LP" and live.norm_party("lib") == "LP"
    assert live.norm_party("NAT") == "NP" and live.norm_party("Lab") == "ALP"
    assert live.norm_party("onp") == "ON" and live.norm_party("ind") == "IND*"
    assert live.norm_party("OTH") == "OTH"
    assert live.norm_party("ZZZ") is None and live.norm_party("") is None


def test_find_district_case_and_slug():
    d = FORECAST["districts"]
    assert live.find_district("kew", d) == "Kew"
    assert live.find_district("PRESTON", d) == "Preston"
    assert live.find_district(" melton ", d) == "Melton"


def test_find_district_unknown_errors():
    import pytest
    with pytest.raises(SystemExit):
        live.find_district("Keeew", FORECAST["districts"])


def test_call_supersession():
    l = make_live([entry(1, "Kew called for Liberal.", "Kew", "LP"),
                   entry(2, "Recheck: Kew called for Greens.", "Kew", "GRN")])
    calls = live.effective_calls(l["entries"])
    assert calls["Kew"]["call"] == "GRN" and len(calls) == 1


def test_scoreboard_coal_and_correct_pct():
    l = make_live([entry(1, "a", "Kew", "LP"), entry(2, "b", "Melton", "ALP"),
                   entry(3, "c", "Preston", "ON")])
    sb = live.scoreboard(l, FORECAST)
    rows = {r[0]: r for r in sb["rows"]}
    assert rows["Coalition"][1] == 1 and rows["Labor"][1] == 1
    assert sb["called"] == 3 and sb["correct"] == 2  # Kew LP ok, Melton ALP ok, Preston ON wrong


def test_frozen_forecast_is_what_page_uses(tmp_path, monkeypatch):
    """write_live reads only the frozen JSON, never model2_vic2026.json."""
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    fc_file = site / "data" / "live_forecast_vic2026.json"
    live_file = site / "data" / "live_vic2026.json"
    fc_file.write_text(json.dumps(FORECAST))
    live_file.write_text(json.dumps(make_live([entry(1, "Kew called for Liberal.", "Kew", "LP")])))
    out = site / "live"
    monkeypatch.setattr(build_site, "shared_chrome",
                        lambda: ("<header>H</header>", "<footer>F</footer>"))
    assert build_site.write_live(live_file, fc_file, out)
    html = (out / "index.html").read_text()
    assert "Kew called for Liberal." in html and "Jess Wilson" in html


def test_html_escaping_in_feed(tmp_path, monkeypatch):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    fc_file = site / "data" / "live_forecast_vic2026.json"
    live_file = site / "data" / "live_vic2026.json"
    fc_file.write_text(json.dumps(FORECAST))
    live_file.write_text(json.dumps(make_live([entry(1, 'Polls <script>alert(1)</script> "closed"')])))
    monkeypatch.setattr(build_site, "shared_chrome",
                        lambda: ("<header>H</header>", "<footer>F</footer>"))
    build_site.write_live(live_file, fc_file, site / "live")
    html = (site / "live" / "index.html").read_text()
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html


def test_push_git_commands(monkeypatch):
    calls = []
    monkeypatch.setattr(live.subprocess, "run",
                        lambda cmd, **kw: calls.append((cmd, kw)))
    live.git_push("live: Kew called")
    add, commit, push = [c[0] for c in calls]
    assert add[:2] == ["git", "add"] and any("live_vic2026.json" in p for p in add)
    assert commit[:3] == ["git", "commit", "-m"] and commit[3] == "live: Kew called"
    assert push[:2] == ["git", "-c"] and push[-3:] == ["push", "origin", "main"]
    assert all(c[1].get("env", {}).get("TZ") == "UTC" for c in calls)


def test_empty_live_file_renders(tmp_path, monkeypatch):
    site = tmp_path / "site"
    (site / "data").mkdir(parents=True)
    fc_file = site / "data" / "live_forecast_vic2026.json"
    live_file = site / "data" / "live_vic2026.json"
    fc_file.write_text(json.dumps(FORECAST))
    live_file.write_text(json.dumps(make_live()))
    monkeypatch.setattr(build_site, "shared_chrome",
                        lambda: ("<header>H</header>", "<footer>F</footer>"))
    build_site.write_live(live_file, fc_file, site / "live")
    html = (site / "live" / "index.html").read_text()
    assert "0 of 88 seats called" in html
    assert "polls close at 6pm" in html


def test_batch_calls_entry_counts_each_seat():
    import live
    entries = [
        {"id": "1", "time": "2026-11-28T20:00:00+11:00", "text": "Kew", "district": "Kew", "call": "IND*"},
        {"id": "2", "time": "2026-11-28T20:50:00+11:00", "text": "batch",
         "calls": [{"district": "Kew", "call": "LP"}, {"district": "Footscray", "call": "GRN"}]},
    ]
    calls = live.effective_calls(entries)
    assert {d: e["call"] for d, e in calls.items()} == {"Kew": "LP", "Footscray": "GRN"}
    assert calls["Kew"]["id"] == "2"


def test_replace_calls_entry_drops_seats_back_in_doubt():
    import live
    entries = [
        {"id": "1", "time": "2026-11-28T20:47:00+11:00", "text": "a",
         "calls": [{"district": "Geelong", "call": "LP"}, {"district": "Kew", "call": "LP"}]},
        {"id": "2", "time": "2026-11-28T21:34:00+11:00", "text": "b", "replace_calls": True,
         "calls": [{"district": "Kew", "call": "LP"}]},
    ]
    assert list(live.effective_calls(entries)) == ["Kew"]
