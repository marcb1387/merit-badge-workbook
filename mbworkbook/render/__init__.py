"""Output renderers: markdown, html, pdf, json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

from ..models import Badge, Requirement

DISCLAIMER = (
    "This checklist is a note-taking aid, not a substitute for the merit badge "
    "pamphlet or for the counselor's judgement. The official, current "
    "requirements are the ones published at scouting.org."
)


@dataclass
class WorkbookOptions:
    """Everything that varies between two runs for the same badge."""

    scout: str = ""
    counselor: str = ""
    unit: str = ""
    style: str = "checklist"  # "checklist" or "workbook"
    note_lines: int = 4  # ruled lines per requirement in workbook style
    show_signoff: bool = True  # date + initials columns
    include_notes: bool = True  # keep "Resources:" lines from the page


def visible_notes(req: Requirement, options: WorkbookOptions) -> list[str]:
    return req.notes if options.include_notes else []


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def render_markdown(badge: Badge, options: WorkbookOptions) -> str:
    out: list[str] = []
    title = f"{badge.name} Merit Badge"
    if badge.eagle_required:
        title += " (Eagle-required)"
    out.append(f"# {title}")
    out.append("")

    meta = [
        f"**Scout:** {options.scout or '_' * 30}",
        f"**Counselor:** {options.counselor or '_' * 30}",
    ]
    if options.unit:
        meta.append(f"**Unit:** {options.unit}")
    meta.append(f"**Date started:** {'_' * 20}")
    out.extend(meta)
    out.append("")
    out.append(f"Requirements retrieved from <{badge.url}>")
    if badge.source_retrieved:
        out.append(f"on {badge.source_retrieved[:10]}. Generated {date.today().isoformat()}.")
    out.append("")
    out.append(f"> {DISCLAIMER}")
    out.append("")
    out.append("---")
    out.append("")

    def emit(req: Requirement, depth: int) -> None:
        indent = "    " * depth
        signoff = "  — Date: ______  Initials: ______" if options.show_signoff else ""
        out.append(f"{indent}- [ ] **{req.label}** {req.text}{signoff}")
        for note in visible_notes(req, options):
            out.append(f"{indent}  - _{note}_")
        if options.style == "workbook" and not req.children:
            out.append("")
            for _ in range(options.note_lines):
                out.append(f"{indent}  {'_' * 70}")
            out.append("")
        for child in req.children:
            emit(child, depth + 1)

    for req in badge.requirements:
        emit(req, 0)
        out.append("")

    out.append("---")
    out.append("")
    out.append(
        f"{badge.total_requirements()} requirement items "
        f"({len(badge.requirements)} top-level)."
    )
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# JSON
# --------------------------------------------------------------------------


def render_json(badge: Badge, options: WorkbookOptions) -> str:
    payload = badge.to_dict()
    payload["generated"] = date.today().isoformat()
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
