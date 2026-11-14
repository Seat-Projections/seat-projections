#!/usr/bin/env python3
"""
Freeze a model's runs into predictions/benchmarking/archive/<date>_<model>/: copies every run's outputs,
the declared-winner files and the booth-assignment checks, and writes results.csv (one row per run) plus
reproduce.sh. Write a WRITEUP.md alongside.

  .venv/bin/python scripts/archive_benchmarks.py model1
  .venv/bin/python scripts/archive_benchmarks.py model2 --tag candidates   # -> <date>_model2_candidates/

An archive that has been published should not be overwritten: use --tag for a second archive on the same day.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import date
from vic_election.config import BENCHMARKS_DIR, MODELS_DIR, ROOT, WINNERS_DIR

CHECKS_STEM = "booth_assignment_checks"  # written by scripts/check_booth_assignment.py (.md and .json)

# Inputs each model needs before its own runner (downloads are cached under data/)
PREREQUISITES = {
    "model1": """.venv/bin/python scripts/fetch_vec_2022.py                  # VEC 2022 results (Victorian winners)
.venv/bin/python scripts/fetch_aec.py                       # AEC polling-place results (every election and state in config.AEC_STATES)
.venv/bin/python scripts/build_district_flows.py            # Victorian boundaries (EBC) and collated flows
.venv/bin/python scripts/fetch_state_winners.py             # QLD/WA/SA/NSW declared winners (cached after first run)
.venv/bin/python scripts/check_booth_assignment.py          # booth -> district checks (other boundaries download on first use)
.venv/bin/python scripts/fetch_vic2026_candidates.py       # VEC 2026 candidate list: restricts VIC2026 (2025) to the declared field""",
    "model2": """.venv/bin/python scripts/fetch_vec_2022.py                  # VEC 2022 primaries and full distributions (baseline, flows, winners)
.venv/bin/python scripts/fetch_state_winners.py             # QLD/WA/SA/NSW declared winners (cached after first run)
.venv/bin/python scripts/fetch_state_dops.py                # QLD/WA/SA/NSW distributions of preferences (ECQ, WAEC, ECSA, NSWEC)
.venv/bin/python scripts/fetch_aec.py                       # AEC 2025 polling places (One Nation pattern via model1)
.venv/bin/python scripts/build_district_flows.py            # Victorian boundaries (EBC)
.venv/bin/python predictions/modelling/model1/run_model1.py "VIC2026 (2025)"   # One Nation's federal 2025 pattern
.venv/bin/python scripts/fetch_vic2026_candidates.py       # VEC 2026 candidate list (nominations closed 9 Nov 2026)
# data/2026/polls_vic2026.csv (electiontracker.au register as downloaded) and data/2026/independents_vic2026.csv are committed inputs""",
}

REPRODUCE = """#!/usr/bin/env bash
# Reproduces every run in this archive from scratch (downloads are cached under data/).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
{prerequisites}
.venv/bin/python predictions/modelling/{model}/run_{model}.py --all --runs {runs} --seed {seed}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=sorted(PREREQUISITES))
    parser.add_argument("--tag", help="suffix for the archive folder, e.g. candidates -> <date>_<model>_candidates")
    args = parser.parse_args()
    src = MODELS_DIR / args.model / "output"
    dest = BENCHMARKS_DIR / "archive" / f"{date.today().isoformat()}_{args.model}{f'_{args.tag}' if args.tag else ''}"
    dest.mkdir(parents=True, exist_ok=True)

    rows, meta = [], {}
    for run_dir in sorted(p for p in src.iterdir() if p.is_dir()):
        meta = json.loads((run_dir / "run_metadata.json").read_text())
        shutil.copytree(run_dir, dest / "runs" / run_dir.name, dirs_exist_ok=True)
        s, inp = meta.get("scores") or {}, meta["inputs"]
        rows.append({
            "run": run_dir.name, "model": meta["model"], "state": inp["state"], "state_election": inp["state_election"],
            "data_from": inp.get("federal_election") or inp.get("baseline", ""), "districts": inp["districts"],
            "raw_seat_count": s.get("raw_seat_count", ""), "accuracy_pct": round(100 * s["raw_seat_count"] / s["districts"], 1) if s else "",
            "brier": s.get("brier", ""), "log_loss": s.get("log_loss", ""),
            "final_two_accuracy": (meta.get("diagnostics") or {}).get("final_two_accuracy", ""),
            "tcp_margin_mae": (meta.get("diagnostics") or {}).get("tcp_margin_mae", ""),
            "predicted_seats": "; ".join(f"{p} {v}" for p, v in sorted(meta["predicted_seats_mean"].items(), key=lambda kv: -kv[1])),
            "actual_seats": "; ".join(f"{p} {v}" for p, v in sorted(meta.get("actual_seats", {}).items(), key=lambda kv: -kv[1])),
        })
    with (dest / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    if args.model == "model1":  # model2 is scored on VEC results, not the other states' winner files
        shutil.copytree(WINNERS_DIR, dest / "winners", dirs_exist_ok=True)
        for suffix in (".md", ".json"):
            checks = BENCHMARKS_DIR / f"{CHECKS_STEM}{suffix}"
            if checks.exists():
                shutil.copy(checks, dest / checks.name)
    (dest / "reproduce.sh").write_text(
        REPRODUCE.format(prerequisites=PREREQUISITES[args.model], model=args.model, runs=meta["runs"], seed=meta["seed"]), encoding="utf-8")
    (dest / "reproduce.sh").chmod(0o755)
    print(f"Archived {len(rows)} runs to {dest.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
