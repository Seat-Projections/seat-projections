#!/usr/bin/env python3
"""Extract the published June/July 2026 YouGov Victorian primary-vote table.

Download the source PDF into the ignored raw directory, then run this script.
Requires pdftotext (Poppler). Writes raw reported percentages, without rounding
corrections or polling adjustments. This is not a combined MRP forecast.
"""
import csv
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/2026/raw/mrp"
SOURCE = (
    "https://actionnetwork.org/user_files/user_files/000/146/615/original/"
    "yougov-vic-mrp-treaty-report-state-voting-intetion-treaty-support.pdf"
)
PARTIES = ("ALP", "LNP", "GRN", "ON", "IND", "OTHER_LEFT", "OTHER_RIGHT")


def extract(text, districts):
    # Only the four detailed table pages, not the summary tables elsewhere.
    pages = [p for p in text.split("\f")
             if "Detailed MRP projection of results in each seat" in p]
    if len(pages) != 4:
        raise ValueError(f"Expected four detailed pages, found {len(pages)}")
    rows = {}
    for page in pages:
        lines = page.splitlines()
        for i, line in enumerate(lines):
            values = re.findall(r"(\d+(?:\.\d+)?)%", line)
            if len(values) != 8:  # seven primaries and a final-pair percentage
                continue
            name = re.split(r"\d", line, maxsplit=1)[0].strip()
            if not name:
                # Three district names wrap across lines in pdftotext's layout.
                name = lines[i - 1].strip() + " " + lines[i + 1].strip()
            if name not in districts or name in rows:
                raise ValueError(f"Unknown or duplicate district: {name!r}")
            primaries = dict(zip(PARTIES, map(float, values[:7])))
            total = sum(primaries.values())
            if not 96 <= total <= 104:
                raise ValueError(f"{name}: implausible rounded primary total {total}")
            rows[name] = {
                "district": name, "region": districts[name],
                **primaries, "reported_total": total,
                "fieldwork_start": "2026-06-16", "fieldwork_end": "2026-07-10",
                "sample": 4003, "source_url": SOURCE,
            }
    if set(rows) != set(districts):
        raise ValueError(f"Missing districts: {sorted(set(districts) - set(rows))}")
    return [rows[d] for d in sorted(rows)]


def main():
    pdf = RAW / "yougov.pdf"
    if not pdf.exists():
        raise SystemExit(f"Download {SOURCE} to {pdf.relative_to(ROOT)} first.")
    text = subprocess.check_output(["pdftotext", "-layout", str(pdf), "-"], text=True)
    geo = json.loads((ROOT / "data/boundaries/vic_assembly_2022/districts.geojson").read_text())
    districts = {f["properties"]["district"]: f["properties"]["region"] for f in geo["features"]}
    rows = extract(text, districts)
    output = RAW / "yougov_primaries.csv"
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Validated {len(rows)} districts across {len(set(districts.values()))} regions.")
    print(f"Reported row totals: {min(r['reported_total'] for r in rows):g}"
          f" to {max(r['reported_total'] for r in rows):g}% (rounded source figures).")
    print(f"Wrote {output.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
