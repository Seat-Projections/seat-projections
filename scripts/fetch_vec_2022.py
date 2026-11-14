#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

from vic_election.data_fetcher import fetch_all_2022_vec_data


def main() -> None:
    root_dir = Path(__file__).resolve().parent.parent
    data_dir = root_dir / "data" / "2022"
    print(f"Fetching 2022 VEC Lower House data into {data_dir} ...")
    summary = fetch_all_2022_vec_data(data_dir)
    print(
        f"Done! Stored:\n"
        f"  - {summary['official_count']} official 2022 district distributions\n"
        f"  - {summary['indicative_count']} indicative 2022 full preference distributions\n"
        f"  - {summary['full_2cp_count']} complete 2CP district distributions & ballot bundles"
    )


if __name__ == "__main__":
    main()
