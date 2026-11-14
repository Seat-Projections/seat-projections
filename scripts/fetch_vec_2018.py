#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from vic_election.data_fetcher import fetch_all_2018_vec_data


def main() -> None:
    data_dir = Path(__file__).resolve().parent.parent / "data" / "2018"
    print(f"Fetching 2018 VEC Lower House data into {data_dir} ...")
    summary = fetch_all_2018_vec_data(data_dir)
    print(
        f"Done! Stored {summary['official_count']} district results:\n"
        f"  - {summary['with_distribution']} with a distribution of preferences\n"
        f"  - {summary['won_on_primaries']} won on first preferences (first preferences + 2CP only)"
    )


if __name__ == "__main__":
    main()
