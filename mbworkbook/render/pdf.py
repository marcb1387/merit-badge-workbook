"""PDF checklist / workbook via ReportLab.

ReportLab is an optional dependency; import errors are surfaced with a hint
rather than a traceback.
"""

from __future__ import annotations

from datetime import date

from ..models import Badge, Requirement
from . import DISCLAIMER, WorkbookOptions, visible_notes

INDENT_PT = 18
BOX_COL_PT = 15  # width of the checkbox column
CONTENT_WIDTH_PT = 504  # letter width less 0.75in margins on each side


def _require_reportlab():
    try:
        from reportlab.lib import colors  # noqa: F401
        from reportlab.lib.pagesizes import letter  # noqa: F401
    except ImportError as exc:  # pragma: no cover
        raise SystemExit(
            "PDF output needs reportlab. Install it with:\n"
            "    pip install reportlab"
        ) from exc


def render_pdf(badge: Badge, options: WorkbookOptions, path: str) -> None:
    _require_reportlab()
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.graphics.shapes import Drawing, Rect
    from reportlab.platypus import (
        HRFlowable,
        KeepTogether,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )
    from xml.sax.saxutils import escape

    ink = colors.HexColor("#16202b")
    muted = colors.HexColor("#5b6b7c")
    rule = colors.HexColor("#c8d2dc")
    accent = colors.HexColor("#8a1c1c")

    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Times-Bold", fontSize=19,
            alignment=TA_LEFT, textColor=ink, spaceAfter=2,
        ),
        "eagle": ParagraphStyle(
            "eagle", fontName="Helvetica-Bold", fontSize=7.5, textColor=accent,
            spaceAfter=3, leading=9,
        ),
        "meta": ParagraphStyle(
            "meta", fontName="Helvetica", fontSize=8, textColor=muted, leading=11,
        ),
        "field": ParagraphStyle(
            "field", fontName="Helvetica", fontSize=9, textColor=ink, leading=16,
        ),
        "req": ParagraphStyle(
            "req", fontName="Times-Roman", fontSize=10.5, textColor=ink, leading=14,
        ),
        "note": ParagraphStyle(
            "note", fontName="Helvetica-Oblique", fontSize=7.8, textColor=muted,
            leading=10,
        ),
    }

    story: list = []

    if badge.eagle_required:
        story.append(Paragraph("EAGLE-REQUIRED", styles["eagle"]))
    kind = "Workbook" if options.style == "workbook" else "Requirements Checklist"
    story.append(Paragraph(f"{escape(badge.name)} Merit Badge", styles["title"]))
    story.append(Paragraph(f"{kind} &middot; generated {date.today().isoformat()}",
                           styles["meta"]))
    story.append(Spacer(1, 10))

    def blank(label: str, value: str, width: int = 46) -> str:
        filled = escape(value) if value else "&nbsp;" * width
        return f"<b>{escape(label)}:</b> <u>{filled}</u>"

    story.append(Paragraph(blank("Scout", options.scout), styles["field"]))
    story.append(Paragraph(blank("Counselor", options.counselor), styles["field"]))
    if options.unit:
        story.append(Paragraph(blank("Unit", options.unit), styles["field"]))
    story.append(Paragraph(
        blank("Date started", "", 22) + " &nbsp;&nbsp; " + blank("Completed", "", 22),
        styles["field"],
    ))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.7, color=rule))
    story.append(Spacer(1, 6))

    retrieved = badge.source_retrieved[:10] if badge.source_retrieved else "unknown date"
    story.append(Paragraph(escape(DISCLAIMER), styles["note"]))
    story.append(Paragraph(
        f"Requirements retrieved {escape(retrieved)} from {escape(badge.url)}",
        styles["note"],
    ))
    story.append(Spacer(1, 12))

    def checkbox():
        """A hollow square, drawn rather than typeset: the Type-1 base fonts
        have no reliable empty-box glyph and fall back to a filled block."""
        d = Drawing(10, 11)
        d.add(Rect(0, 0, 9.5, 9.5, strokeColor=ink, strokeWidth=0.9, fillColor=None))
        return d

    def emit(req: Requirement, depth: int) -> list:
        indent = depth * INDENT_PT
        text_width = CONTENT_WIDTH_PT - indent - BOX_COL_PT
        style = ParagraphStyle(
            f"req{depth}", parent=styles["req"],
            leftIndent=0, firstLineIndent=0,
        )
        text = f"<b>{escape(req.label)}</b> {escape(req.text)}"
        if options.show_signoff:
            text += (
                f'<font size="7" color="#5b6b7c">'
                f'&nbsp;&nbsp;Date <u>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</u>'
                f'&nbsp;Init. <u>&nbsp;&nbsp;&nbsp;&nbsp;</u></font>'
            )

        # An empty leading column carries the indentation, so each row is a
        # self-contained flowable that KeepTogether can move between pages.
        cells = [["", checkbox(), Paragraph(text, style)]]
        widths = [indent, BOX_COL_PT, text_width]
        row = Table(
            cells, colWidths=widths,
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (1, 0), (1, 0), 4),
            ]),
            hAlign="LEFT",
        )
        block: list = [row]

        for note in visible_notes(req, options):
            block.append(Paragraph(
                escape(note),
                ParagraphStyle(f"n{depth}", parent=styles["note"],
                               leftIndent=indent + BOX_COL_PT),
            ))

        if options.style == "workbook" and not req.children:
            block.append(Spacer(1, 4))
            for _ in range(options.note_lines):
                block.append(HRFlowable(
                    width=CONTENT_WIDTH_PT - indent - BOX_COL_PT,
                    thickness=0.5, color=rule,
                    spaceBefore=9, spaceAfter=0, hAlign="RIGHT",
                ))
            block.append(Spacer(1, 8))
        else:
            block.append(Spacer(1, 3))

        out = [KeepTogether(block)]
        for child in req.children:
            out.extend(emit(child, depth + 1))
        return out

    for req in badge.requirements:
        story.extend(emit(req, 0))
        story.append(Spacer(1, 5))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(0.75 * inch, 0.5 * inch,
                          f"{badge.name} Merit Badge - {kind}")
        canvas.drawRightString(letter[0] - 0.75 * inch, 0.5 * inch,
                               f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        path, pagesize=letter,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.7 * inch, bottomMargin=0.75 * inch,
        title=f"{badge.name} Merit Badge {kind}", author="merit-badge-workbook",
    )
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
