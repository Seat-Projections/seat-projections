#!/usr/bin/env python3
"""Build data/benchmarks/polls/final_polls.csv from the Wikipedia articles it cites.

For each scored state election, downloads the pinned wikitext of the article (action=raw&oldid=,
cached in the gitignored data/benchmarks/polls/raw/), parses the lower-house voting-intention
table, and keeps polls with fieldwork end <= election day - 1; for each pollster, its latest poll
whose end date is within 35 days of the newest such poll.

Columns: election, pollster, fieldwork_end, alp, lnp, grn, onp, oth, source.
lnp = the Coalition (LIB+NAT added when polled separately, LNP where merged). onp is blank where
the poll did not report One Nation separately. oth = every other column (independents, KAP, SFF…).
Rows whose "firm" is not a named polling company (e.g. a newspaper's own reader survey) are dropped.
"""
from __future__ import annotations

import csv
import re
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "benchmarks" / "polls" / "raw"
OUT = ROOT / "data" / "benchmarks" / "polls" / "final_polls.csv"

# Pinned article revisions (oldid), retrieved 16 Nov 2026.
ARTICLES = {
    "VIC2022": ("2022 Victorian state election", 1385403947, date(2022, 11, 26)),
    "NSW2023": ("2023 New South Wales state election", 1385613308, date(2023, 3, 25)),
    "QLD2024": ("2024 Queensland state election", 1385922628, date(2024, 10, 26)),
    "WA2025": ("2025 Western Australian state election", 1381217185, date(2025, 3, 8)),
    "SA2026": ("Opinion polling for the 2026 South Australian state election", 1369474692, date(2026, 3, 21)),
}
WINDOW_DAYS = 35
USER_AGENT = "seatprojections/0.1 (+https://seatprojections.au)"

POLLSTERS = {
    "newspoll": "newspoll", "roymorgan": "roy-morgan", "resolvestrategic": "resolve",
    "resolve": "resolve", "freshwaterstrategy": "freshwater", "freshwater": "freshwater",
    "redbridge": "redbridge", "redbridgegroup": "redbridge", "lonergan": "lonergan",
    "lonerganresearch": "lonergan", "ucomms": "ucomms", "onlineresearchunit": "online-research-unit",
    "dynata": "dynata", "yougov": "yougov", "demosau": "demosau", "essential": "essential", "foxhedgehog": "fox-and-hedgehog",
    "foxandhedgehog": "fox-and-hedgehog",
}

MONTHS = {m: i for i, m in enumerate(
    "January February March April May June July August September October November December".split(), 1)}
MONTHS.update({m[:3]: i for m, i in MONTHS.items()}  # Mar, Feb, … abbreviations
              | {"Sept": 9, "Jun": 6, "Jul": 7})

# party-column label (uppercase, cleaned) -> output category
CAT = {"ALP": "alp", "LIB": "lnp", "NAT": "lnp", "LNP": "lnp", "CLP": "lnp", "L/NP": "lnp",
       "GRN": "grn", "GREENS": "grn",
       "ON": "onp", "ONP": "onp", "PHON": "onp", "ONE NATION": "onp"}


