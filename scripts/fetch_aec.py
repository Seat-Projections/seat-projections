#!/usr/bin/env python3
"""
Fetch AEC Tally Room results down to polling-place level for the federal elections the benchmarks use.

  .venv/bin/python scripts/fetch_aec.py                       # every election, the states in config.AEC_STATES
  .venv/bin/python scripts/fetch_aec.py --year 2025 --states VIC SA
"""
from __future__ import annotations

import argparse

from vic_election.aec import fetch_aec_event
from vic_election.config import AEC_EVENTS, AEC_SENATE_BALLOT_STATES, AEC_STATES, federal_data_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--year", type=int, choices=sorted(AEC_EVENTS), nargs="*", default=sorted(AEC_EVENTS))
    parser.add_argument("--states", nargs="*", help="Override the states fetched (default: those with a benchmark run)")
    parser.add_argument("--senate-ballot-states", nargs="*",
                        help="States whose large ballot-level Senate files are fetched (default: Victoria for 2022 and 2025)")
    parser.add_argument("--refresh", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()

    for year in args.year:
        states = tuple(args.states) if args.states else AEC_STATES[year]
        ballot_states = tuple(args.senate_ballot_states) if args.senate_ballot_states is not None else AEC_SENATE_BALLOT_STATES[year]
        out_dir = federal_data_dir(year)
        print(f"Fetching AEC {year} (event {AEC_EVENTS[year]}) for {', '.join(states)} into {out_dir} ...")
        m = fetch_aec_event(AEC_EVENTS[year], out_dir, states, refresh=args.refresh, senate_ballot_states=ballot_states)
        print(f"  {m['file_count']} files, {int(m['total_bytes']) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
