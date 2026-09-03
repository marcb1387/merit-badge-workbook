"""Printable HTML checklist / workbook."""

from __future__ import annotations

from datetime import date
from html import escape

from ..models import Badge, Requirement
from . import DISCLAIMER, WorkbookOptions, visible_notes

CSS = """
:root { --ink:#16202b; --muted:#5b6b7c; --rule:#c8d2dc; --accent:#8a1c1c; }
* { box-sizing: border-box; }
body { font-family: Georgia, "Iowan Old Style", serif; color: var(--ink);
       max-width: 46rem; margin: 2rem auto; padding: 0 1.25rem; line-height: 1.5; }
header { border-bottom: 3px double var(--rule); padding-bottom: .75rem; margin-bottom: 1rem; }
h1 { font-size: 1.7rem; margin: 0 0 .2rem; }
.eagle { color: var(--accent); font-size: .8rem; letter-spacing: .1em;
         text-transform: uppercase; font-family: system-ui, sans-serif; }
.fields { display: flex; flex-wrap: wrap; gap: 1rem 2rem; margin: .9rem 0 .4rem;
          font-family: system-ui, sans-serif; font-size: .85rem; }
.field { flex: 1 1 12rem; }
.field span { color: var(--muted); display: block; font-size: .72rem;
              text-transform: uppercase; letter-spacing: .06em; }
.field .line { border-bottom: 1px solid var(--rule); min-height: 1.4rem;
               padding-top: .15rem; }
.source, .disclaimer { font-family: system-ui, sans-serif; font-size: .75rem;
                       color: var(--muted); }
.disclaimer { border-left: 3px solid var(--rule); padding-left: .7rem; margin: 1rem 0 1.5rem; }
ol.reqs, ol.reqs ol { list-style: none; margin: 0; padding: 0; }
ol.reqs ol { margin-left: 1.6rem; }
li.req { margin: .55rem 0; page-break-inside: avoid; }
.row { display: flex; align-items: flex-start; gap: .55rem; }
.box { flex: 0 0 auto; width: .95rem; height: .95rem; border: 1.5px solid var(--ink);
       border-radius: 2px; margin-top: .28rem; }
.marker { flex: 0 0 auto; font-weight: 700; min-width: 1.9rem; }
.text { flex: 1 1 auto; }
.signoff { flex: 0 0 auto; font-family: system-ui, sans-serif; font-size: .7rem;
           color: var(--muted); white-space: nowrap; padding-top: .3rem; }
.signoff u { color: transparent; text-decoration-color: var(--rule); }
.note { font-size: .8rem; color: var(--muted); margin: .2rem 0 0 3.4rem; }
.lines { margin: .35rem 0 .8rem 3.4rem; }
.lines div { border-bottom: 1px solid var(--rule); height: 1.45rem; }
footer { margin-top: 2rem; border-top: 1px solid var(--rule); padding-top: .6rem;
         font-family: system-ui, sans-serif; font-size: .75rem; color: var(--muted); }
@media print {
  body { margin: 0; max-width: none; font-size: 11pt; }
  .disclaimer { break-inside: avoid; }
  a { color: inherit; text-decoration: none; }
}
"""


def _field(label: str, value: str) -> str:
    return (
        f'<div class="field"><span>{escape(label)}</span>'
        f'<div class="line">{escape(value)}</div></div>'
    )


def render_html(badge: Badge, options: WorkbookOptions) -> str:
    def emit(req: Requirement) -> str:
        signoff = ""
        if options.show_signoff:
            signoff = '<div class="signoff">Date <u>________</u> Init. <u>_____</u></div>'
        parts = [
            '<li class="req"><div class="row">',
            '<div class="box"></div>',
            f'<div class="marker">{escape(req.label)}</div>',
            f'<div class="text">{escape(req.text)}</div>',
            signoff,
            "</div>",
        ]
        for note in visible_notes(req, options):
            parts.append(f'<div class="note">{escape(note)}</div>')
        if options.style == "workbook" and not req.children:
            rules = "".join("<div></div>" for _ in range(options.note_lines))
            parts.append(f'<div class="lines">{rules}</div>')
        if req.children:
            parts.append("<ol>")
            parts.extend(emit(child) for child in req.children)
            parts.append("</ol>")
        parts.append("</li>")
        return "".join(parts)

    body = "".join(emit(r) for r in badge.requirements)
    eagle = '<div class="eagle">Eagle-required</div>' if badge.eagle_required else ""
    kind = "Workbook" if options.style == "workbook" else "Requirements Checklist"

    fields = [
        _field("Scout", options.scout),
        _field("Counselor", options.counselor),
    ]
    if options.unit:
        fields.append(_field("Unit", options.unit))
    fields.append(_field("Date started", ""))
    fields.append(_field("Date completed", ""))

    retrieved = badge.source_retrieved[:10] if badge.source_retrieved else "unknown date"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(badge.name)} Merit Badge {escape(kind)}</title>
<style>{CSS}</style></head>
<body>
<header>
  {eagle}
  <h1>{escape(badge.name)} Merit Badge</h1>
  <div class="source">{escape(kind)} &middot; generated {date.today().isoformat()}</div>
  <div class="fields">{''.join(fields)}</div>
</header>
<p class="disclaimer">{escape(DISCLAIMER)}<br>
Requirements retrieved {escape(retrieved)} from
<a href="{escape(badge.url)}">{escape(badge.url)}</a>.</p>
<ol class="reqs">{body}</ol>
<footer>{badge.total_requirements()} requirement items &middot;
{len(badge.requirements)} top-level.</footer>
</body></html>
"""
