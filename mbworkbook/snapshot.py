"""A snapshot of every badge's requirements, built once and shipped with the app.

Fetching 140-odd pages at the one-request-per-second rate limit takes minutes,
which is a poor first run for someone who just wants to print one checklist. So
we build the whole catalogue ahead of time and ship the result; the app reads
that by default and only touches the network when asked to.

The obvious hazard is staleness: requirements change, and a shipped file cannot.
Every snapshot therefore records when it was built, every sheet already prints
its retrieval date, and :func:`check_for_updates` re-fetches and reports what
has moved since. Each badge carries a fingerprint of its requirement text so
that comparison is an equality check rather than a diff.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from .models import Badge, CatalogEntry

FORMAT_VERSION = 1

# Shipped inside the package so it survives PyInstaller and a wheel install.
BUNDLED_PATH = Path(__file__).parent / "data" / "requirements.json"


def fingerprint(badge: Badge) -> str:
    """A stable hash of the requirement tree, ignoring cosmetic differences.

    Only marker and text go in. Retrieval dates and note ordering change
    between fetches without the requirements themselves having changed, and we
    do not want to report those as updates.
    """
    parts: list[str] = []
    for req in badge.requirements:
        for path, node in req.walk():
            parts.append(".".join(path) + "\x1f" + " ".join(node.text.split()))
    blob = "\x1e".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class Snapshot:
    """Parsed badges plus the catalogue, as of ``built``."""

    built: str = ""
    badges: dict[str, Badge] = field(default_factory=dict)
    entries: list[CatalogEntry] = field(default_factory=list)
    fingerprints: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.badges)

    def badge(self, slug: str) -> Badge | None:
        return self.badges.get(slug)

    def catalog(self) -> list[CatalogEntry]:
        return list(self.entries)

    @property
    def built_date(self) -> str:
        """Just the date part, for display. Empty if unknown."""
        return self.built[:10]

    def to_dict(self) -> dict:
        return {
            "format": FORMAT_VERSION,
            "built": self.built,
            "entries": [
                {
                    "name": e.name,
                    "slug": e.slug,
                    "url": e.url,
                    "eagle_required": e.eagle_required,
                }
                for e in self.entries
            ],
            "badges": {slug: b.to_dict() for slug, b in self.badges.items()},
            "fingerprints": self.fingerprints,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Snapshot":
        if data.get("format") != FORMAT_VERSION:
            raise ValueError(
                f"snapshot format {data.get('format')!r} is not supported "
                f"by this version (expected {FORMAT_VERSION})"
            )
        return cls(
            built=data.get("built", ""),
            badges={
                slug: Badge.from_dict(raw) for slug, raw in data.get("badges", {}).items()
            },
            entries=[CatalogEntry(**e) for e in data.get("entries", [])],
            fingerprints=dict(data.get("fingerprints", {})),
        )


def load(path: Path | str | None = None) -> Snapshot:
    """Load the shipped snapshot, or an empty one if it is missing or unreadable.

    A broken snapshot must not stop the app: everything it provides can also be
    fetched live, so we degrade to that rather than refusing to start.
    """
    target = Path(path) if path else BUNDLED_PATH
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return Snapshot.from_dict(data)
    except (OSError, ValueError, KeyError, TypeError):
        return Snapshot()


def save(snapshot: Snapshot, path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot.to_dict(), indent=1, sort_keys=True), encoding="utf-8"
    )
    return path


# --------------------------------------------------------------------------
# Building and refreshing
# --------------------------------------------------------------------------


def build(
    entries: Iterable[CatalogEntry],
    *,
    fetch: Callable[[CatalogEntry], Badge],
    on_progress: Callable[[int, CatalogEntry, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[Snapshot, list[str]]:
    """Fetch every entry and assemble a snapshot.

    ``fetch`` is injected so this stays testable and so the caller controls
    refresh and caching. Returns the snapshot plus a list of human-readable
    problems, since one unparseable badge should not sink the whole build.
    """
    entries = list(entries)
    snapshot = Snapshot(
        built=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        entries=entries,
    )
    problems: list[str] = []

    for index, entry in enumerate(entries, 1):
        if should_cancel and should_cancel():
            problems.append(f"cancelled after {index - 1} of {len(entries)}")
            break
        try:
            badge = fetch(entry)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            problems.append(f"{entry.name}: {type(exc).__name__}: {exc}")
            if on_progress:
                on_progress(index, entry, "error")
            continue

        if not badge.requirements:
            problems.append(f"{entry.name}: parsed to zero requirements")
            if on_progress:
                on_progress(index, entry, "empty")
            continue

        snapshot.badges[entry.slug] = badge
        snapshot.fingerprints[entry.slug] = fingerprint(badge)
        if on_progress:
            on_progress(index, entry, "ok")

    return snapshot, problems


@dataclass
class UpdateReport:
    """What changed between the shipped snapshot and the live site."""

    changed: list[str] = field(default_factory=list)  # slug, requirements differ
    added: list[str] = field(default_factory=list)  # on the site, not shipped
    removed: list[str] = field(default_factory=list)  # shipped, gone from the site
    unchanged: int = 0
    failed: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def any_changes(self) -> bool:
        return bool(self.changed or self.added or self.removed)

    def summary(self) -> str:
        if self.cancelled:
            return "Update check cancelled."
        if not self.any_changes:
            return f"No changes. {self.unchanged} badges match the shipped copy."
        bits = []
        if self.changed:
            bits.append(f"{len(self.changed)} changed")
        if self.added:
            bits.append(f"{len(self.added)} new")
        if self.removed:
            bits.append(f"{len(self.removed)} removed")
        return ", ".join(bits) + f"; {self.unchanged} unchanged."


def check_for_updates(
    snapshot: Snapshot,
    entries: Iterable[CatalogEntry],
    *,
    fetch: Callable[[CatalogEntry], Badge],
    on_progress: Callable[[int, CatalogEntry], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> UpdateReport:
    """Re-fetch every badge and compare fingerprints against ``snapshot``.

    ``entries`` is the live catalogue, so badges added to or dropped from the
    A-Z index are reported too, not just edits to existing requirements.
    """
    entries = list(entries)
    report = UpdateReport()
    live_slugs: set[str] = set()

    for index, entry in enumerate(entries, 1):
        if should_cancel and should_cancel():
            report.cancelled = True
            return report
        live_slugs.add(entry.slug)

        if entry.slug not in snapshot.fingerprints:
            report.added.append(entry.slug)
            if on_progress:
                on_progress(index, entry)
            continue

        try:
            badge = fetch(entry)
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            report.failed.append(f"{entry.name}: {type(exc).__name__}: {exc}")
            if on_progress:
                on_progress(index, entry)
            continue

        if not badge.requirements:
            report.failed.append(f"{entry.name}: parsed to zero requirements")
        elif fingerprint(badge) != snapshot.fingerprints[entry.slug]:
            report.changed.append(entry.slug)
        else:
            report.unchanged += 1

        if on_progress:
            on_progress(index, entry)

    report.removed = sorted(set(snapshot.fingerprints) - live_slugs)
    return report
