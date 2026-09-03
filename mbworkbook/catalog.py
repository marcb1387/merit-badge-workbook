"""Scrape the A-Z merit badge index and resolve user-typed badge names."""

from __future__ import annotations

import difflib
import re

from bs4 import BeautifulSoup

from .fetch import get_html
from .models import CatalogEntry

INDEX_URL = "https://www.scouting.org/skills/merit-badges/all/"
BADGE_URL = "https://www.scouting.org/merit-badges/{slug}/"

BADGE_HREF = re.compile(r"^https?://(?:www\.)?scouting\.org/merit-badges/([a-z0-9\-]+)/?$")

# Anchor labels on the index that are decoration, not badge names.
SKIP_LABELS = {"drg", "eagle required", "", "merit badge", "view now"}


def load_catalog(*, force_refresh: bool = False) -> list[CatalogEntry]:
    """Return every merit badge listed on the A-Z page."""
    html = get_html(INDEX_URL, force_refresh=force_refresh)
    return parse_catalog(html)


def parse_catalog(html: str) -> list[CatalogEntry]:
    soup = BeautifulSoup(html, "lxml")

    eagle_slugs: set[str] = set()
    names: dict[str, str] = {}
    order: list[str] = []

    for anchor in soup.find_all("a", href=True):
        match = BADGE_HREF.match(anchor["href"].strip())
        if not match:
            continue
        slug = match.group(1)
        label = " ".join(anchor.get_text(" ", strip=True).split())
        lowered = label.lower()

        if "eagle required" in lowered:
            eagle_slugs.add(slug)
            continue
        if lowered in SKIP_LABELS:
            continue
        # Index entries in the "requirement updates" lists carry trailing
        # change markers like "Athletics (2) (3)" - strip them.
        label = re.sub(r"\s*\((?:new|\d+|numbered|numbers changed|formally[^)]*)\)", "", label, flags=re.I).strip()
        if not label:
            continue
        if slug not in names:
            names[slug] = label
            order.append(slug)

    return [
        CatalogEntry(
            name=names[slug],
            slug=slug,
            url=BADGE_URL.format(slug=slug),
            eagle_required=slug in eagle_slugs,
        )
        for slug in sorted(order, key=lambda s: names[s].lower())
    ]


def _normalize(value: str) -> str:
    value = value.lower().replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def resolve(query: str, catalog: list[CatalogEntry]) -> CatalogEntry:
    """Find the badge a user meant. Raises LookupError with suggestions."""
    target = _normalize(query)
    by_name = {_normalize(e.name): e for e in catalog}
    by_slug = {_normalize(e.slug): e for e in catalog}

    if target in by_name:
        return by_name[target]
    if target in by_slug:
        return by_slug[target]

    starts = [e for e in catalog if _normalize(e.name).startswith(target)]
    if len(starts) == 1:
        return starts[0]

    contains = [e for e in catalog if target in _normalize(e.name)]
    if len(contains) == 1:
        return contains[0]

    pool = starts or contains
    if pool:
        raise LookupError(
            f"{query!r} matches several badges: "
            + ", ".join(sorted(e.name for e in pool))
        )

    close = difflib.get_close_matches(target, list(by_name), n=5, cutoff=0.6)
    hint = ""
    if close:
        hint = " Did you mean: " + ", ".join(by_name[c].name for c in close) + "?"
    raise LookupError(f"No merit badge matched {query!r}.{hint}")
