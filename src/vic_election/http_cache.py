"""HTTP downloads cached to disk, shared by every fetcher (VEC, AEC, boundaries)."""
from __future__ import annotations

import time
from pathlib import Path

import requests

USER_AGENT = "seatprojections/0.1 (+https://seatprojections.au)"
TIMEOUT_SECONDS = 60
# The VEC's web application firewall occasionally answers a burst of parallel requests with an HTTP 200
# "Access Denied" page. Such a response must not be cached; wait and retry instead.
BLOCKED_MARKERS = (b"Access Denied", b"blocked by our security system")
BLOCKED_PAGE_MAX_BYTES = 2000
MAX_ATTEMPTS = 5
RETRY_BACKOFF_SECONDS = 2.0  # doubled after each blocked attempt


class BlockedResponseError(RuntimeError):
    """The server kept answering with its anti-bot page after MAX_ATTEMPTS tries."""


def _looks_blocked(content: bytes) -> bool:
    return len(content) <= BLOCKED_PAGE_MAX_BYTES and any(marker in content for marker in BLOCKED_MARKERS)
# Electoral-commission sites serve UTF-8; cp1252 is the fallback for the occasional legacy page.
TEXT_ENCODINGS = ("utf-8", "cp1252")


class CachedSession:
    """HTTP GETs cached to disk: each file is downloaded once and re-read locally unless refresh=True."""

    def __init__(self, refresh: bool = False) -> None:
        self.refresh = refresh
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def bytes(self, path: Path, url: str) -> bytes:
        if path.exists() and not self.refresh:
            return path.read_bytes()
        content = self._get(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return content

    def _get(self, url: str) -> bytes:
        delay = RETRY_BACKOFF_SECONDS
        for attempt in range(1, MAX_ATTEMPTS + 1):
            r = self.session.get(url, timeout=TIMEOUT_SECONDS)
            r.raise_for_status()
            if not _looks_blocked(r.content):
                return r.content
            if attempt < MAX_ATTEMPTS:
                time.sleep(delay)
                delay *= 2
        raise BlockedResponseError(f"{url}: blocked by the server's security system after {MAX_ATTEMPTS} attempts")

    def text(self, path: Path, url: str) -> str:
        raw = self.bytes(path, url)
        for encoding in TEXT_ENCODINGS[:-1]:
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode(TEXT_ENCODINGS[-1])
