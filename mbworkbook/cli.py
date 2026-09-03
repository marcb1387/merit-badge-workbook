"""Command line interface for merit-badge-workbook."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .catalog import load_catalog, resolve
from .fetch import FetchError
from .models import Badge
from .render import WorkbookOptions
from .service import (
    EXTENSIONS,
    catalog_entries,
    fetch_badge,
    output_filename,
    snapshot,
    write_output,
)
from .snapshot import check_for_updates


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mbworkbook",
        description="Generate a requirements checklist or workbook for a "
                    "Scouting America merit badge.",
        epilog="Examples:\n"
               "  mbworkbook --list\n"
               "  mbworkbook Camping\n"
               "  mbworkbook 'personal management' -f pdf --style workbook "
               "--scout 'A. Scout'\n"
               "  mbworkbook --pick -f html\n"
               "  mbworkbook --gui",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("badge", nargs="?", help="Merit badge name or slug (fuzzy matched).")
    p.add_argument("--gui", action="store_true",
                   help="Open the desktop window instead of running on the CLI.")
    p.add_argument("--pick", action="store_true",
                   help="Choose a badge interactively from the A-Z list.")
    p.add_argument("--list", action="store_true",
                   help="Print every badge on the A-Z index and exit.")
    p.add_argument("--eagle-only", action="store_true",
                   help="With --list or --all, restrict to Eagle-required badges.")
    p.add_argument("--all", action="store_true",
                   help="Generate for every badge in the catalog.")

    p.add_argument("-f", "--format", default="md", choices=sorted(EXTENSIONS),
                   help="Output format (default: md).")
    p.add_argument("-o", "--output",
                   help="Output file, or directory when used with --all. "
                        "Defaults to <slug>-checklist.<ext> in the current directory.")
    p.add_argument("--style", default="checklist", choices=["checklist", "workbook"],
                   help="checklist = compact list; workbook = ruled writing space.")
    p.add_argument("--note-lines", type=int, default=4,
                   help="Ruled lines per requirement in workbook style (default: 4).")
    p.add_argument("--no-signoff", action="store_true",
                   help="Omit the date / counselor-initials columns.")
    p.add_argument("--no-resources", action="store_true",
                   help="Drop 'Resources:' lines carried over from the page.")

    p.add_argument("--scout", default="", help="Pre-fill the Scout's name.")
    p.add_argument("--counselor", default="", help="Pre-fill the counselor's name.")
    p.add_argument("--unit", default="", help="Pre-fill the unit, e.g. 'Troop 379'.")

    p.add_argument("--html-file", type=Path,
                   help="Parse a locally saved badge page instead of fetching.")
    p.add_argument("--refresh", action="store_true",
                   help="Ignore the cache and re-fetch from scouting.org.")
    p.add_argument("--dump-html", type=Path,
                   help="Save the fetched page HTML here (useful when parsing fails).")
    p.add_argument("--card-template", type=Path, default=None,
                   help="Fillable blue card PDF to fill (for -f card). Without "
                        "one, a card is drawn from scratch.")
    p.add_argument("--check-updates", action="store_true",
                   help="Re-fetch every badge and report what has changed since "
                        "the built-in requirements were built, then exit.")
    p.add_argument("--online", action="store_true",
                   help="Ignore the built-in requirements and fetch from the site.")
    p.add_argument("--quiet", action="store_true", help="Suppress progress output.")
    return p


def _log(message: str, *, quiet: bool) -> None:
    if not quiet:
        print(message, file=sys.stderr)


def _pick(catalog) -> object:
    for i, entry in enumerate(catalog, 1):
        flag = " *" if entry.eagle_required else ""
        print(f"{i:3}. {entry.name}{flag}")
    print("\n(* = Eagle-required)")
    while True:
        choice = input("\nNumber or name: ").strip()
        if not choice:
            raise SystemExit("Nothing selected.")
        if choice.isdigit() and 1 <= int(choice) <= len(catalog):
            return catalog[int(choice) - 1]
        try:
            return resolve(choice, catalog)
        except LookupError as exc:
            print(exc)


def load_badge(entry, args) -> Badge:
    return fetch_badge(
        entry,
        refresh=args.refresh,
        html_file=args.html_file,
        dump_html=args.dump_html,
    )


def default_path(badge: Badge, args) -> Path:
    name = output_filename(badge, args.style, args.format)
    if args.output:
        out = Path(args.output)
        if args.all or out.is_dir() or str(args.output).endswith(("/", "\\")):
            return out / name
        return out
    return Path(name)


def _check_updates(catalog, *, quiet: bool) -> int:
    """Compare the built-in requirements against the live site."""
    CR = "\r"  # rewrite the progress line in place
    snap = snapshot()
    if not snap:
        print("error: this build has no built-in requirements to compare.",
              file=sys.stderr)
        return 2

    total = len(catalog)
    print(f"Checking {total} badges against scouting.org "
          f"(built-in copy built {snap.built_date}). This takes a few minutes.")

    def progress(index, entry):
        if not quiet:
            print(f"  [{index}/{total}] {entry.name}", end="\r", file=sys.stderr, flush=True)

    report = check_for_updates(
        snap, catalog,
        fetch=lambda e: fetch_badge(e, refresh=True, offline=False),
        on_progress=progress,
    )
    if not quiet:
        print(" " * 60, end="\r", file=sys.stderr)

    print(report.summary())
    for slug in report.changed:
        print(f"  changed: {slug}")
    for slug in report.added:
        print(f"  new on the site: {slug}")
    for slug in report.removed:
        print(f"  no longer listed: {slug}")
    for line in report.failed:
        print(f"  ! {line}", file=sys.stderr)

    if report.any_changes:
        print("\nRe-run with --refresh for those badges, or rebuild the "
              "built-in copy with tools/build_snapshot.py.")
    return 1 if report.any_changes else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.gui:
        from .gui import main as gui_main

        return gui_main()

    options = WorkbookOptions(
        scout=args.scout,
        counselor=args.counselor,
        unit=args.unit,
        style=args.style,
        note_lines=max(0, args.note_lines),
        show_signoff=not args.no_signoff,
        include_notes=not args.no_resources,
        card_template=str(args.card_template) if args.card_template else "",
    )

    # A local file can be parsed without touching the network at all.
    offline_single = args.html_file and not (args.list or args.all or args.pick or args.badge)
    use_snapshot = not (args.online or args.refresh)
    catalog = []
    if not offline_single:
        try:
            catalog = catalog_entries(refresh=args.refresh, offline=use_snapshot)
        except FetchError as exc:
            if not args.html_file:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        if args.eagle_only:
            catalog = [e for e in catalog if e.eagle_required]

    if args.check_updates:
        return _check_updates(catalog, quiet=args.quiet)

    if args.list:
        for entry in catalog:
            flag = " *" if entry.eagle_required else ""
            print(f"{entry.name}{flag}\t{entry.slug}")
        _log(f"\n{len(catalog)} badges. * = Eagle-required.", quiet=args.quiet)
        return 0

    targets = []
    if args.all:
        targets = catalog
    elif args.pick:
        targets = [_pick(catalog)]
    elif args.badge:
        try:
            targets = [resolve(args.badge, catalog)]
        except LookupError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    elif args.html_file:
        targets = [None]
    else:
        build_parser().print_help()
        return 1

    failures = 0
    for entry in targets:
        label = entry.name if entry else str(args.html_file)
        try:
            badge = load_badge(entry, args)
        except FetchError as exc:
            print(f"error: {label}: {exc}", file=sys.stderr)
            failures += 1
            continue

        if not badge.requirements:
            print(
                f"warning: no requirements parsed for {label}. The page layout may "
                f"have changed; re-run with --dump-html page.html to inspect it.",
                file=sys.stderr,
            )
            failures += 1
            continue

        path = default_path(badge, args)
        write_output(badge, options, args.format, path)
        _log(
            f"{badge.name}: {len(badge.requirements)} top-level, "
            f"{badge.total_requirements()} total -> {path}",
            quiet=args.quiet,
        )

    return 1 if failures and failures == len(targets) else 0


if __name__ == "__main__":
    raise SystemExit(main())
