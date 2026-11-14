"""Data records shared by the counting engine, the VEC parsers and the verifier."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    name: str
    party: str = ""
    ballot_position: int | None = None

    to_dict = asdict

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Candidate:
        return cls(d["candidate_id"], d.get("name", d["candidate_id"]), d.get("party", ""), d.get("ballot_position"))


@dataclass(frozen=True)
class BallotBundle:
    ranking: tuple[str, ...]
    count: int | float

    def __post_init__(self) -> None:
        if not isinstance(self.ranking, tuple):
            object.__setattr__(self, "ranking", tuple(self.ranking))
        if not self.ranking or self.count < 0:
            raise ValueError(f"Invalid BallotBundle: ranking={self.ranking}, count={self.count}")

    def to_dict(self) -> dict[str, Any]:
        return {"ranking": list(self.ranking), "count": self.count}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BallotBundle:
        return cls(tuple(d["ranking"]), d["count"])


@dataclass(frozen=True)
class RoundTransfer:
    round_number: int
    excluded_candidate: str
    excluded_votes: int | float
    transfers: dict[str, int | float]
    progressive_totals: dict[str, int | float]
    exhausted_votes: int | float = 0

    to_dict = asdict


@dataclass
class CountResult:
    district: str
    total_formal_votes: int | float
    majority_threshold: int | float
    first_preferences: dict[str, int | float]
    rounds: list[RoundTransfer]
    final_totals: dict[str, int | float]
    winner: str
    runner_up: str | None = None
    candidates: dict[str, Candidate] = field(default_factory=dict)

    @property
    def elimination_order(self) -> list[str]:
        return [r.excluded_candidate for r in self.rounds]

    def final_percentages(self) -> dict[str, float]:
        tot = self.total_formal_votes
        return {c: (v / tot) * 100.0 if tot else 0.0 for c, v in self.final_totals.items()}

    to_dict = asdict

    def format_table(self) -> str:
        cands = list(self.first_preferences.keys())
        headers = ["Stage", *cands, "TOTAL"]

        def fmt(v: int | float | None) -> str:
            if v is None:
                return ""
            return f"{int(round(v)):,}" if isinstance(v, int) or v.is_integer() else f"{v:,.2f}"

        rows = [["First preference votes", *(fmt(self.first_preferences.get(c)) for c in cands), fmt(self.total_formal_votes)]]
        for r in self.rounds:
            rows.append([
                f"Transfer of {fmt(r.excluded_votes)} ({r.excluded_candidate})",
                *(fmt(r.transfers[c]) if c in r.transfers else "" for c in cands),
                fmt(r.excluded_votes),
            ])
            label = "FINAL TOTAL" if r == self.rounds[-1] else f"Progressive Total (Round {r.round_number})"
            rows.append([
                label,
                *(fmt(r.progressive_totals[c]) if c in r.progressive_totals else "" for c in cands),
                fmt(sum(r.progressive_totals.values())),
            ])

        widths = [max(len(str(r[i])) for r in [headers, *rows]) for i in range(len(headers))]

        def fmt_row(r: list[str]) -> str:
            return " | ".join(r[i].ljust(widths[i]) if i == 0 else r[i].rjust(widths[i]) for i in range(len(headers)))

        return "\n".join([fmt_row(headers), "-+-".join("-" * w for w in widths), *(fmt_row(r) for r in rows)])


@dataclass(frozen=True)
class DistributionStep:
    step_index: int
    excluded_candidate: str
    excluded_total: int
    transfers: dict[str, int]
    progressive_totals: dict[str, int]

    to_dict = asdict

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DistributionStep:
        return cls(
            int(d["step_index"]),
            d["excluded_candidate"],
            int(d["excluded_total"]),
            {k: int(v) for k, v in d["transfers"].items()},
            {k: int(v) for k, v in d["progressive_totals"].items()},
        )


@dataclass
class DistributionTable:
    district: str
    source_type: str
    formal_votes: int
    majority_threshold: int
    candidates: list[Candidate]
    first_preferences: dict[str, int]
    steps: list[DistributionStep]
    final_totals: dict[str, int]
    declared_winner: str | None = None
    enrolment: int | None = None
    informal_votes: int | None = None
    source_url: str | None = None
    two_candidate_preferred: dict[str, int] | None = None

    @property
    def candidate_ids(self) -> list[str]:
        return [c.candidate_id for c in self.candidates]

    @property
    def is_full_2cp(self) -> bool:
        return len(self.final_totals) <= 2

    to_dict = asdict

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DistributionTable:
        return cls(
            district=d["district"],
            source_type=d["source_type"],
            formal_votes=int(d["formal_votes"]),
            majority_threshold=int(d["majority_threshold"]),
            candidates=[Candidate.from_dict(c) for c in d["candidates"]],
            first_preferences={k: int(v) for k, v in d["first_preferences"].items()},
            steps=[DistributionStep.from_dict(s) for s in d["steps"]],
            final_totals={k: int(v) for k, v in d["final_totals"].items()},
            declared_winner=d.get("declared_winner"),
            enrolment=d.get("enrolment"),
            informal_votes=d.get("informal_votes"),
            source_url=d.get("source_url"),
            two_candidate_preferred={k: int(v) for k, v in tcp.items()} if (tcp := d.get("two_candidate_preferred")) else None,
        )
