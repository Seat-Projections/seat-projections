#!/usr/bin/env python3
"""
Verify the counting engine against the VEC's published counts: every district's distribution of
preferences is decomposed into ballots, recounted, and compared round by round (0 vote discrepancy).

  .venv/bin/python scripts/verify_counts.py --year 2022                 # all districts, both datasets
  .venv/bin/python scripts/verify_counts.py --year 2022 --district Prahran
"""
from __future__ import annotations

import argparse

from vic_election.config import DATA_DIR
from vic_election.verify import (
    load_distribution_dataset,
    verify_dataset_file,
    verify_distribution_table,
)

# (label, file stem, counting mode); a dataset is skipped if its file doesn't exist for that year
DATASETS = [
    ("official", "OFFICIAL DECLARATION COUNT", "official_{year}", "official"),
    ("full_2cp", "FULL 2CP PREFERENCE DISTRIBUTION", "full_2cp_{year}", "full_2cp"),
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the Victorian IRV counting engine against VEC empirical counts"
    )
    parser.add_argument("--year", choices=["2018", "2022"], default="2022", help="Election year (default: 2022)")
    parser.add_argument(
        "--district",
        type=str,
        default=None,
        help="Inspect a specific district (e.g. 'Sandringham', 'Melbourne', 'Narracan', 'Hawthorn')",
    )
    parser.add_argument(
        "--dataset",
        choices=["official", "full_2cp", "both"],
        default="both",
        help="Which dataset to verify/inspect (default: both; 2018 only has 'official')",
    )
    args = parser.parse_args()

    datasets = [
        (label, path, mode)
        for key, label, stem, mode in DATASETS
        if args.dataset in ("both", key)
        and (path := DATA_DIR / args.year / "distributions" / f"{stem.format(year=args.year)}.json").exists()
    ]
    if not datasets:
        print(f"No {args.dataset} dataset for {args.year}. Run scripts/fetch_vec_{args.year}.py first.")
        return

    if args.district:
        target = args.district.strip().lower()
        for label, path, mode in datasets:
            tables = load_distribution_dataset(path)
            matches = [d for d in tables if d.lower() == target or target in d.lower()]
            if not matches:
                print(f"No district matching {args.district!r} in {path.name}")
                continue
            for d in matches:
                tbl = tables[d]
                v, sim_res, bundles = verify_distribution_table(tbl, mode=mode)  # type: ignore[arg-type]
                print("=" * 90)
                print(f"{d} District {args.year} — {label}")
                print(
                    f"Formal Votes: {tbl.formal_votes:,} | Majority Required: {tbl.majority_threshold:,} | "
                    f"Winner: {sim_res.winner} | VEC Elected: {tbl.declared_winner} | "
                    f"Exact Match: {'PASS (0 vote error)' if v.passed else 'FAIL'}"
                )
                print("=" * 90)
                print(sim_res.format_table())
                print(f"\nDecomposed into {len(bundles)} exact preference order bundles (top 8 by volume):")
                for b in sorted(bundles, key=lambda x: x.count, reverse=True)[:8]:
                    chain = " > ".join(b.ranking[:4]) + (" > ..." if len(b.ranking) > 4 else "")
                    print(f"  {int(b.count):>7,} votes : {chain}")
                print()
        return

    for label, path, mode in datasets:
        verifications = verify_dataset_file(path, mode=mode)  # type: ignore[arg-type]
        passed = sum(1 for v in verifications if v.passed)
        print("=" * 85)
        print(f"Dataset: {args.year} {label} ({path.name})")
        print(f"Districts Verified : {passed}/{len(verifications)} passed")
        print(f"Total Formal Votes : {sum(v.total_formal_votes for v in verifications):,}")
        print(f"Total Count Rounds : {sum(v.num_rounds for v in verifications):,}")
        print(f"Total Ballot Orders: {sum(v.num_ballot_bundles for v in verifications):,}")
        print("=" * 85)
        failures = [v for v in verifications if not v.passed]
        for f in failures:
            print(f"FAIL in {f.district}:")
            for err in f.errors:
                print(f"  - {err}")
        if not failures:
            print("All districts verified with 0 vote discrepancy across all rounds, final counts and winners.\n")


if __name__ == "__main__":
    main()
