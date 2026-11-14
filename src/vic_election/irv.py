"""
Instant-runoff (full preferential) counting engine.

Two entry points share one core loop: `run_irv_from_ballots` transfers real ballot parcels to their next
continuing preference, and `run_irv_from_transfer_matrix` splits an excluded candidate's pile by a
party-level flow matrix (used by the forecasting models). Both can run to the final two (`full_2cp`,
as in the VEC's full distributions) or stop once a candidate holds a majority (`official`).
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from .models import BallotBundle, Candidate, CountResult, RoundTransfer

CountMode = Literal["full_2cp", "official"]
# For fractional vote totals (simulated counts) "more than half" is total/2 plus a vanishing margin
FRACTIONAL_MAJORITY_EPSILON = 1e-9


def compute_majority_threshold(total_formal_votes: int | float) -> int | float:
    """Votes needed for an absolute majority: more than half of the formal votes."""
    if isinstance(total_formal_votes, int) or total_formal_votes.is_integer():
        return (int(round(total_formal_votes)) // 2) + 1
    return (total_formal_votes / 2.0) + FRACTIONAL_MAJORITY_EPSILON


def select_excluded_candidate(
    continuing: Sequence[str],
    current_totals: Mapping[str, int | float],
    history_totals: Sequence[Mapping[str, int | float]],
    tie_break_order: Sequence[str] | None = None,
) -> str:
    """
    The continuing candidate with the fewest votes. Ties are broken by looking back through earlier
    counts, then by `tie_break_order` (e.g. the order the commission actually excluded candidates in).
    """
    min_votes = min(current_totals[c] for c in continuing)
    tied = [c for c in continuing if current_totals[c] == min_votes]
    if len(tied) == 1:
        return tied[0]

    # Electoral Act 2002 (Vic) s 114(5): look back at preceding counts from most recent
    # to earliest and exclude the tied candidate with the fewest votes at the most recent
    # preceding count where they were not all equal.
    for past_totals in reversed(history_totals):
        past_min = min(past_totals[c] for c in tied)
        narrowed = [c for c in tied if past_totals[c] == past_min]
        if len(narrowed) == 1:
            return narrowed[0]
        if len(narrowed) < len(tied):
            tied = narrowed

    if tie_break_order:
        for c in tie_break_order:
            if c in tied:
                return c
    return tied[0]


def _normalise_candidates(
    candidates: Sequence[Candidate | str] | None,
    discovered_ids: Sequence[str],
) -> tuple[list[str], dict[str, Candidate]]:
    cand_map: dict[str, Candidate] = {}
    for idx, item in enumerate(candidates or ()):
        c = item if isinstance(item, Candidate) else Candidate(str(item), str(item), ballot_position=idx + 1)
        cand_map.setdefault(c.candidate_id, c)
    for cid in discovered_ids:
        cand_map.setdefault(cid, Candidate(cid, cid, ballot_position=len(cand_map) + 1))
    return list(cand_map.keys()), cand_map


def _run_irv_core(
    ordered_ids: list[str],
    cand_map: dict[str, Candidate],
    initial_totals: dict[str, int | float],
    transfer_fn: Callable[[str, int | float, list[str]], tuple[dict[str, int | float], int | float]],
    *,
    district: str,
    mode: CountMode,
    stop_after_rounds: int | None,
    tie_break_order: Sequence[str] | None,
) -> CountResult:
    """
    Exclude the lowest candidate and redistribute with `transfer_fn(excluded, votes, continuing) ->
    (transfers, exhausted)` until the stopping rule for `mode` is met (or `stop_after_rounds` rounds).
    """
    if not ordered_ids:
        raise ValueError("Cannot run IRV count with zero candidates")

    continuing = list(ordered_ids)
    current_totals = dict(initial_totals)
    first_preferences = dict(initial_totals)
    total_formal_votes = sum(first_preferences.values())
    majority_threshold = compute_majority_threshold(total_formal_votes)

    rounds: list[RoundTransfer] = []
    history: list[dict[str, int | float]] = [dict(first_preferences)]

    def finished() -> bool:
        if stop_after_rounds is not None and len(rounds) >= stop_after_rounds:
            return True
        if mode == "official":  # stop as soon as someone has an absolute majority
            return len(continuing) <= 1 or max(current_totals.values()) >= majority_threshold
        return len(continuing) <= 2  # full_2cp: always count down to the final two

    while not finished():

        excluded = select_excluded_candidate(continuing, current_totals, history, tie_break_order)
        excluded_votes = current_totals.pop(excluded)
        continuing.remove(excluded)

        transfers, exhausted = transfer_fn(excluded, excluded_votes, continuing)
        for c in continuing:
            current_totals[c] += transfers[c]

        snapshot = dict(current_totals)
        history.append(snapshot)
        rounds.append(
            RoundTransfer(len(rounds) + 1, excluded, excluded_votes, transfers, snapshot, exhausted)
        )

    max_votes = max(current_totals.values())
    top_tied = [c for c in continuing if current_totals[c] == max_votes]
    if len(top_tied) == 1:
        winner = top_tied[0]
    else:
        # A tie for first is resolved like a tie for exclusion: whoever was behind at the most recent
        # earlier count loses (s 114(5) applied to the final count), so the winner is the one not "excluded".
        loser = select_excluded_candidate(top_tied, current_totals, history, tie_break_order)
        winner = next(c for c in top_tied if c != loser)
    others = [c for c in continuing if c != winner]
    runner_up = max(others, key=current_totals.__getitem__) if others else None

    return CountResult(
        district=district,
        total_formal_votes=total_formal_votes,
        majority_threshold=majority_threshold,
        first_preferences=first_preferences,
        rounds=rounds,
        final_totals=dict(current_totals),
        winner=winner,
        runner_up=runner_up,
        candidates=cand_map,
    )


def run_irv_from_ballots(
    ballots: Sequence[BallotBundle | tuple[Sequence[str], int | float]],
    candidates: Sequence[Candidate | str] | None = None,
    *,
    district: str = "",
    mode: CountMode = "full_2cp",
    stop_after_rounds: int | None = None,
    tie_break_order: Sequence[str] | None = None,
) -> CountResult:
    """
    Count weighted ballot rankings. Each parcel moves to its next continuing preference when its holder is
    excluded; parcels with no continuing preference left exhaust. Candidates default to those on the ballots.
    """
    bundles = [b if isinstance(b, BallotBundle) else BallotBundle(tuple(b[0]), b[1]) for b in ballots]
    discovered = list(dict.fromkeys(cid for b in bundles for cid in b.ranking))
    ordered_ids, cand_map = _normalise_candidates(candidates, discovered)
    continuing_set = set(ordered_ids)

    # Track active ballot parcels per continuing candidate as (ranking, next_search_idx, count)
    buckets: dict[str, list[tuple[tuple[str, ...], int, int | float]]] = {c: [] for c in ordered_ids}
    initial_totals: dict[str, int | float] = {c: 0 for c in ordered_ids}

    for b in bundles:
        if b.count == 0:
            continue
        idx, cid = next(((i, c) for i, c in enumerate(b.ranking) if c in continuing_set), (-1, ""))
        if not cid:
            raise ValueError(f"Ballot ranking {b.ranking} contains no valid candidate")
        buckets[cid].append((b.ranking, idx + 1, b.count))
        initial_totals[cid] += b.count

    def transfer_ballots(
        excluded: str, _excl_votes: int | float, continuing: list[str]
    ) -> tuple[dict[str, int | float], int | float]:
        continuing_set.discard(excluded)
        transfers: dict[str, int | float] = {c: 0 for c in continuing}
        exhausted: int | float = 0
        for ranking, start_idx, count in buckets.pop(excluded):
            for idx in range(start_idx, len(ranking)):
                target = ranking[idx]
                if target in continuing_set:
                    buckets[target].append((ranking, idx + 1, count))
                    transfers[target] += count
                    break
            else:
                exhausted += count
        return transfers, exhausted

    return _run_irv_core(
        ordered_ids,
        cand_map,
        initial_totals,
        transfer_ballots,
        district=district,
        mode=mode,
        stop_after_rounds=stop_after_rounds,
        tie_break_order=tie_break_order,
    )


def _largest_remainder_split(
    total: int, weights: Mapping[str, float], continuing: Sequence[str]
) -> dict[str, int]:
    w_sum = sum(max(0.0, weights.get(c, 0.0)) for c in continuing)
    if w_sum <= 0:
        q, r = divmod(total, len(continuing))
        return {c: q + (i < r) for i, c in enumerate(continuing)}
    exact = {c: (total * max(0.0, weights.get(c, 0.0))) / w_sum for c in continuing}
    floors = {c: int(exact[c]) for c in continuing}
    for c in sorted(continuing, key=lambda c: (exact[c] - floors[c], exact[c]), reverse=True)[: total - sum(floors.values())]:
        floors[c] += 1
    return floors


def run_irv_from_transfer_matrix(
    first_preferences: Mapping[str, int | float],
    transfer_flows: Mapping[str, Mapping[str, float]],
    *,
    candidates: Sequence[Candidate | str] | None = None,
    district: str = "",
    mode: CountMode = "full_2cp",
    stop_after_rounds: int | None = None,
    round_transfers_to_int: bool = False,
    tie_break_order: Sequence[str] | None = None,
) -> CountResult:
    """
    Count from first preferences and a flow matrix `transfer_flows[excluded][recipient]` (relative weights,
    renormalised over the continuing candidates at each exclusion). A candidate with no flows splits evenly.
    With `round_transfers_to_int` every transfer is a whole number of votes (largest-remainder rounding).
    """
    ordered_ids, cand_map = _normalise_candidates(candidates, list(first_preferences.keys()))
    initial_totals: dict[str, int | float] = {
        c: int(round(first_preferences.get(c, 0))) if round_transfers_to_int else first_preferences.get(c, 0)
        for c in ordered_ids
    }

    def transfer_by_matrix(
        excluded: str, excluded_votes: int | float, continuing: list[str]
    ) -> tuple[dict[str, int | float], int | float]:
        flows = transfer_flows.get(excluded, {})
        if round_transfers_to_int:
            return dict(_largest_remainder_split(int(round(excluded_votes)), flows, continuing)), 0
        w_sum = sum(max(0.0, flows.get(c, 0.0)) for c in continuing)
        if w_sum > 0:
            return {c: excluded_votes * (max(0.0, flows.get(c, 0.0)) / w_sum) for c in continuing}, 0
        return {c: excluded_votes / len(continuing) for c in continuing}, 0

    return _run_irv_core(
        ordered_ids,
        cand_map,
        initial_totals,
        transfer_by_matrix,
        district=district,
        mode=mode,
        stop_after_rounds=stop_after_rounds,
        tie_break_order=tie_break_order,
    )
