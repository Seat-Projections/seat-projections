"""
VEC results fetchers and parsers: 2022 (vec.vic.gov.au district pages and indicative full-preference
workbooks) and 2018 (static historical-results pages), parsed into DistributionTable datasets.
"""
from __future__ import annotations

import io
import json
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

import openpyxl
import xlrd
from bs4 import BeautifulSoup

from .decomposition import decompose_distribution_to_ballots
from .http_cache import CachedSession
from .irv import compute_majority_threshold
from .models import Candidate, DistributionStep, DistributionTable

VEC_BASE_URL = "https://www.vec.vic.gov.au"
RESULTS_2022_URL = f"{VEC_BASE_URL}/results/state-election-results/2022-state-election-results"
NARRACAN_RESULTS_URL = (
    f"{VEC_BASE_URL}/results/state-election-results/state-by-elections-timeline/"
    "narracan-district-supplementary-election-results"
)
FULL_PREF_DISTRIBUTIONS_URL = (
    f"{VEC_BASE_URL}/results/electoral-statistics/state-election-statistics/"
    "full-preference-distributions"
)
STATEWIDE_2PP_XLSX_URL = f"{VEC_BASE_URL}/-/media/a8466a1794024583a2128ed431ca24f3.xlsx"
STATEWIDE_PRIMARY_XLSX_URL = f"{VEC_BASE_URL}/-/media/c4665365795d431e811d0ce818e373d4.xlsx"


def _clean_text(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "").replace("\xa0", " ")).strip()


def _parse_int(val: object) -> int | None:
    if val is None or (isinstance(val, float) and val != val):  # NaN
        return None
    if isinstance(val, (int, float)):
        return int(round(val))
    m = re.search(r"-?\d+", _clean_text(val).replace(",", ""))
    return int(m.group(0)) if m else None


def _normalize_candidate_name(name: object) -> str:
    # Normalize "SURNAME,  Given" -> "SURNAME, Given"
    return re.sub(r",\s*", ", ", _clean_text(name))


def _match_candidate_name(raw_name: str, known_candidates: list[str]) -> str:
    norm = _normalize_candidate_name(raw_name)
    if norm in known_candidates:
        return norm
    norm_lower = norm.lower()
    for c in known_candidates:
        if c.lower() == norm_lower:
            return c
    # Handle truncated names in VEC row labels (e.g. "UL MURTAZA, Muhammad Nisa")
    for c in known_candidates:
        if c.lower().startswith(norm_lower) or norm_lower.startswith(c.lower()):
            return c
    surname = norm.split(",")[0].strip().lower()
    matches = [c for c in known_candidates if c.split(",")[0].strip().lower() == surname]
    if len(matches) == 1:
        return matches[0]
    raise KeyError(f"Could not match candidate {raw_name!r} among {known_candidates}")


def _extract_excluded_candidate(
    row_label: str,
    continuing: list[str],
    row_values_by_cand: dict[str, int | None],
    prev_totals: dict[str, int],
    transfer_total: int | None,
) -> str:
    # Strategy 1: parse "Transfer of <N> ballot papers of <NAME> (<k>st/nd/rd/th excluded candidate)"
    if m := re.search(r"ballot papers of\s+(.+?)\s*\(\d+(?:st|nd|rd|th)\s+excluded", row_label, re.I):
        try:
            return _match_candidate_name(m.group(1), continuing)
        except KeyError:
            pass

    # Strategy 2: unique continuing candidate whose cell became blank in this transfer row
    blank_continuing = [c for c in continuing if row_values_by_cand.get(c) is None]
    if len(blank_continuing) == 1:
        return blank_continuing[0]

    # Strategy 3: among blank continuing candidates, match previous progressive total == transfer_total
    if transfer_total is not None:
        matching = [c for c in blank_continuing if prev_totals.get(c) == transfer_total]
        if len(matching) == 1:
            return matching[0]

    raise ValueError(f"Unable to identify excluded candidate from row {row_label!r}")


def _extract_grid_matrix(
    grid_rows: list[list[object]],
) -> tuple[list[str], list[tuple[str, list[int | None], int | None]]]:
    # Header row: ['', 'CAND 1', 'CAND 2', ..., 'TOTAL']
    header = grid_rows[0]
    cand_cols: list[int] = []
    cand_headers: list[str] = []
    total_col: int | None = None

    for idx in range(1, len(header)):
        text = _clean_text(header[idx])
        if text.upper() == "TOTAL":
            total_col = idx
        elif text:
            cand_cols.append(idx)
            cand_headers.append(_normalize_candidate_name(text))

    matrix_rows: list[tuple[str, list[int | None], int | None]] = []
    for row in grid_rows[1:]:
        if not row or not (label := _clean_text(row[0])):
            continue
        vals = [_parse_int(row[i]) if i < len(row) else None for i in cand_cols]
        row_tot = _parse_int(row[total_col]) if (total_col is not None and total_col < len(row)) else None
        matrix_rows.append((label, vals, row_tot))

    return cand_headers, matrix_rows


