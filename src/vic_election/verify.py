"""Checks the counting engine against a commission's published count, round by round and vote by vote."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .decomposition import decompose_distribution_to_ballots
from .irv import run_irv_from_ballots
from .models import BallotBundle, CountResult, DistributionTable


@dataclass
class DistrictVerificationResult:
    district: str
    source_type: str
    passed: bool
    num_candidates: int
    num_rounds: int
    num_ballot_bundles: int
    total_formal_votes: int
    winner: str
    final_totals: dict[str, int]
    errors: list[str] = field(default_factory=list)


def verify_distribution_table(
    table: DistributionTable,
    *,
    mode: Literal["full_2cp", "official"] | None = None,
) -> tuple[DistrictVerificationResult, CountResult, list[BallotBundle]]:
    """
    Decompose `table` into ballots, recount them, and compare every round with the table. Returns the
    verification result (passed + list of mismatches), the recount and the ballots. `mode` defaults to
    'official' for official_* datasets and 'full_2cp' otherwise.
    """
    effective_mode: Literal["full_2cp", "official"] = mode or (
        "official" if table.source_type.startswith("official") else "full_2cp"
    )
    errors: list[str] = []

    def check(label: str, actual: object, expected: object) -> None:
        if actual != expected:
            errors.append(f"{label} mismatch: got {actual!r}, expected {expected!r}")

    ballots = decompose_distribution_to_ballots(table, complete_full_rankings=True)
    result = run_irv_from_ballots(
        ballots=ballots,
        candidates=table.candidates,
        district=table.district,
        mode=effective_mode,
        stop_after_rounds=len(table.steps),
        tie_break_order=[s.excluded_candidate for s in table.steps],
    )

    check("total_formal_votes", int(result.total_formal_votes), table.formal_votes)
    check("majority_threshold", int(result.majority_threshold), table.majority_threshold)
    check("num_rounds", len(result.rounds), len(table.steps))

    for cid, exp_fp in table.first_preferences.items():
        check(f"Round 0 first_preferences[{cid!r}]", int(result.first_preferences.get(cid, -1)), exp_fp)

    for step, r in zip(table.steps, result.rounds):
        check(f"Round {step.step_index} excluded_candidate", r.excluded_candidate, step.excluded_candidate)
        check(f"Round {step.step_index} excluded_votes", int(r.excluded_votes), step.excluded_total)
        for cid, exp_tx in step.transfers.items():
            check(f"Round {step.step_index} transfer[{cid!r}]", int(r.transfers.get(cid, -1)), exp_tx)
        for cid, exp_prog in step.progressive_totals.items():
            check(f"Round {step.step_index} progressive_total[{cid!r}]", int(r.progressive_totals.get(cid, -1)), exp_prog)

    for cid, exp_final in table.final_totals.items():
        check(f"Final total[{cid!r}]", int(result.final_totals.get(cid, -1)), exp_final)

    if table.declared_winner:
        check("winner", result.winner, table.declared_winner)

    return (
        DistrictVerificationResult(
            district=table.district,
            source_type=table.source_type,
            passed=not errors,
            num_candidates=len(table.candidates),
            num_rounds=len(result.rounds),
            num_ballot_bundles=len(ballots),
            total_formal_votes=int(result.total_formal_votes),
            winner=result.winner,
            final_totals={k: int(v) for k, v in result.final_totals.items()},
            errors=errors,
        ),
        result,
        ballots,
    )


def load_distribution_dataset(json_path: Path) -> dict[str, DistributionTable]:
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    return {d: DistributionTable.from_dict(data) for d, data in raw.items()}


def verify_dataset_file(
    json_path: Path,
    *,
    mode: Literal["full_2cp", "official"] | None = None,
) -> list[DistrictVerificationResult]:
    tables = load_distribution_dataset(json_path)
    return [verify_distribution_table(tables[d], mode=mode)[0] for d in sorted(tables)]
