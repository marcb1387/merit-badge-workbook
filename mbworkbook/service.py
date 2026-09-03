"""Operations shared by the CLI and the GUI.

Keeping fetch/parse/render here means the two front ends cannot drift apart.
"""

from __future__ import annotations

from pathlib import Path

from .fetch import get_html
from .models import Badge, CatalogEntry
from .parser import parse_badge_page
from .render import WorkbookOptions, render_json, render_markdown
from .render.html import render_html
from .snapshot import Snapshot, load as load_snapshot

EXTENSIONS = {"md": ".md", "html": ".html", "pdf": ".pdf", "json": ".json",
              "card": ".pdf"}

FORMAT_LABELS = {
    "md": "Markdown (.md)",
    "html": "Printable HTML (.html)",
    "pdf": "PDF (.pdf)",
    "json": "JSON data (.json)",
    "card": "Blue card — application for merit badge (.pdf)",
}


_SNAPSHOT: Snapshot | None = None


def snapshot() -> Snapshot:
    """The shipped requirements snapshot, loaded once."""
    global _SNAPSHOT
    if _SNAPSHOT is None:
        _SNAPSHOT = load_snapshot()
    return _SNAPSHOT


def catalog_entries(*, refresh: bool = False, offline: bool = True) -> list[CatalogEntry]:
    """The badge list, from the snapshot when we have one.

    Falling back to the live index keeps the app working if the snapshot is
    missing, which is the state during development and after a failed build.
    """
    if not refresh and offline:
        entries = snapshot().catalog()
        if entries:
            return entries
    from .catalog import load_catalog

    return load_catalog(force_refresh=refresh)


def fetch_badge(
    entry: CatalogEntry | None,
    *,
    refresh: bool = False,
    offline: bool = True,
    html_file: Path | str | None = None,
    dump_html: Path | str | None = None,
) -> Badge:
    """Load and parse one badge.

    Order of preference: an explicitly saved page, then the shipped snapshot,
    then the network. ``refresh`` skips the snapshot and the HTTP cache both,
    which is what the update check and ``--refresh`` want.
    """
    if html_file:
        path = Path(html_file)
        html = path.read_text(encoding="utf-8", errors="replace")
        return parse_badge_page(
            html,
            slug=entry.slug if entry else path.stem,
            url=entry.url if entry else str(path),
            eagle_required=bool(entry and entry.eagle_required),
            name=entry.name if entry else None,
        )

    if entry is None:
        raise ValueError("fetch_badge needs either a catalog entry or an html_file")

    if offline and not refresh and not dump_html:
        stored = snapshot().badge(entry.slug)
        if stored is not None:
            return stored

    html = get_html(entry.url, force_refresh=refresh)
    if dump_html:
        Path(dump_html).write_text(html, encoding="utf-8")
    return parse_badge_page(
        html,
        slug=entry.slug,
        url=entry.url,
        eagle_required=entry.eagle_required,
        name=entry.name,
    )


def output_filename(badge: Badge, style: str, fmt: str) -> str:
    if fmt == "card":
        return f"{badge.slug}-blue-card{EXTENSIONS[fmt]}"
    suffix = "workbook" if style == "workbook" else "checklist"
    return f"{badge.slug}-{suffix}{EXTENSIONS[fmt]}"


def write_output(badge: Badge, options: WorkbookOptions, fmt: str, path: Path) -> Path:
    """Render ``badge`` to ``path`` and return the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "pdf":
        from .render.pdf import render_pdf

        render_pdf(badge, options, str(path))
        return path

    if fmt == "card":
        write_cards([badge], options, path)
        return path

    renderer = {"md": render_markdown, "html": render_html, "json": render_json}[fmt]
    path.write_text(renderer(badge, options), encoding="utf-8")
    return path


def write_cards(badges, options: WorkbookOptions, path: Path) -> Path:
    """Write blue cards for ``badges`` to one PDF.

    Uses the official fillable template when the user has pointed us at one,
    and falls back to our own drawn card otherwise. A template that turns out
    not to be a blue card raises, rather than quietly emitting a blank form.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if options.card_template:
        from .render.cardform import fill_template

        fill_template(options.card_template, badges, options, str(path))
        return path

    from .render.card import render_cards

    render_cards(badges, options, str(path))
    return path
