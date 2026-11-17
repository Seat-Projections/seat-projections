"""
Repository paths, AEC election identifiers and the benchmark runs shared by the models, scripts and tests.

A benchmark run is named ``STATEyyyy (federal year)``: the state election being forecast and the federal
election whose polling-place results feed the model (see predictions/benchmarking/README.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
FEDERAL_DATA_DIR = DATA_DIR / "federal"
BOUNDARIES_DIR = DATA_DIR / "boundaries"
FEDERAL_BOUNDARIES_DIR = BOUNDARIES_DIR / "federal"
STATE_BOUNDARIES_DIR = BOUNDARIES_DIR / "states"
VIC_DISTRICTS_DIR = BOUNDARIES_DIR / "vic_assembly_2022"
VIC_DISTRICTS_GEOJSON = VIC_DISTRICTS_DIR / "districts.geojson"
WINNERS_DIR = DATA_DIR / "benchmarks" / "winners"
MODELS_DIR = ROOT / "predictions" / "modelling"
BENCHMARKS_DIR = ROOT / "predictions" / "benchmarking"

# AEC Tally Room event IDs by federal election year
AEC_EVENTS = {2019: 24310, 2022: 27966, 2025: 31496}
# States fetched for each federal election: every state with a benchmark run on that election
AEC_STATES = {2019: ("QLD", "WA", "SA"), 2022: ("VIC", "NSW", "QLD", "WA", "SA"), 2025: ("VIC", "SA")}
# The ballot-level Senate preference files are large; only the states model3 needs for F2 flows (B5, B6, VIC 2026)
AEC_SENATE_BALLOT_STATES = {2019: (), 2022: ("VIC",), 2025: ("VIC", "SA")}


def federal_data_dir(year: int) -> Path:
    return FEDERAL_DATA_DIR / str(year)


def vec_distributions_path(year: int) -> Path:
    """Parsed VEC results (declared winners and full distributions) for a Victorian state election."""
    return DATA_DIR / str(year) / "distributions" / f"official_{year}.json"


@dataclass(frozen=True)
class BenchmarkRun:
    run_id: str
    state: str
    federal_year: int
    state_election: str  # YYYY-MM-DD; selects the state boundaries in force on the day
    winners: str | None  # "vec:<year>" (parsed VEC results) or a data/benchmarks/winners/<name>.csv stem; None if not held

    @property
    def event(self) -> int:
        return AEC_EVENTS[self.federal_year]

    @property
    def federal_dir(self) -> Path:
        return federal_data_dir(self.federal_year)


RUNS = {
    r.run_id: r
    for r in (
        BenchmarkRun("VIC2022 (2022)", "VIC", 2022, "2022-11-26", "vec:2022"),
        BenchmarkRun("NSW2023 (2022)", "NSW", 2022, "2023-03-25", "NSW2023"),
        BenchmarkRun("QLD2024 (2022)", "QLD", 2022, "2024-10-26", "QLD2024"),
        BenchmarkRun("WA2025 (2022)", "WA", 2022, "2025-03-08", "WA2025"),
        BenchmarkRun("SA2026 (2025)", "SA", 2025, "2026-03-21", "SA2026"),
        BenchmarkRun("VIC2026 (2025)", "VIC", 2025, "2026-11-28", None),
    )
}


def majority_of(seats: int) -> int:
    """Seats needed to govern alone (Victoria 45 of 88, SA 24 of 47)."""
    return seats // 2 + 1