def parse_distribution_matrix_rows(
    district: str,
    source_type: str,
    candidate_headers: list[str],
    matrix_rows: list[tuple[str, list[int | None], int | None]],
    party_by_candidate: dict[str, str] | None = None,
    declared_winner: str | None = None,
    enrolment: int | None = None,
    formal_votes: int | None = None,
    informal_votes: int | None = None,
    majority_threshold: int | None = None,
    source_url: str | None = None,
) -> DistributionTable:
    party_map = party_by_candidate or {}
    norm_headers = [_normalize_candidate_name(h) for h in candidate_headers]

    candidates: list[Candidate] = []
    for idx, cid in enumerate(norm_headers):
        party = party_map.get(cid, "")
        if not party and party_map:
            try:
                party = party_map[_match_candidate_name(cid, list(party_map.keys()))]
            except KeyError:
                party = ""
        candidates.append(Candidate(cid, cid, party, idx + 1))

    first_prefs: dict[str, int] = {}
    steps: list[DistributionStep] = []
    final_totals: dict[str, int] = {}
    continuing = list(norm_headers)
    current_totals: dict[str, int] = {}

    idx = 0
    while idx < len(matrix_rows):
        label, vals, row_total = matrix_rows[idx]
        label_clean = label.lower()

        if "first preference" in label_clean:
            first_prefs = {c: int(v or 0) for c, v in zip(norm_headers, vals)}
            current_totals = dict(first_prefs)
            if formal_votes is None:
                formal_votes = row_total if row_total is not None else sum(first_prefs.values())
        elif label_clean.startswith("transfer of"):
            val_by_cand = dict(zip(norm_headers, vals))
            excl = _extract_excluded_candidate(label, continuing, val_by_cand, current_totals, row_total)
            excl_total = current_totals[excl]
            if row_total is not None and row_total != excl_total:
                raise ValueError(f"{district}: transfer row total {row_total} != {excl} total {excl_total}")
            continuing.remove(excl)
            transfers = {c: int(val_by_cand[c] or 0) for c in continuing}

            # Next row should be Progressive Total or FINAL TOTAL
            prog_totals = {c: current_totals[c] + transfers[c] for c in continuing}
            if idx + 1 < len(matrix_rows) and any(
                k in matrix_rows[idx + 1][0].lower() for k in ("progressive total", "final total")
            ):
                next_by_cand = dict(zip(norm_headers, matrix_rows[idx + 1][1]))
                if parsed_prog := {c: int(next_by_cand[c]) for c in continuing if next_by_cand[c] is not None}:
                    prog_totals = parsed_prog
                idx += 1

            current_totals = dict(prog_totals)
            steps.append(DistributionStep(len(steps) + 1, excl, excl_total, transfers, prog_totals))
        elif "final total" in label_clean:
            val_by_cand = dict(zip(norm_headers, vals))
            final_totals = {c: int(val_by_cand[c]) for c in continuing if val_by_cand.get(c) is not None}

        idx += 1

    final_totals = final_totals or dict(current_totals)
    total_formal = formal_votes if formal_votes is not None else sum(first_prefs.values())
    maj = majority_threshold if majority_threshold is not None else int(compute_majority_threshold(total_formal))

    # Only ever the VEC's own "Elected member"; never inferred from the count, so the winner check stays independent
    winner = declared_winner
    if winner:
        try:
            winner = _match_candidate_name(winner, norm_headers)
        except KeyError:
            pass

    return DistributionTable(
        district=district,
        source_type=source_type,
        formal_votes=total_formal,
        majority_threshold=maj,
        candidates=candidates,
        first_preferences=first_prefs,
        steps=steps,
        final_totals=final_totals,
        declared_winner=winner,
        enrolment=enrolment,
        informal_votes=informal_votes,
        source_url=source_url,
    )


def _is_bold(tag: object) -> bool:
    return getattr(tag, "name", None) in ("b", "strong") or "bold-text" in (getattr(tag, "get", lambda *_: [])("class") or [])


