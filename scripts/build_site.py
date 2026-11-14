#!/usr/bin/env python3
"""
Builds the static data for the public website (site/data/), served by GitHub Pages at
https://seatprojections.au:

  districts.geojson        88 Legislative Assembly districts (2021 redivision), coordinates rounded
                           to 5 decimals; properties reduced to district name and region
  victoria_outline.json    state outline rings, used to mask the map outside Victoria
  baseline_2022.json       2022 VEC result per district: elected member, final-two (2CP) votes and
                           margin, first preferences per candidate, enrolment, VEC source link,
                           plus statewide seat tally and first-preference shares
  model1_vic2026.json      the models' 2026 forecasts, copied from visualiser/data/ (rebuilt there by
  model2_vic2026.json      scripts/build_visualiser.py --forecasts-only after each model run)
  benchmarks.json          archived benchmark results (model1 forecast runs, model2 B1 replays)
  site.json                REPO_URL, build date, forecast run metadata, downloadable-file register
  downloads/               public copies of the datasets listed on the Methodology page

The HTML/CSS/JS under site/ is hand-written; this script only produces data files.
Serve with:  .venv/bin/python -m http.server 8001 -d site
"""
from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIS = ROOT / "visualiser" / "data"
SITE = ROOT / "site"
DATA = SITE / "data"
DOWNLOADS = DATA / "downloads"

# Placeholder until the public repository exists; written into site/data/site.json and read by the
# pages, so switching to the real URL is a one-line change here.
REPO_URL = "https://github.com/Seat-Projections/seat-projections"

ARCHIVE = ROOT / "predictions" / "benchmarking" / "archive"
MODEL1_CANDIDATES = ARCHIVE / "2026-11-09_model1_candidates" / "results.csv"
MODEL2_CANDIDATES = ARCHIVE / "2026-11-09_model2_candidates" / "results.csv"

# Registered VEC party name -> party-group code used across the models
PARTY_GROUP = {
    "Australian Labor Party - Victorian Branch": "ALP",
    "Liberal": "LP",
    "The Nationals": "NP",
    "Australian Greens": "GRN",
    "Pauline Hanson's One Nation": "ON",
    "Independent": "IND",
}
GROUP_ORDER = ("ALP", "LP", "NP", "GRN", "ON", "IND", "OTH")


def group_of(party_name: str) -> str:
    return PARTY_GROUP.get(party_name, "OTH")


def round_coords(obj, digits: int = 5):
    if isinstance(obj, list):
        if obj and isinstance(obj[0], (int, float)):
            return [round(v, digits) for v in obj]
        return [round_coords(v, digits) for v in obj]
    return obj


def load_baseline() -> dict:
    """2022 VEC results per district. Two-candidate-preferred finals come from the full-preference
    file (the official count stops at 50%, so its `final_totals` can hold >2 candidates); first
    preferences, enrolment and source links come from the official distribution pages."""
    official = json.loads((ROOT / "data" / "2022" / "distributions" / "official_2022.json").read_text())
    full2cp = json.loads((ROOT / "data" / "2022" / "distributions" / "full_2cp_2022.json").read_text())
    geojson = json.loads((VIS / "districts.geojson").read_text())
    regions = {f["properties"]["district"]: f["properties"]["region"] for f in geojson["features"]}

    districts = {}
    seats = Counter()
    fp_by_group = Counter()
    totals = {"formal": 0, "informal": 0, "enrolment": 0}

    for name, off in official.items():
        full = full2cp[name]
        cand_party = {c["name"]: c["party"] for c in off["candidates"]}
        # The indicative workbooks' first preferences differ from the official count by a handful
        # of votes; the official distribution pages are authoritative for primaries and totals.

        winner = off["declared_winner"]
        winner_party = cand_party[winner]
        winner_group = group_of(winner_party)
        seats[winner_group] += 1

        primary = sorted(
            (
                {
                    "name": c["name"],
                    "party": c["party"],
                    "group": group_of(c["party"]),
                    "votes": off["first_preferences"].get(c["name"], 0),
                }
                for c in off["candidates"]
            ),
            key=lambda c: -c["votes"],
        )
        for c in primary:
            fp_by_group[c["group"]] += c["votes"]

        final = sorted(full["final_totals"].items(), key=lambda kv: -kv[1])
        assert len(final) == 2, name
        final_two = [
            {"name": n, "party": cand_party[n], "group": group_of(cand_party[n]), "votes": v}
            for n, v in final
        ]
        tcp_total = sum(v for _, v in final)
        margin = round(100 * final[0][1] / tcp_total - 50, 2)

        totals["formal"] += off["formal_votes"]
        totals["informal"] += off["informal_votes"]
        totals["enrolment"] += off["enrolment"]

        districts[name] = {
            "region": regions.get(name),
            "winner": winner,
            "winner_party": winner_party,
            "winner_group": winner_group,
            "final_two": final_two,
            "margin_pct": margin,
            "primary": primary,
            "formal_votes": off["formal_votes"],
            "informal_votes": off["informal_votes"],
            "enrolment": off["enrolment"],
            "indicative_2cp": full["source_type"] == "indicative_full_2022",
            "source_url": off["source_url"],
        }

    fp_share = {
        g: round(100 * fp_by_group[g] / totals["formal"], 2) for g in GROUP_ORDER
    }
    return {
        "election": "2022 Victorian state election",
        "districts": districts,
        "seats": dict(seats),
        "fp_share": fp_share,
        "totals": totals,
    }