def clean(text: str) -> str:
    """Strip refs, comments, templates, links, markup from a wikitext fragment."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"<ref[^>]*/>", "", text)
    text = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    # label-bearing templates whose display text we want before the generic strip
    text = re.sub(r"\{\{tooltip\|([^|}]*)\|[^}]*\}\}", r"\1", text, flags=re.I)
    text = re.sub(r"\{\{colou?red link\|[^|}]*\|[^|}]*\|([^|}]*)\}\}", r"\1", text, flags=re.I)
    for _ in range(6):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[[^|\]]*\|([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    return re.sub(r"'{2,}", "", text).strip()


def cells(chunk: str) -> list[tuple[str, list[str]]]:
    """Rows of a wikitable chunk -> [(marker, [cell, ...])] with '!' or '|' markers."""
    out = []
    for row in chunk.split("|-"):
        items: list[tuple[str, str]] = []
        for line in row.split("\n"):
            line = line.rstrip()
            if line.startswith("!") and not line.startswith("|-"):
                parts = re.split(r"!!", line[1:])
                items += [("!", p) for p in parts]
            elif line.startswith("|") and not line.startswith(("|-", "|}", "|+")):
                parts = re.split(r"\|\|", line[1:])
                items += [("|", p) for p in parts]
        if items:
            out.append((items[0][0], [c for _, c in items]))
    return out


def split_attr(cell: str) -> tuple[int, str]:
    """(colspan, content) for a wikitable cell with optional `attr="v"|` prefixes."""
    span = 1
    m = re.match(r"^([^|]*)\|(.*)$", cell, flags=re.S)
    if m and re.search(r"(?:colspan|rowspan|style|width|class|scope|data|align|bgcolor)\s*=", m.group(1)):
        attrs, content = m.group(1), m.group(2)
        cs = re.search(r"colspan\s*=\s*\"?(\d+)", attrs)
        if cs:
            span = int(cs.group(1))
        return span, content
    return span, cell


def percent(cell: str) -> float | None:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", cell)
    return float(m.group(1)) if m else None


def end_date(text: str) -> date | None:
    """Fieldwork end = the last 'D Month YYYY' (or trailing 'Month YYYY') in the cell."""
    t = clean(text)
    found = None
    for m in re.finditer(r"(\d{1,2})\s+([A-Z][a-z]+)\s+,?\s*(\d{4})", t):
        if m.group(2) in MONTHS:
            found = date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    if found is None:
        m = re.search(r"([A-Z][a-z]+)\s+(\d{4})", t)
        if m and m.group(1) in MONTHS:
            import calendar
            y, mo = int(m.group(2)), MONTHS[m.group(1)]
            found = date(y, mo, calendar.monthrange(y, mo)[1])
    return found


def party_columns(table: str) -> list[str]:
    """Party labels of the primary-vote columns, from the header row under the 'Primary vote' span."""
    m = re.search(r"colspan\s*=\s*\"?(\d+)\b[^|]*\|\s*(?:\[\[[^|\]]*\|)?\s*Primary vote", table)
    if not m:
        raise ValueError("no 'Primary vote' header span")
    n = int(m.group(1))
    rest = table[m.end():]
    row = rest[rest.index("|-"):]
    labels = []
    for line in row.split("\n"):
        if not line.strip() or line.startswith("|-"):
            continue
        if not line.startswith("!"):
            break
        for part in re.split(r"!!", line[1:]):
            _, content = split_attr(part)
            label = clean(content).upper()
            if label:
                labels.append(label)
            if len(labels) == n:
                return labels
    return labels[:n]


def find_table(wikitext: str) -> str:
    for m in re.finditer(r"\{\|[^\n]*", wikitext):
        start = m.start()
        depth, i = 0, start
        while True:
            nxt = re.search(r"\{\||\|\}", wikitext[i:])
            if not nxt:
                break
            i += nxt.start()
            if wikitext[i:i + 2] == "{|":
                depth += 1
                i += 2
            else:
                depth -= 1
                i += 2
                if depth == 0:
                    seg = wikitext[start:i]
                    if "Primary vote" in seg and re.search(r"!.*?\|\s*Firm", seg):
                        return seg
                    break
    raise ValueError("no voting-intention table found")


def parse_table(table: str) -> list[dict]:
    labels = party_columns(table)
    cats = [CAT.get(l, "oth") for l in labels]
    rows = []
    for marker, cell_list in cells(table):
        if marker != "!" or len(cell_list) < 2:
            continue
        span, date_txt = split_attr(cell_list[0])
        if span != 1:  # e.g. the "election result" row whose date cell spans two columns
            continue
        d = end_date(date_txt)
        vals = cell_list[1:]
        if not vals:
            continue
        _, firm_txt = split_attr(vals[0])
        firm_key = re.sub(r"[^a-z]", "", clean(firm_txt).lower())
        pollster = POLLSTERS.get(firm_key)
        if pollster is None:
            skipped = clean(firm_txt)
            if skipped and d:
                print(f"    skipped (no named pollster): {skipped!r} on {date_txt.strip()!r}")
            continue
        rest = vals[1:]
        if rest:
            _, sample_txt = split_attr(rest[0])
            if re.fullmatch(r"[\d,]+", clean(sample_txt)):
                rest = rest[1:]  # sample-size column
        totals = {"alp": 0.0, "lnp": 0.0, "grn": 0.0, "onp": None, "oth": 0.0}
        col = 0
        on_seen = False
        for cell in rest:
            if col >= len(labels):
                break
            span, content = split_attr(cell)
            v = percent(content)
            covered = cats[col:col + span]
            if v is not None:
                cat = covered[0] if covered else "oth"
                if cat == "onp":
                    totals["onp"] = (totals["onp"] or 0.0) + v
                    on_seen = True
                else:
                    totals[cat] += v
            col += span
        if d is None:
            continue
        rows.append({"pollster": pollster, "fieldwork_end": d, "cats": cats,
                     "alp": totals["alp"], "lnp": totals["lnp"], "grn": totals["grn"],
                     "onp": totals["onp"], "oth": totals["oth"]})
    return rows


def fetch(election: str, page: str, oldid: int, refresh: bool) -> str:
    RAW.mkdir(parents=True, exist_ok=True)
    cache = RAW / f"{election}.wiki"
    if cache.exists() and not refresh:
        return cache.read_text(encoding="utf-8")
    url = f"https://en.wikipedia.org/w/index.php?action=raw&oldid={oldid}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8")
    cache.write_text(text, encoding="utf-8")
    return text


def main() -> None:
    refresh = "--refresh" in sys.argv
    out_rows = []
    for el, (page, oldid, election_day) in ARTICLES.items():
        print(f"{el}: {page} (oldid {oldid})")
        polls = [r for r in parse_table(find_table(fetch(el, page, oldid, refresh)))
                 if r["fieldwork_end"] <= election_day - timedelta(days=1)]
        newest = max(r["fieldwork_end"] for r in polls)
        window = [r for r in polls if r["fieldwork_end"] >= newest - timedelta(days=WINDOW_DAYS)]
        latest: dict[str, dict] = {}
        for r in sorted(window, key=lambda x: x["fieldwork_end"]):
            latest[r["pollster"]] = r
        src = f"https://en.wikipedia.org/wiki/{page.replace(' ', '_')}?oldid={oldid}"
        for r in sorted(latest.values(), key=lambda x: -x["fieldwork_end"].toordinal()):
            def fmt(v):
                return "" if v is None else f"{v:g}"
            out_rows.append({
                "election": el, "pollster": r["pollster"],
                "fieldwork_end": r["fieldwork_end"].isoformat(),
                "alp": fmt(r["alp"]), "lnp": fmt(r["lnp"]), "grn": fmt(r["grn"]),
                "onp": fmt(r["onp"]), "oth": fmt(r["oth"]), "source": src})
            print(f"    {r['pollster']:22s} {r['fieldwork_end']}  "
                  f"alp {r['alp']} lnp {r['lnp']} grn {r['grn']} onp {r['onp']} oth {r['oth']}")
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["election", "pollster", "fieldwork_end",
                                          "alp", "lnp", "grn", "onp", "oth", "source"])
        w.writeheader()
        w.writerows(out_rows)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(out_rows)} rows")


if __name__ == "__main__":
    main()
