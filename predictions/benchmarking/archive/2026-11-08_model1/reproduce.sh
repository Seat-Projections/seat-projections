#!/usr/bin/env bash
# Reproduces every run in this archive from scratch (downloads are cached under data/).
set -euo pipefail
cd "$(dirname "$0")/../../../.."
.venv/bin/python scripts/fetch_vec_2022.py                  # VEC 2022 results (Victorian winners)
.venv/bin/python scripts/fetch_aec.py                       # AEC polling-place results (every election and state in config.AEC_STATES)
.venv/bin/python scripts/build_district_flows.py            # Victorian boundaries (EBC) and collated flows
.venv/bin/python scripts/fetch_state_winners.py             # QLD/WA/SA/NSW declared winners (cached after first run)
.venv/bin/python scripts/check_booth_assignment.py          # booth -> district checks (other boundaries download on first use)
.venv/bin/python predictions/modelling/model1/run_model1.py --all --runs 1000 --seed 1