def parse_district_summary_html(html: str, url: str) -> dict[str, object]:
    """Parses a district results page (2022 vec.vic.gov.au layout and 2018 historical-results layout)."""
    soup = BeautifulSoup(html, "html.parser")
    title = next((_clean_text(h.get_text()) for h in soup.find_all(["h1", "h2"]) if "District" in h.get_text()), "")
    district = re.sub(r"\s+District\b.*$", "", title, flags=re.I).strip()
    text = soup.get_text("\n")

    def regex_int(pattern: str) -> int | None:
        m = re.search(pattern, text, flags=re.I)
        return _parse_int(m.group(1)) if m else None

    declared_winner = None
    for heading in soup.find_all(["h2", "h3", "h4"]):
        if "elected member" in _clean_text(heading.get_text()).lower():
            if bold := heading.find_next(_is_bold):
                declared_winner = _normalize_candidate_name(bold.get_text())
            break

    party_by_candidate: dict[str, str] = {}
    first_prefs: dict[str, int] = {}
    tcp: dict[str, int] = {}
    for table in soup.find_all("table"):
        headers = [_clean_text(th.get_text()).lower() for th in table.find_all("th")]
        is_fp = "candidate" in headers and any("1st pref" in h for h in headers)
        is_tcp = "candidate" in headers and any(h == "preferred votes" for h in headers)
        if not (is_fp or is_tcp):
            continue
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if len(tds) >= 3 and (votes := _parse_int(tds[2])) is not None:
                cname = _normalize_candidate_name(tds[0])
                if is_fp:
                    party_by_candidate[cname] = _clean_text(tds[1]) or "Independent"
                    first_prefs[cname] = votes
                else:
                    tcp[cname] = votes

    dist_link = next(
        (
            urljoin(url, a["href"])
            for a in soup.find_all("a", href=True)
            if re.search(r"results-+distribution|(^|/)distribution[\w-]+\.html$", a["href"], re.I)
        ),
        None,
    )

    return {
        "district": district,
        "url": url,
        "enrolment": regex_int(r"Total enrolment\s*as at close of rolls:\s*([\d,]+)"),
        "formal_votes": regex_int(r"\bFormal votes:\s*([\d,]+)"),
        "informal_votes": regex_int(r"\bInformal votes:\s*([\d,]+)"),
        "declared_winner": declared_winner,
        "party_by_candidate": party_by_candidate,
        "first_preferences": first_prefs,
        "two_candidate_preferred": tcp or None,
        "distribution_url": dist_link,
    }


def parse_distribution_html(
    html: str,
    district: str,
    party_by_candidate: dict[str, str],
    source_type: str,
    declared_winner: str | None = None,
    enrolment: int | None = None,
    informal_votes: int | None = None,
    source_url: str | None = None,
) -> DistributionTable:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n")
    maj_m = re.search(r"absolute majority:?\s*([\d,]+)", text, re.I)
    formal_m = re.search(r"\bFormal votes:\s*([\d,]+)", text, re.I)

    target_table = next(
        (t for t in soup.find_all("table") if "total first preference votes" in _clean_text(t.get_text()).lower()),
        None,
    )
    if target_table is None:
        raise ValueError(f"{district}: no distribution of preferences table found ({source_url})")
    grid_rows: list[list[object]] = [
        [_clean_text(c.get_text()) for c in tr.find_all(["th", "td"])] for tr in target_table.find_all("tr")
    ]
    cand_headers, matrix_rows = _extract_grid_matrix(grid_rows)

    return parse_distribution_matrix_rows(
        district=district,
        source_type=source_type,
        candidate_headers=cand_headers,
        matrix_rows=matrix_rows,
        party_by_candidate=party_by_candidate,
        declared_winner=declared_winner,
        enrolment=enrolment,
        formal_votes=_parse_int(formal_m.group(1)) if formal_m else None,
        informal_votes=informal_votes,
        majority_threshold=_parse_int(maj_m.group(1)) if maj_m else None,
        source_url=source_url,
    )


