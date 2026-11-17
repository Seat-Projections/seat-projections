#!/usr/bin/env python3
"""
Write predictions/benchmarking/forecast_backtests.csv: the canonical benchmark table — every model
x the latest election per eligible state (VIC 2022, NSW 2023, QLD 2024, WA 2025, SA 2026), plus the
unscored VIC 2026 forecast rows. Model2 rows are its "(F)" forecast backtests; replays given the
actual primaries were removed (they did not measure forecasting).

  .venv/bin/python scripts/build_forecast_backtests.py

Reads run_metadata.json/scores.json from each model's output dir and model3's grid_T1.csv.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "predictions" / "modelling"
OUT = ROOT / "predictions" / "benchmarking" / "forecast_backtests.csv"
M3_VARIANT = "L0-C0-R2"

# election -> model1 run id (federal booths of the preceding federal election)
ELECTIONS = {
    "VIC2022": "VIC2022 (2022)",
    "NSW2023": "NSW2023 (2022)",
    "QLD2024": "QLD2024 (2022)",
    "WA2025": "WA2025 (2022)",
    "SA2026": "SA2026 (2025)",
}
FORECAST = {"model1": "VIC2026 (2025)", "model2": "VIC2026 (2022)", "model3": f"VIC2026 (2025) {M3_VARIANT}"}


def meta(model: str, run_dir: str) -> dict:
    p = MOD / model / "output" / run_dir / "run_metadata.json"
    return json.loads(p.read_text()) if p.exists() else {}


def m3_t1(m1_run: str, rescale: str) -> float | None:
    grid = MOD / "model3" / "output" / "grid_T1.csv"
    if not grid.exists():
        return None
    for r in csv.DictReader(grid.open()):
        if r["run_id"] == m1_run and float(r["lam"]) == 0 and r["clip"] == "C0" and r["rescale"] == rescale:
            return float(r["mae_pp"])
    return None


def row(model: str, variant: str, run_id: str, election: str) -> dict:
    m = meta(model, run_id)
    s, dg = m.get("scores", {}), m.get("diagnostics", {})
    t1 = dg.get("t1_mae_pp")
    if model == "model1":
        t1 = m3_t1(run_id, "R0")
    elif model == "model3":
        t1 = m3_t1(run_id.removesuffix(f" {M3_VARIANT}"), "R2")
    return {"model": model, "variant": variant, "run_id": run_id, "election": election,
            "seats_right": s.get("raw_seat_count", ""), "districts": s.get("districts", ""),
            "accuracy": round(s["raw_seat_count"] / s["districts"], 4) if s else "",
            "brier": s.get("brier", ""), "log_loss": s.get("log_loss", ""),
            "t1_mae_pp": t1 if t1 is not None else "",
            "final_two_accuracy": dg.get("final_two_accuracy", ""),
            "predicted_seats": json.dumps(m.get("predicted_seats_mean", {})),
            "actual_seats": json.dumps(m.get("actual_seats", {}))}


def main() -> None:
    rows = []
    for model, run_dir in FORECAST.items():
        rows.append(row(model, "forecast — not yet scored", run_dir, "VIC2026"))
    for election in reversed(sorted(ELECTIONS, key=lambda e: e[-4:])):
        m1 = ELECTIONS[election]
        rows.append(row("model1", "federal booths, hard assignment, no rescale", m1, election))
        rows.append(row("model3", M3_VARIANT, f"{m1} {M3_VARIANT}", election))
        rows.append(row("model2", "forecast (previous-election inputs only)",
                        f"{election} (F)", election))
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
