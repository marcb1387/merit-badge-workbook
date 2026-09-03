"""Printable merit badge application cards - the "blue card" - via ReportLab.

The card is the three-part advancement record a Scout carries through a badge:
the applicant keeps one panel, the counselor keeps one, and the unit keeps one,
separated along the perforations once the badge is signed off.

This is a unit-printable version, not a reproduction of the council-issued
form. It carries the same three panels and the same fields so it can be used
the same way, and it is marked unofficial on every panel: some councils accept
printed cards and some insist on the pre-printed stock from the Scout shop, and
a Scout should not find that out at a board of review. Print on blue cardstock
if you have it - the colour is what makes it recognisable at a glance.
"""

from __future__ import annotations

from datetime import date

from ..models import Badge
from . import WorkbookOptions

# Three panels across, sized so a full card fits letter portrait with room for
# two cards per sheet. Points throughout; 72pt to the inch.
PANEL_W = 2.55 * 72
PANEL_H = 3.9 * 72
CARD_W = PANEL_W * 3
CARDS_PER_PAGE = 2

PANELS = ("APPLICANT'S RECORD", "COUNSELOR'S RECORD", "UNIT LEADER'S RECORD")

PANEL_NOTE = {
    "APPLICANT'S RECORD": "Scout keeps this portion",
    "COUNSELOR'S RECORD": "Counselor keeps this portion",
    "UNIT LEADER'S RECORD": "Unit keeps this portion for advancement records",
}


def _require_reportlab():
    try:
        from reportlab.pdfgen import canvas  # noqa: F401
        from reportlab.lib.pagesizes import letter  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "Blue card output needs reportlab. Install it with:\n"
            "    pip install reportlab"
        ) from exc


def _fit(text: str, width: float, font: str, size: float) -> str:
    """Truncate ``text`` with an ellipsis so it fits ``width``."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def render_cards(badges, options: WorkbookOptions, path: str) -> None:
    """Write one three-part card per badge to ``path``, two cards per page."""
    _require_reportlab()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    badges = list(badges)
    if not badges:
        raise ValueError("render_cards needs at least one badge")

    page_w, page_h = letter
    ink = colors.HexColor("#12263a")
    muted = colors.HexColor("#5b6b7c")
    rule = colors.HexColor("#93a7ba")
    cut = colors.HexColor("#b8c6d4")

    left = (page_w - CARD_W) / 2
    top_margin = 0.6 * 72
    gap = 0.45 * 72

    pdf = canvas.Canvas(path, pagesize=letter)
    pdf.setTitle("Merit badge application cards")

    def field(x: float, y: float, label: str, value: str, width: float) -> float:
        """Draw a labelled fill-in line, returning the next baseline."""
        pdf.setFont("Helvetica", 5.2)
        pdf.setFillColor(muted)
        pdf.drawString(x, y, label.upper())
        pdf.setStrokeColor(rule)
        pdf.setLineWidth(0.4)
        pdf.line(x, y - 10.5, x + width, y - 10.5)
        if value:
            pdf.setFont("Helvetica-Bold", 8)
            pdf.setFillColor(ink)
            pdf.drawString(x + 1.5, y - 8.5, _fit(value, width - 3, "Helvetica-Bold", 8))
        return y - 22

    def draw_panel(x: float, y_top: float, title: str, badge: Badge) -> None:
        pad = 9
        inner = PANEL_W - pad * 2
        x0 = x + pad

        pdf.setStrokeColor(cut)
        pdf.setLineWidth(0.5)
        pdf.rect(x, y_top - PANEL_H, PANEL_W, PANEL_H, stroke=1, fill=0)

        y = y_top - 16
        pdf.setFont("Helvetica-Bold", 6.4)
        pdf.setFillColor(ink)
        pdf.drawString(x0, y, title)
        y -= 8
        pdf.setFont("Helvetica", 5)
        pdf.setFillColor(muted)
        pdf.drawString(x0, y, "APPLICATION FOR MERIT BADGE")

        y -= 6
        pdf.setStrokeColor(rule)
        pdf.setLineWidth(0.8)
        pdf.line(x0, y, x0 + inner, y)
        y -= 14

        name = badge.name + (" ★" if badge.eagle_required else "")
        pdf.setFont("Helvetica-Bold", 10.5)
        pdf.setFillColor(ink)
        pdf.drawString(x0, y, _fit(name, inner, "Helvetica-Bold", 10.5))
        if badge.eagle_required:
            y -= 8
            pdf.setFont("Helvetica-Bold", 5)
            pdf.setFillColor(colors.HexColor("#8a1c1c"))
            pdf.drawString(x0, y, "EAGLE-REQUIRED")
        y -= 16

        y = field(x0, y, "Scout", options.scout, inner)
        y = field(x0, y, "Unit", options.unit, inner)
        y = field(x0, y, "Council / District", "", inner)

        half = (inner - 8) / 2
        pdf.setFont("Helvetica", 5.2)
        pdf.setFillColor(muted)
        pdf.drawString(x0, y, "DATE STARTED")
        pdf.drawString(x0 + half + 8, y, "DATE COMPLETED")
        pdf.setStrokeColor(rule)
        pdf.setLineWidth(0.4)
        pdf.line(x0, y - 10.5, x0 + half, y - 10.5)
        pdf.line(x0 + half + 8, y - 10.5, x0 + inner, y - 10.5)
        y -= 22

        y = field(x0, y, "Counselor", options.counselor, inner)
        y = field(x0, y, "Counselor signature", "", inner)
        field(x0, y, "Unit leader signature", "", inner)

        pdf.setFont("Helvetica-Oblique", 4.6)
        pdf.setFillColor(muted)
        pdf.drawString(x0, y_top - PANEL_H + 15, PANEL_NOTE[title])
        pdf.drawString(x0, y_top - PANEL_H + 8, "Unofficial — not the council-issued card")

    def draw_card(badge: Badge, y_top: float) -> None:
        for index, title in enumerate(PANELS):
            draw_panel(left + index * PANEL_W, y_top, title, badge)
        # Dashed guides on the perforation lines, so the panels cut apart square.
        pdf.setStrokeColor(cut)
        pdf.setLineWidth(0.5)
        pdf.setDash(2, 3)
        for index in (1, 2):
            x = left + index * PANEL_W
            pdf.line(x, y_top - PANEL_H, x, y_top)
        pdf.setDash()

        pdf.setFont("Helvetica", 5)
        pdf.setFillColor(muted)
        stamp = f"{badge.name} · generated {date.today().isoformat()}"
        if badge.source_retrieved:
            stamp += f" · requirements retrieved {badge.source_retrieved[:10]}"
        pdf.drawString(left, y_top + 5, stamp)

    for index, badge in enumerate(badges):
        slot = index % CARDS_PER_PAGE
        if slot == 0 and index:
            pdf.showPage()
        draw_card(badge, page_h - top_margin - slot * (PANEL_H + gap))

    pdf.save()


def render_card(badge: Badge, options: WorkbookOptions, path: str) -> None:
    """Single-badge entry point, for the shared ``write_output`` path."""
    render_cards([badge], options, path)
