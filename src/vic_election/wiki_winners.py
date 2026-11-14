"""
Declared winners per district parsed from Wikipedia wikitext (post-election pendulums and
"Members of the ... Assembly" tables), used for the NSW, QLD, WA and SA benchmark elections.
"""
from __future__ import annotations

import re

# Party labels used in Wikipedia post-election pendulums -> party-group codes
PENDULUM_PARTIES = {"ALP": "ALP", "LAB": "ALP", "LIB": "LP", "NAT": "NP", "LNP": "LNP", "GRN": "GRN", "IND": "IND*",
                    "ON": "ON", "ONP": "ON", "KAP": "KAP", "SFF": "SFF", "CLP": "CLP"}


def _style_group(style: str) -> str:
    s = style.lower()
    for key, group in (("one nation", "ON"), ("independent", "IND*"), ("green", "GRN"), ("labor", "ALP"),
                       ("liberal national", "LNP"), ("liberal", "LP"), ("national", "NP"), ("katter", "KAP")):
        if key in s:
            return group
    return style


def _cell_text(cell: str) -> str:
    cell = re.sub(r"\{\{[^}]*\}\}|<[^>]+>", "", cell)
    return re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", cell).strip()


def parse_members_table(wikitext: str, year: int | None = None) -> dict[str, str]:
    """
    District -> party group from a Wikipedia 'Members of the ... Assembly' table (one row per member,
    with a district link; party from an {{Australian party style|...}} cell or the cell before the
    district). Tables list by-election replacements too: with `year`, the member whose term spans the
    election and started earliest is kept (the one elected at that election); without it, the first row.
    """
    picks: dict[str, tuple[int, str]] = {}
    for block in wikitext.split("\n|-"):
        d = re.search(r"\[\[Electoral district of ([^|\]]+)(?:\|([^\]]+))?\]\]", block)
        if not d:
            continue
        district = (d.group(2) or d.group(1)).strip()
        style = re.search(r"\{\{Australian party style\|([^}|]+)", block)
        if style:
            party = style.group(1)
        else:  # "|| Name || Party || [[Electoral district of X|X]] || 2018–2026" rows
            cells = [c for c in re.split(r"\|\||\n\|", block) if c.strip()]
            idx = next(i for i, c in enumerate(cells) if "Electoral district of" in c)
            party = (_cell_text(cells[idx - 1]) if idx else "").split("/")[0]  # "Liberal/Independent": elected as Liberal
        term = re.search(r"(\d{4})\s*[–-]\s*(\d{4}|present|current)", block)
        start = int(term.group(1)) if term else 0
        end = 9999 if not term or not term.group(2).isdigit() else int(term.group(2))
        if year is not None and not (start <= year <= end):
            continue
        if district not in picks or (year is not None and start < picks[district][0]):
            picks[district] = (start, _style_group(party))
    return {d: p for d, (_, p) in picks.items()}


def parse_pendulum(wikitext: str) -> dict[str, str]:
    """
    District -> winning party group from a Wikipedia post-election pendulum: each seat row is a district
    link, the member, then the party label. Pendulums list the result of the election itself, before any
    later by-elections or defections.
    """
    out = {}
    lines = [line.strip() for line in wikitext.splitlines()]
    for i, line in enumerate(lines):
        m = re.search(r"\[\[Electoral district of ([^|\]]+)(?:\|([^\]]+))?\]\]", line)
        if not m or i + 2 >= len(lines):
            continue
        label = re.sub(r"<[^>]+>|'''|\[\[|\]\]", "", lines[i + 2].split("|")[-1]).strip().upper()
        if label in PENDULUM_PARTIES:
            out[(m.group(2) or m.group(1)).strip()] = PENDULUM_PARTIES[label]
    return out
