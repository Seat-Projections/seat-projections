"""Turns a published distribution-of-preferences table back into ballot bundles that reproduce it exactly."""
from __future__ import annotations

from collections import defaultdict

from .models import BallotBundle, DistributionTable


def decompose_distribution_to_ballots(
    table: DistributionTable,
    *,
    complete_full_rankings: bool = True,
) -> list[BallotBundle]:
    """
    Deterministically decomposes an empirical VEC round-by-round Distribution of
    Preferences table into exact integer-weighted BallotBundle preference orders.

    Mathematical guarantee:
    Running `run_irv_from_ballots` on the returned bundles reproduces Round 0
    first preferences, every round's excluded candidate, every round's transfer
    counts, every round's progressive totals, and the final totals with zero
    vote discrepancy.
    """
    candidate_ids = table.candidate_ids
    continuing = list(candidate_ids)

    # Each candidate holds a FIFO queue of (ranking_prefix, count) parcels
    pools: dict[str, list[tuple[tuple[str, ...], int]]] = {
        c: [((c,), fp)] if (fp := int(table.first_preferences.get(c, 0))) > 0 else []
        for c in candidate_ids
    }

    for step in table.steps:
        excl = step.excluded_candidate
        excl_parcels = pools.pop(excl, [])
        continuing.remove(excl)

        if sum(cnt for _, cnt in excl_parcels) != step.excluded_total:
            raise ValueError(f"{table.district} step {step.step_index}: parcel total != {step.excluded_total}")
        if sum(step.transfers.get(c, 0) for c in continuing) != step.excluded_total:
            raise ValueError(f"{table.district} step {step.step_index}: transfers don't sum to {step.excluded_total}")

        idx, rem = 0, (excl_parcels[0][1] if excl_parcels else 0)
        for recipient in continuing:
            needed = int(step.transfers.get(recipient, 0))
            while needed > 0:
                take = min(needed, rem)
                pools[recipient].append((excl_parcels[idx][0] + (recipient,), take))
                needed -= take
                rem -= take
                if rem == 0 and (idx := idx + 1) < len(excl_parcels):
                    rem = excl_parcels[idx][1]

    merged: dict[tuple[str, ...], int] = defaultdict(int)
    for c in continuing:
        for prefix, cnt in pools[c]:
            if cnt > 0:
                tail = tuple(x for x in candidate_ids if x not in prefix) if complete_full_rankings else ()
                merged[prefix + tail] += cnt

    return [BallotBundle(ranking, count) for ranking, count in merged.items()]
