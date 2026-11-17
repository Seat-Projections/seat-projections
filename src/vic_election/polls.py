"""Shared final-poll loading and averaging for the benchmark backtests.

`data/benchmarks/polls/final_polls.csv` holds, per state election, each pollster's latest
lower-house poll inside the 35-day window (built by `scripts/fetch_final_polls.py`). Both model2's
`(F)` backtests and model3's poll rescaling must average it identically, so the rule lives here.
"""
from __future__ import annotations

import csv
from pathlib import Path

from vic_election.config import ROOT

FINAL_POLLS = ROOT / "data" / "benchmarks" / "polls" / "final_polls.csv"

BLOC_KEYS = ("ALP", "LNP", "GRN", "ON", "OTH")


def load_final_polls(election: str, path: Path = FINAL_POLLS) -> list[dict]:
    """Rows of final_polls.csv for one election ("VIC2022", "SA2026", …)."""
    with path.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["election"] == election]
    if not rows:
        raise SystemExit(f"no rows for {election} in {path}")
    return rows


def final_poll_mean(rows: list[dict], on_unpolled: float | None = None,
                    oth_floor: bool = True) -> dict[str, float]:
    """Statewide poll average in percentage points over the ALP/LNP/GRN/ON/OTH blocs.

    ALP/LNP/GRN are averaged over every row. ON is averaged only over the rows that report it;
    when no row does, `on_unpolled` supplies the target (None = drop ON, i.e. it stays inside OTH).
    OTH is the remainder to 100; with `oth_floor` it cannot go below 0 (model2's rule —
    model3 rescaling keeps the unfloored remainder). The result is renormalised to sum to 100.
    """
    mean = {c: sum(float(r[c]) for r in rows) / len(rows) for c in ("alp", "lnp", "grn")}
    on_rows = [r for r in rows if r.get("onp") not in (None, "")]
    out = {"ALP": mean["alp"], "LNP": mean["lnp"], "GRN": mean["grn"]}
    if on_rows:
        out["ON"] = sum(float(r["onp"]) for r in on_rows) / len(on_rows)
    elif on_unpolled:
        out["ON"] = on_unpolled
    out["OTH"] = 100.0 - sum(out.values())
    if oth_floor:
        out["OTH"] = max(out["OTH"], 0.0)
    z = sum(out.values())
    return {k: 100 * v / z for k, v in out.items()}
