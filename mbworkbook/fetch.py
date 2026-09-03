"""HTTP access to scouting.org, with an on-disk cache so we scrape politely."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import requests

from .paths import cache_dir as _cache_dir

USER_AGENT = (
    "merit-badge-workbook/1.0 (+troop volunteer tool; "
    "contact: set MBW_CONTACT env var)"
)

# Be gentle: scouting.org is a volunteer-facing site, not an API.
MIN_INTERVAL_SECONDS = 1.0
_last_request_at = 0.0


class FetchError(RuntimeError):
    pass


def _cache_path(url: str, cache_dir: Path) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    return cache_dir / f"{digest}.html"


def get_html(
    url: str,
    *,
    cache_dir: Path | None = None,
    max_age_seconds: int = 7 * 24 * 3600,
    force_refresh: bool = False,
    timeout: int = 30,
) -> str:
    """Return page HTML, using the cache when it is fresh enough."""
    cache_dir = Path(cache_dir) if cache_dir else _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(url, cache_dir)

    if path.exists() and not force_refresh:
        age = time.time() - path.stat().st_mtime
        if age <= max_age_seconds:
            return path.read_text(encoding="utf-8")

    global _last_request_at
    delta = time.time() - _last_request_at
    if delta < MIN_INTERVAL_SECONDS:
        time.sleep(MIN_INTERVAL_SECONDS - delta)

    contact = os.environ.get("MBW_CONTACT")
    headers = {"User-Agent": USER_AGENT if not contact else USER_AGENT.replace(
        "set MBW_CONTACT env var", contact)}

    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        _last_request_at = time.time()
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Fall back to a stale cache entry rather than failing outright.
        if path.exists():
            return path.read_text(encoding="utf-8")
        raise FetchError(f"Could not fetch {url}: {exc}") from exc

    html = resp.text
    path.write_text(html, encoding="utf-8")
    return html
