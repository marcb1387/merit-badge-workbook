"""Fill an official fillable blue card PDF with a badge's details.

Councils publish a fillable version of Scouting America's "Application for
Merit Badge" (the blue card) as an AcroForm PDF. If you point this at one, you
get the real form — the layout your advancement chair already knows — with the
Scout, unit, counselor and the badge's requirement numbers typed in.

The template is *not* shipped with this app. It is Scouting America's form, and
redistributing it is theirs to allow, not ours; councils also revise it. So you
download it yourself and point the app at your copy. Without a template the app
falls back to :mod:`mbworkbook.render.card`, which draws its own card.

A council sheet holds three cards, and the form reflects that: the Scout's name
and unit are single fields shared by all three, while the badge, counselor,
dates and requirement grid repeat with the suffixes "", "1" and "2". So one
sheet covers three badges for one Scout, and we emit another sheet per three.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

from ..models import Badge
from . import WorkbookOptions

# The three card positions on one sheet, in the order they are printed.
PANEL_SUFFIXES = ("1", "2", "")
CARDS_PER_SHEET = len(PANEL_SUFFIXES)

# Rows in each card's requirement grid.
GRID_ROWS = 22

class TemplateError(RuntimeError):
    """The file given is not a blue card template we recognise."""


def _require_pypdf():
    try:
        from pypdf import PdfReader, PdfWriter  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Filling a blue card template needs pypdf. Install it with:\n"
            "    pip install pypdf"
        ) from exc


def _unit_number(unit: str) -> str:
    """"Troop 379" -> "379". The form has a separate type selector."""
    digits = "".join(ch for ch in unit if ch.isdigit())
    return digits or unit


def looks_like_template(path: Path | str) -> bool:
    """True if ``path`` is an AcroForm PDF with the blue card's fields."""
    try:
        _require_pypdf()
        from pypdf import PdfReader

        fields = PdfReader(str(path)).get_fields() or {}
    except Exception:  # noqa: BLE001 - any unreadable file is simply not one
        return False
    return "MeritBadge" in fields and "Requirement.01" in fields


def _card_values(badge: Badge, options: WorkbookOptions, suffix: str) -> dict[str, str]:
    """Every field for one card position, fully qualified."""
    values = {
        f"MeritBadge{suffix}": badge.name,
        f"Counselor{suffix}": options.counselor,
        f"DateApplied{suffix}": date.today().strftime("%m/%d/%Y"),
    }

    markers = [req.marker for req in badge.requirements][:GRID_ROWS]
    for row, marker in enumerate(markers, 1):
        values[f"Requirement{suffix}.{row:02d}"] = marker

    remarks = f"Requirements retrieved {badge.source_retrieved[:10]}" \
        if badge.source_retrieved else ""
    if badge.eagle_required:
        remarks = ("Eagle-required. " + remarks).strip()
    if remarks:
        values[f"Remarks{suffix}"] = remarks
    return values


def fill_template(
    template: Path | str,
    badges,
    options: WorkbookOptions,
    path: str,
) -> int:
    """Fill ``template`` with ``badges`` and write to ``path``.

    Returns the number of sheets written. Raises :class:`TemplateError` if the
    file does not carry the fields we expect, so the caller can fall back or
    tell the user rather than emitting a silently blank form.
    """
    _require_pypdf()
    from pypdf import PdfReader, PdfWriter

    badges = list(badges)
    if not badges:
        raise ValueError("fill_template needs at least one badge")

    template = Path(template)
    if not looks_like_template(template):
        raise TemplateError(
            f"{template.name} does not look like a fillable blue card. Expected "
            f"an AcroForm PDF with 'MeritBadge' and 'Requirement.01' fields."
        )

    shared = {
        "Name1": options.scout,
        "UnitNumber": _unit_number(options.unit),
    }
    shared = {k: v for k, v in shared.items() if v}

    writer = PdfWriter()
    sheets = 0

    for index, start in enumerate(range(0, len(badges), CARDS_PER_SHEET)):
        chunk = badges[start:start + CARDS_PER_SHEET]

        values = dict(shared)
        for suffix, badge in zip(PANEL_SUFFIXES, chunk):
            values.update(_card_values(badge, options, suffix))

        sheet = PdfWriter(clone_from=PdfReader(str(template)))
        for page in sheet.pages:
            # Every page carries widgets for the same fields; pypdf ignores
            # names that are not present on the page it is given.
            sheet.update_page_form_field_values(page, values, auto_regenerate=False)

        if index:
            _suffix_field_names(sheet, index)
        buf = io.BytesIO()
        sheet.write(buf)
        buf.seek(0)
        writer.append(buf)
        sheets += 1

    # Without this, some viewers (notably Acrobat) show the fields blank until
    # they are clicked, because we did not regenerate appearance streams.
    writer.set_need_appearances_writer(True)

    with open(path, "wb") as fh:
        writer.write(fh)
    return sheets


def _suffix_field_names(sheet, index: int) -> None:
    """Make one sheet's field names unique before it is merged.

    Appending PDFs merges AcroForms by field name, so a second sheet with the
    same names would overwrite the first sheet's values instead of sitting
    beside them. Renaming the root fields keeps each sheet's answers its own;
    the widgets follow their parent, so nothing moves on the page.
    """
    from pypdf.generic import NameObject, TextStringObject

    acro = sheet._root_object.get("/AcroForm")
    if acro is None:
        return
    for ref in acro.get("/Fields", []):
        field = ref.get_object()
        if "/T" in field:
            field[NameObject("/T")] = TextStringObject(f"{field['/T']}~{index}")
