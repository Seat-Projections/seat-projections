#!/usr/bin/env python3
"""
Score a model run's seat_probabilities.csv against the declared Victorian results.

  .venv/bin/python scripts/score_model.py "predictions/modelling/model1/output/VIC2022 (2022)/seat_probabilities.csv" --year 2022

Writes scores.json next to the forecast. Metrics are defined in predictions/benchmarking/README.md.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from vic_election.benchmark import load_forecast, load_winners, score
from vic_election.config import vec_distributions_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Score seat forecasts: raw seat count, Brier score, log loss")
    parser.add_argument("forecast", type=Path, help="Path to seat_probabilities.csv")
    parser.add_argument("--year", type=int, required=True, choices=[2018, 2022], help="Election the forecast is scored against")
    parser.add_argument("--key", choices=["party", "candidate"], default="party", help="Match outcomes by party group or candidate name")
    args = parser.parse_args()

    winners = load_winners(vec_distributions_path(args.year), args.key)
    result = score(load_forecast(args.forecast, args.key), winners)
    result.update({"forecast": str(args.forecast), "scored_against": f"VEC {args.year} declared winners", "matched_by": args.key})
    (args.forecast.parent / "scores.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Raw seat count: {result['raw_seat_count']}/{result['districts']}")
    print(f"Brier score:    {result['brier']}")
    print(f"Log loss:       {result['log_loss']}")


if __name__ == "__main__":
    main()
