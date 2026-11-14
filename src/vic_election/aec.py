"""
Downloads official AEC Tally Room results for a federal election, keeping only the requested states
for anything published per state (booth results, booth distributions of preferences, Senate ballots).

Every file linked from the House and Senate CSV download menus is fetched, plus the per-division
Senate first-preferences-by-polling-place files. Files keep their AEC names and are cached: re-runs
read from disk unless refresh=True. A manifest.json records the source URL, size and SHA-256 of each file.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .http_cache import CachedSession

AEC_BASE_URL = "https://results.aec.gov.au"
ALL_STATES = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT")

_HREF = re.compile(r'href="((?:Downloads|External)/[^"]+\.(?:csv|zip))"', re.I)
_STATE_SUFFIX = re.compile(r"-(" + "|".join(ALL_STATES) + r")\.(?:csv|zip)$", re.I)


def read_aec_csv(path: Path) -> Iterator[dict[str, str]]:
    """Rows of an AEC Tally Room CSV, which starts with a title line before the header."""
    with path.open(encoding="utf-8-sig") as f:
        f.readline()
        yield from csv.DictReader(f)


def _subdir(filename: str) -> str:
    name = filename.lower()
    if name.startswith("house"):
        return "house"
    if name.startswith(("senate", "aec-senate")):
        return "senate"
    return "general"


def _wanted(filename: str, states: tuple[str, ...]) -> bool:
    m = _STATE_SUFFIX.search(filename)
    return m is None or m.group(1).upper() in states


def _menu_links(http: CachedSession, event_id: int, menu: str, cache_dir: Path) -> list[str]:
    url = f"{AEC_BASE_URL}/{event_id}/Website/{menu}"
    html = http.text(cache_dir / menu, url)
    return list(dict.fromkeys(_HREF.findall(html)))


def fetch_aec_event(
    event_id: int,
    out_dir: Path,
    states: tuple[str, ...] = ("VIC",),
    max_workers: int = 8,
    refresh: bool = False,
    senate_ballot_states: tuple[str, ...] | None = None,
) -> dict[str, object]:
    """
    Fetch every House/Senate download for `event_id`, filtering state-specific files to `states`.
    The large Senate ballot-level files are only fetched for `senate_ballot_states` (default: all `states`).
    """
    states = tuple(s.upper() for s in states)
    ballot_states = states if senate_ballot_states is None else tuple(s.upper() for s in senate_ballot_states)
    http = CachedSession(refresh)
    menus_dir = out_dir / "_menus"

    links = _menu_links(http, event_id, f"HouseDownloadsMenu-{event_id}-Csv.htm", menus_dir)
    links += _menu_links(http, event_id, f"SenateDownloadsMenu-{event_id}-Csv.htm", menus_dir)
    targets: dict[str, Path] = {}
    for href in links:
        fname = href.rsplit("/", 1)[-1]
        if fname.startswith("aec-senate-formalpreferences") and not _wanted(fname, ballot_states):
            continue
        if _wanted(fname, states):
            targets[f"{AEC_BASE_URL}/{event_id}/Website/{href}"] = out_dir / _subdir(fname) / fname

    # Senate first preferences by polling place are published per division, on a per-state menu
    for state in states:
        menu = f"SenateDivisionDownloadMenu-{event_id}-{state}-Csv.htm"
        for href in _menu_links(http, event_id, menu, menus_dir):
            fname = href.rsplit("/", 1)[-1]
            path = out_dir / "senate" / "first_prefs_by_polling_place" / state / fname
            targets[f"{AEC_BASE_URL}/{event_id}/Website/{href}"] = path

    def download(item: tuple[str, Path]) -> dict[str, object]:
        url, path = item
        content = http.bytes(path, url)
        return {
            "url": url,
            "path": str(path.relative_to(out_dir)),
            "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        files = sorted(pool.map(download, targets.items()), key=lambda f: str(f["path"]))

    _extract_booth_zips(out_dir / "house")

    manifest = {
        "event_id": event_id,
        "states": list(states),
        "source": f"{AEC_BASE_URL}/{event_id}/Website/",
        "retrieved": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "total_bytes": sum(int(f["bytes"]) for f in files),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def _extract_booth_zips(house_dir: Path) -> None:
    """Unzip the (small) booth-level DOP and TCP-flow archives next to the zip; Senate ballot zips stay zipped."""
    for zpath in house_dir.glob("House*ByPPDownload-*.zip"):
        target = house_dir / zpath.stem
        if not target.exists():
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(target)
