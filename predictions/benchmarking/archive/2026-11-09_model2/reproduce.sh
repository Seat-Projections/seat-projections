#!/usr/bin/env bash
# Reproduces every run in this archive from scratch (downloads are cached under data/).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
.venv/bin/python scripts/fetch_vec_2022.py                  # VEC 2022 primaries and full distributions (baseline, flows, winners)
.venv/bin/python scripts/fetch_state_winners.py             # QLD/WA/SA/NSW declared winners (cached after first run)
.venv/bin/python scripts/fetch_state_dops.py                # QLD/WA/SA/NSW distributions of preferences (ECQ, WAEC, ECSA, NSWEC)
.venv/bin/python scripts/fetch_aec.py                       # AEC 2025 polling places (One Nation pattern via model1)
.venv/bin/python scripts/build_district_flows.py            # Victorian boundaries (EBC)
.venv/bin/python predictions/modelling/model1/run_model1.py "VIC2026 (2025)"   # One Nation's federal 2025 pattern
# data/2026/polls_vic2026.csv (electiontracker.au register as downloaded) and data/2026/independents_vic2026.csv are committed inputs
.venv/bin/python predictions/modelling/model2/run_model2.py --all --runs 5000 --seed 1
