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

EXTENSIONS = {"md": ".md", "html": ".html", "pdf": ".pdf", "json": ".json"}

FORMAT_LABELS = {
    "md": "Markdown (.md)",
    "html": "Printable HTML (.html)",
    "pdf": "PDF (.pdf)",
    "json": "JSON data (.json)",
}


def fetch_badge(
    entry: CatalogEntry | None,
    *,
    refresh: bool = False,
    html_file: Path | str | None = None,
    dump_html: Path | str | None = None,
) -> Badge:
    """Load and parse one badge, from the web or from a saved page."""
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

    renderer = {"md": render_markdown, "html": render_html, "json": render_json}[fmt]
    path.write_text(renderer(badge, options), encoding="utf-8")
    return path