def results_csv(baseline: dict) -> str:
    """One row per district: winner, runner-up, 2CP margin and headline numbers."""
    rows = []
    for name, d in sorted(baseline["districts"].items()):
        a, b = d["final_two"]
        rows.append(
            {
                "district": name,
                "region": d["region"],
                "winner": d["winner"],
                "winner_party": d["winner_party"],
                "winner_group": d["winner_group"],
                "runner_up": b["name"],
                "runner_up_party": b["party"],
                "winner_2cp_pct": round(100 * a["votes"] / (a["votes"] + b["votes"]), 2),
                "margin_2cp_pct": d["margin_pct"],
                "formal_votes": d["formal_votes"],
                "informal_votes": d["informal_votes"],
                "enrolment": d["enrolment"],
                "source_url": d["source_url"],
            }
        )
    import io

    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def benchmarks() -> dict:
    def read(path: Path) -> list[dict]:
        with path.open() as f:
            return list(csv.DictReader(f))

    def slim(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            out.append(
                {
                    "model": r["model"],
                    "run": r["run"],
                    "districts": int(r["districts"]),
                    "data_from": r["data_from"],
                    "raw_seat_count": r["raw_seat_count"],
                    "accuracy_pct": r["accuracy_pct"],
                    "brier": r["brier"],
                    "log_loss": r["log_loss"],
                    "final_two_accuracy": r.get("final_two_accuracy") or None,
                    "tcp_margin_mae": r.get("tcp_margin_mae") or None,
                    "predicted_seats": r["predicted_seats"],
                    "actual_seats": r["actual_seats"] or None,
                }
            )
        return out

    return {
        "model1_runs": slim(read(MODEL1_CANDIDATES)),
        "model2_replays": slim(read(MODEL2_CANDIDATES)),
    }


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    DOWNLOADS.mkdir(parents=True, exist_ok=True)

    baseline = load_baseline()
    (DATA / "baseline_2022.json").write_text(json.dumps(baseline, separators=(",", ":")))

    geojson = json.loads((VIS / "districts.geojson").read_text())
    geojson["features"] = [
        {
            "type": "Feature",
            "properties": {
                "district": f["properties"]["district"],
                "region": f["properties"]["region"],
            },
            "geometry": round_coords(f["geometry"]),
        }
        for f in geojson["features"]
    ]
    geo_text = json.dumps(geojson, separators=(",", ":"))
    (DATA / "districts.geojson").write_text(geo_text)
    (DOWNLOADS / "districts.geojson").write_text(geo_text)

    outline = round_coords(json.loads((VIS / "victoria_outline.json").read_text()))
    (DATA / "victoria_outline.json").write_text(json.dumps(outline, separators=(",", ":")))

    model_meta = {}
    for model in ("model1", "model2"):
        src = VIS / f"{model}_vic2026.json"
        doc = json.loads(src.read_text())
        model_meta[model] = doc["meta"]
        (DATA / src.name).write_text(json.dumps(doc, separators=(",", ":")))

    (DATA / "benchmarks.json").write_text(json.dumps(benchmarks(), separators=(",", ":")))

    # Downloads register: (output filename, source or generator, description)
    copies = [
        (
            "vic2022_district_results.csv",
            None,
            "2022 district results: elected member, final two, 2CP margin, enrolment (derived from VEC distributions)",
        ),
        (
            "model1_seat_probabilities.csv",
            ROOT / "predictions" / "modelling" / "model1" / "output" / "VIC2026 (2025)" / "seat_probabilities.csv",
            "Model 1 forecast: per-district win and final-two probabilities (VIC2026 (2025) run)",
        ),
        (
            "model1_statewide_blocs.csv",
            ROOT / "predictions" / "modelling" / "model1" / "output" / "VIC2026 (2025)" / "statewide_blocs.csv",
            "Model 1 forecast: statewide seat distribution per bloc",
        ),
        (
            "model2_seat_probabilities.csv",
            ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 (2022)" / "seat_probabilities.csv",
            "Model 2 forecast: per-district win and final-two probabilities (VIC2026 (2022) run)",
        ),
        (
            "model2_statewide_blocs.csv",
            ROOT / "predictions" / "modelling" / "model2" / "output" / "VIC2026 (2022)" / "statewide_blocs.csv",
            "Model 2 forecast: statewide seat distribution per bloc",
        ),
        (
            "candidates_vic2026.csv",
            ROOT / "data" / "2026" / "candidates_vic2026.csv",
            "Declared 2026 candidates by district and ballot position (VEC nominations; names and parties only)",
        ),
        (
            "polls_vic2026.csv",
            ROOT / "data" / "2026" / "polls_vic2026.csv",
            "2026 Victorian polling register used for the model2 average (from electiontracker.au)",
        ),
    ]
    (DOWNLOADS / "vic2022_district_results.csv").write_text(results_csv(baseline))
    for fname, src, _desc in copies:
        if src is not None:
            shutil.copyfile(src, DOWNLOADS / fname)

    downloads = [
        {
            "file": fname,
            "size_kb": round((DOWNLOADS / fname).stat().st_size / 1024, 1),
            "description": desc,
        }
        for fname, _src, desc in [("districts.geojson", None, "88 Legislative Assembly district boundaries, 2021 redivision (Electoral Boundaries Commission)")] + copies
    ]

    site = {
        "brand": "Seat Projections",
        "domain": "seatprojections.au",
        "repo_url": REPO_URL,
        "build_date": model_meta["model2"]["timestamp"][:10],
        "models": model_meta,
        "downloads": downloads,
    }
    (DATA / "site.json").write_text(json.dumps(site, indent=1) + "\n")

    for path in sorted(DATA.rglob("*")):
        if path.is_file():
            print(f"{path.relative_to(SITE)}  {path.stat().st_size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
