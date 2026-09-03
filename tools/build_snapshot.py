"""Rebuild the requirements snapshot that ships with the app.

Run this before cutting a release, not at install time:

    python tools/build_snapshot.py

It walks the whole A-Z index at the usual one-request-per-second rate limit,
so expect a few minutes. Badges that fail or parse to zero requirements are
reported and left out of the snapshot rather than shipped empty; the app falls
back to a live fetch for anything missing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mbworkbook import snapshot as snap  # noqa: E402
from mbworkbook.catalog import load_catalog  # noqa: E402
from mbworkbook.service import fetch_badge  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "-o", "--output", default=str(snap.BUNDLED_PATH),
        help="Where to write the snapshot (default: the bundled path).",
    )
    ap.add_argument(
        "--limit", type=int, default=0,
        help="Only build the first N badges. For a quick smoke test.",
    )
    ap.add_argument(
        "--no-refresh", action="store_true",
        help="Allow the week-old HTTP cache instead of re-fetching every page.",
    )
    args = ap.parse_args(argv)

    print("Loading the A-Z index...")
    entries = load_catalog(force_refresh=not args.no_refresh)
    if args.limit:
        entries = entries[: args.limit]
    print(f"{len(entries)} badges to fetch. This will take about "
          f"{len(entries) // 60 + 1} minutes.")

    def progress(index: int, entry, status: str) -> None:
        mark = {"ok": " ", "empty": "?", "error": "!"}[status]
        print(f"{mark} [{index}/{len(entries)}] {entry.name}", flush=True)

    result, problems = snap.build(
        entries,
        fetch=lambda e: fetch_badge(e, refresh=not args.no_refresh, offline=False),
        on_progress=progress,
    )

    path = snap.save(result, args.output)
    size_kb = path.stat().st_size / 1024
    total = sum(b.total_requirements() for b in result.badges.values())
    print(f"\nWrote {path} ({size_kb:.0f} KB)")
    print(f"{len(result.badges)} badges, {total} requirements, built {result.built}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for line in problems:
            print(f"  - {line}")
        # Missing badges are survivable, so this is a warning, not a failure.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