def parse_indicative_excel_bytes(
    content: bytes,
    ext: str,
    party_by_district: dict[str, dict[str, str]],
    enrolment_by_district: dict[str, int | None],
    source_url: str | None = None,
) -> DistributionTable:
    if ext.lower() == ".xls":
        sheet = xlrd.open_workbook(file_contents=content).sheet_by_index(0)
        raw_rows: list[list[object]] = [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]
    else:
        wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
        raw_rows = [list(row) for row in wb[wb.sheetnames[0]].iter_rows(values_only=True)]

    district_name = ""
    formal_votes = majority_threshold = informal_votes = header_row_idx = None

    for idx, row in enumerate(raw_rows):
        first = _clean_text(row[0]) if row else ""
        low = first.lower()
        if "district" in low and not district_name and idx < 8:
            district_name = re.sub(r"\s+District.*$", "", first, flags=re.I).strip()
        elif "total valid first preference votes" in low:
            formal_votes = _parse_int(first.split()[-1])
        elif low.startswith("number of votes required to constitute an absolute majority"):
            majority_threshold = _parse_int(first.split()[-1])
        elif "number of informal votes" in low:
            informal_votes = _parse_int(first.split()[-1])
        elif "candidates names" in low:
            header_row_idx = idx
            break

    if header_row_idx is None:
        raise ValueError(f"Could not find 'Candidates Names' row in workbook ({source_url})")

    cand_headers, matrix_rows = _extract_grid_matrix(raw_rows[header_row_idx:])
    return parse_distribution_matrix_rows(
        district=district_name,
        source_type="indicative_full_2022",
        candidate_headers=cand_headers,
        matrix_rows=matrix_rows,
        party_by_candidate=party_by_district.get(district_name, {}),
        enrolment=enrolment_by_district.get(district_name),
        formal_votes=formal_votes,
        informal_votes=informal_votes,
        majority_threshold=majority_threshold,
        source_url=source_url,
    )


def _official_table(
    summary_html: str, url: str, source_type: str, fetch_distribution: Callable[[str], str]
) -> DistributionTable:
    summary = parse_district_summary_html(summary_html, url)
    district = str(summary["district"])
    party_map: dict[str, str] = summary["party_by_candidate"]  # type: ignore[assignment]
    first_prefs: dict[str, int] = summary["first_preferences"]  # type: ignore[assignment]

    if dist_url := summary["distribution_url"]:
        table = parse_distribution_html(
            fetch_distribution(str(dist_url)),
            district,
            party_map,
            source_type,
            declared_winner=summary["declared_winner"],  # type: ignore[arg-type]
            enrolment=summary["enrolment"],  # type: ignore[arg-type]
            informal_votes=summary["informal_votes"],  # type: ignore[arg-type]
            source_url=str(dist_url),
        )
    else:
        # Won outright on first preference votes (>50% in Round 0)
        formal_total = int(summary["formal_votes"] or sum(first_prefs.values()))
        table = DistributionTable(
            district=district,
            source_type=source_type,
            enrolment=summary["enrolment"],  # type: ignore[arg-type]
            formal_votes=formal_total,
            informal_votes=summary["informal_votes"],  # type: ignore[arg-type]
            majority_threshold=int(compute_majority_threshold(formal_total)),
            candidates=[Candidate(c, c, party_map.get(c, ""), i + 1) for i, c in enumerate(first_prefs)],
            first_preferences=dict(first_prefs),
            steps=[],
            final_totals=dict(first_prefs),
            declared_winner=summary["declared_winner"],  # type: ignore[arg-type]
            source_url=url,
        )
    table.two_candidate_preferred = summary["two_candidate_preferred"]  # type: ignore[assignment]
    return table


