"""
Scoring seat forecasts against declared results (see predictions/benchmarking/README.md).

A forecast is, for each district, a probability for each outcome (a candidate, or a party group for
models that forecast parties). An outcome missing from a district's forecast has probability 0.
"""
from __future__ import annotations

import csv
import json
import math
import re
from collections import defaultdict
from pathlib import Path

LOG_LOSS_FLOOR = 1e-3  # a winner given probability 0 would make log loss infinite

# Electoral-commission party names -> party-group codes used by the models (matched case-insensitively)
PARTY_GROUPS = {
    "australian labor party - victorian branch": "ALP", "australian labor party": "ALP", "labor": "ALP",
    "liberal": "LP", "the nationals": "NP", "national party": "NP", "australian greens": "GRN", "the greens": "GRN",
    "independent": "IND*", "pauline hanson's one nation": "ON", "one nation": "ON", "family first victoria": "FFP",
    "family first": "FFP", "liberal democrats": "LDP", "libertarian": "LTP", "legalise cannabis victoria": "HMP",
    "animal justice party": "AJP", "victorian socialists": "VNS",
    # 2026 VEC registered names -> the 2022 groups they continue (so 2022 shares and flows carry over)
    "liberal party of australia - victorian division": "LP", "national party of australia - victoria": "NP",
    "australian greens victoria": "GRN", "one nation victoria": "ON", "libertarian party (formerly liberal democrats)": "LDP",
    "democratic labour party (dlp)": "Labour DLP", "shooters, fishers and farmers party victoria": "Shooters, Fishers & Farmers Vic",
}


def party_group(name: str) -> str:
    return PARTY_GROUPS.get(name.strip().lower(), name.strip())


COALITION_GROUPS = ("LP", "NP", "LNP")


def bloc_seats(seats: dict[str, list[int]]) -> dict[str, list[int]]:
    """
    Seats per simulation run with the Liberals and Nationals merged into one Coalition bloc ("COAL"). The sum is
    taken run by run, so its percentiles and majority chance are those of the combined total (adding the
    parties' separate percentiles would not be).
    """
    out: dict[str, list[int]] = {}
    coal = [s for p, s in seats.items() if p in COALITION_GROUPS]
    if coal:
        out["COAL"] = [sum(run) for run in zip(*coal)]
    out.update({p: s for p, s in seats.items() if p not in COALITION_GROUPS})
    return out


def norm_district(name: str) -> str:
    """Key for matching district names across sources ('Collie - Preston' == 'Collie-Preston', 'MacKillop' == 'Mackillop')."""
    return re.sub(r"[^a-z]", "", name.lower())


def score(forecast: dict[str, dict[str, float]], winners: dict[str, str], floor: float = LOG_LOSS_FLOOR) -> dict:
    """
    forecast: district -> {outcome: probability}; winners: district -> winning outcome.
    Only districts present in both are scored.
    """
    districts = sorted(set(forecast) & set(winners))
    correct, brier, log_loss = 0, 0.0, 0.0
    for d in districts:
        probs, won = forecast[d], winners[d]
        if probs and max(probs, key=probs.get) == won:
            correct += 1
        brier += sum((probs.get(k, 0.0) - (k == won)) ** 2 for k in set(probs) | {won})
        log_loss += -math.log(max(probs.get(won, 0.0), floor))
    n = len(districts)
    return {
        "districts": n,
        "raw_seat_count": correct,
        "brier": round(brier / n, 4) if n else None,
        "log_loss": round(log_loss / n, 4) if n else None,
    }


def load_forecast(path: Path, key: str = "party") -> dict[str, dict[str, float]]:
    """Read a standard seat_probabilities.csv; `key` is the column identifying outcomes ('party' or 'candidate')."""
    out: dict[str, dict[str, float]] = defaultdict(dict)
    with path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out[r["district"]][r[key]] = out[r["district"]].get(r[key], 0.0) + float(r["p_win"])
    return dict(out)


def load_winners_csv(path: Path) -> dict[str, str]:
    """District -> winning party group from data/benchmarks/winners/<election>.csv."""
    with path.open(encoding="utf-8") as f:
        return {r["district"]: r["party"] for r in csv.DictReader(f)}


def align_districts(winners: dict[str, str], districts: list[str]) -> dict[str, str]:
    """Re-key winners to the forecast's district names (matched with norm_district); every district must match."""
    by_key = {norm_district(d): w for d, w in winners.items()}
    missing = [d for d in districts if norm_district(d) not in by_key]
    if missing:
        raise KeyError(f"No declared winner for {missing}")
    return {d: by_key[norm_district(d)] for d in districts}


def load_winners(distributions_json: Path, key: str = "party") -> dict[str, str]:
    """Declared winners from a parsed VEC dataset, as party groups ('party') or candidate names ('candidate')."""
    tables = json.loads(distributions_json.read_text(encoding="utf-8"))
    out = {}
    for d, t in tables.items():
        party = {c["candidate_id"]: c["party"] for c in t["candidates"]}
        out[d] = party_group(party[t["declared_winner"]]) if key == "party" else t["declared_winner"]
    return out