def _write_datasets(
    data_dir: Path,
    distributions: dict[str, dict[str, DistributionTable]],
    ballots: dict[str, dict[str, DistributionTable]],
) -> None:
    for sub, datasets, fn in [
        ("distributions", distributions, lambda t: t.to_dict()),
        ("ballots", ballots, lambda t: [b.to_dict() for b in decompose_distribution_to_ballots(t)]),
    ]:
        (data_dir / sub).mkdir(parents=True, exist_ok=True)
        for fname, dataset in datasets.items():
            payload = {d: fn(dataset[d]) for d in sorted(dataset)}
            (data_dir / sub / fname).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def fetch_all_2022_vec_data(data_dir: Path, max_workers: int = 12, refresh: bool = False) -> dict[str, int]:
    raw_html_dir = data_dir / "raw" / "html"
    raw_excel_dir = data_dir / "raw" / "indicative_excel"
    raw_statewide_dir = data_dir / "raw" / "statewide"
    http = CachedSession(refresh)

    # 1. Discover all 87 general election district URLs + Narracan supplementary election
    index_soup = BeautifulSoup(http.text(raw_html_dir / "_index_2022.html", RESULTS_2022_URL), "html.parser")
    district_urls = list(
        dict.fromkeys(
            [
                urljoin(VEC_BASE_URL, a["href"])
                for a in index_soup.find_all("a", href=True)
                if "/results-by-district/" in a["href"] and a["href"].endswith("-district-results")
            ]
            + [NARRACAN_RESULTS_URL]
        )
    )

    # 2. Fetch statewide summary workbooks
    http.bytes(raw_statewide_dir / "2pp_all_districts_2022.xlsx", STATEWIDE_2PP_XLSX_URL)
    http.bytes(raw_statewide_dir / "all_district_primary_results_2022.xlsx", STATEWIDE_PRIMARY_XLSX_URL)

    # 3. Fetch all 88 district summary + official distribution pages in parallel
    def fetch_single_district(url: str) -> DistributionTable:
        slug = url.rstrip("/").split("/")[-1]
        return _official_table(
            http.text(raw_html_dir / f"{slug}.html", url),
            url,
            "official_2022",
            lambda dist_url: http.text(raw_html_dir / f"{slug}-distribution.html", dist_url),
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        official_tables = {t.district: t for t in pool.map(fetch_single_district, district_urls)}

    # 4. Fetch the 39 indicative full-preference distribution Excel workbooks
    full_pref_html = http.text(raw_html_dir / "_full_pref_index_2022.html", FULL_PREF_DISTRIBUTIONS_URL)
    excel_urls = [
        urljoin(VEC_BASE_URL, a["href"])
        for a in BeautifulSoup(full_pref_html, "html.parser").find_all("a", href=True)
        if a["href"].lower().endswith((".xls", ".xlsx")) and "by-election" not in _clean_text(a.get_text()).lower()
    ]
    party_by_district = {d: {c.candidate_id: c.party for c in t.candidates} for d, t in official_tables.items()}
    enrolment_by_district = {d: t.enrolment for d, t in official_tables.items()}

    def fetch_indicative_workbook(url: str) -> DistributionTable:
        media_id = url.rstrip("/").split("/")[-1]
        ext = ".xlsx" if media_id.lower().endswith(".xlsx") else ".xls"
        content = http.bytes(raw_excel_dir / media_id, url)
        table = parse_indicative_excel_bytes(content, ext, party_by_district, enrolment_by_district, url)
        table.declared_winner = official_tables[table.district].declared_winner
        return table

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        indicative_tables = {t.district: t for t in pool.map(fetch_indicative_workbook, excel_urls)}

    # 5. Build combined 88-district full_2cp dataset (49 official full 2CP + 39 indicative full 2CP)
    full_2cp_tables = {d: indicative_tables.get(d, official_tables[d]) for d in sorted(official_tables)}

    # 6. Serialize distributions and decomposed ballot bundles
    _write_datasets(
        data_dir,
        {
            "official_2022.json": official_tables,
            "indicative_39_2022.json": indicative_tables,
            "full_2cp_2022.json": full_2cp_tables,
        },
        {"official_2022_ballots.json": official_tables, "full_2cp_2022_ballots.json": full_2cp_tables},
    )
    return {
        "official_count": len(official_tables),
        "indicative_count": len(indicative_tables),
        "full_2cp_count": len(full_2cp_tables),
    }


STATE2018_BASE_URL = "https://itsitecoreblobvecprd01.blob.core.windows.net/public-files/historical-results/state2018/"


def fetch_all_2018_vec_data(data_dir: Path, max_workers: int = 12, refresh: bool = False) -> dict[str, int]:
    """
    2018 results live as static HTML on the VEC's historical-results blob store. Unlike 2022, the VEC
    published no indicative full distributions for 2018, so seats won on primaries only have a 2CP count.
    """
    raw_html_dir = data_dir / "raw" / "html"
    http = CachedSession(refresh)

    summary_html = http.text(raw_html_dir / "_summary_2018.html", STATE2018_BASE_URL + "summary.html")
    hrefs = re.findall(r'href="([^"]+)"', summary_html)
    pages = sorted({h for h in hrefs if re.fullmatch(r"[a-z-]+district\.html", h)})

    http.bytes(data_dir / "raw" / "statewide" / "2pp_all_districts_2018.xlsx", STATE2018_BASE_URL + "files/2ppvote2018-final.xlsx")

    def fetch_single_district(page: str) -> DistributionTable:
        slug = page.removesuffix(".html")
        http.bytes(data_dir / "raw" / "primary_by_voting_centre" / f"{slug}.xlsx", STATE2018_BASE_URL + f"files/{slug}.xlsx")
        return _official_table(
            http.text(raw_html_dir / page, STATE2018_BASE_URL + page),
            STATE2018_BASE_URL + page,
            "official_2018",
            lambda dist_url: http.text(raw_html_dir / dist_url.rsplit("/", 1)[-1], dist_url),
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        official_tables = {t.district: t for t in pool.map(fetch_single_district, pages)}

    _write_datasets(
        data_dir,
        {"official_2018.json": official_tables},
        {"official_2018_ballots.json": official_tables},
    )
    return {
        "official_count": len(official_tables),
        "with_distribution": sum(1 for t in official_tables.values() if t.steps),
        "won_on_primaries": sum(1 for t in official_tables.values() if not t.steps),
    }

