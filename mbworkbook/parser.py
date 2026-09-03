"""Turn a scouting.org merit badge page into a nested requirement tree.

The page markup is Elementor-generated and changes shape from badge to badge:
some pages put sub-requirements inside accordion panels, some use nested
``<ol>`` lists, some use ``<p>`` blocks separated by ``<br>``. Rather than
depend on any one of those, we flatten the requirements region into text lines
in document order and rebuild the tree from the printed markers ("1.", "a.",
"(1)"). That is the one thing every layout agrees on.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup, NavigableString, Tag

from .models import Badge, Requirement

# --------------------------------------------------------------------------
# Marker recognition
# --------------------------------------------------------------------------

# Order matters: "(1)" must be tried before "1." style patterns.
MARKER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("paren_num", re.compile(r"^\((\d{1,2})\)\s+(?=\S)")),
    ("paren_alpha", re.compile(r"^\(([a-z])\)\s+(?=\S)")),
    ("roman", re.compile(r"^((?:i{2,3}|iv|vi{0,3}|ix|xi{0,3}))[.)]\s+(?=\S)")),
    ("num", re.compile(r"^(\d{1,2})[.)]\s+(?=\S)")),
    ("alpha", re.compile(r"^([a-z])[.)]\s+(?=\S)")),
]

# Depth ordering used when a marker type has not been seen yet in this badge.
TYPE_RANK = {"num": 0, "alpha": 1, "paren_alpha": 1, "paren_num": 2, "roman": 3}

MARKER_FORMAT = {
    "num": "{}",
    "alpha": "{}",
    "paren_num": "({})",
    "paren_alpha": "({})",
    "roman": "{}",
}

NOTE_PREFIXES = ("resources:", "resource:", "note:", "notes:")

# Text that means we have run past the end of the requirements section.
STOP_LINE = re.compile(
    r"^\s*(view related merit badges|related merit badges|merit badge pamphlet|"
    r"pamphlet|counselor information|digital resource guide|scoutly|"
    r"connect with us|resources for merit badge|©|copyright)\b",
    re.I,
)

# Boilerplate lines inside the requirements block that are not requirements.
NOISE_LINE = re.compile(
    r"^\s*(the requirements will be fed dynamically|the previous version of the "
    r"merit badge requirements|the requirements posted here are|this will always "
    r"be the best place|merit badge requirements?\s*$|requirements\s*$|"
    r"skip to main content|toggle size|close chat)",
    re.I,
)

REQ_HEADING = re.compile(r"\brequirements\b", re.I)

BLOCK_TAGS = {
    "p", "li", "summary", "dt", "dd", "td", "th", "blockquote",
    "h2", "h3", "h4", "h5", "h6", "figcaption",
}

# Elementor accordion / toggle title containers, which are usually divs.
TITLE_CLASS_HINTS = (
    "elementor-tab-title",
    "elementor-toggle-title",
    "elementor-accordion-title",
    "e-n-accordion-item-title",
    "accordion-title",
)

DROP_TAGS = ("script", "style", "noscript", "nav", "header", "footer", "form", "svg")

# The current scouting.org template wraps each requirement in its own element and
# puts the printed marker in a sibling <span>, so the marker and its text never
# share a line. When these classes are present we read that structure directly
# instead of flattening the region; it is the same page, said unambiguously.
MB_ITEM = "mb-requirement-item"
MB_PARENT = "mb-requirement-parent"
MB_CHILDREN = "mb-requirement-children-list"
MB_CHILD = "mb-requirement-child"
MB_LISTNUMBER = "mb-requirement-listnumber"


# --------------------------------------------------------------------------
# Line extraction
# --------------------------------------------------------------------------


def _is_block(tag: Tag) -> bool:
    if tag.name in BLOCK_TAGS:
        return True
    classes = tag.get("class") or []
    return any(hint in c for c in classes for hint in TITLE_CLASS_HINTS)


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _block_lines(tag: Tag) -> list[str]:
    """Text of a block, with <br> treated as a line break."""
    parts: list[str] = []
    for node in tag.descendants:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif isinstance(node, Tag) and node.name == "br":
            parts.append("\n")
    raw = "".join(parts)
    return [_clean(line) for line in raw.split("\n") if _clean(line)]


def extract_lines(root: Tag) -> list[str]:
    """Flatten a subtree into text lines in document order, without duplicates.

    A block is emitted only if it contains no nested blocks of its own, so an
    ``<li>`` wrapping an ``<ol>`` contributes its own lead-in text but does not
    also re-emit its children.
    """
    lines: list[str] = []
    for tag in root.find_all(True):
        if not isinstance(tag, Tag) or not _is_block(tag):
            continue
        nested = [d for d in tag.find_all(True) if _is_block(d)]
        if nested:
            # Emit only the text that belongs to this block directly.
            own = Tag(name="div")
            for child in list(tag.children):
                if isinstance(child, Tag) and _is_block(child):
                    continue
                if isinstance(child, Tag) and any(
                    _is_block(d) for d in child.find_all(True)
                ):
                    continue
                own.append(child.__copy__() if isinstance(child, Tag) else str(child))
            candidate = _block_lines(own)
        else:
            candidate = _block_lines(tag)
        for line in candidate:
            if lines and lines[-1] == line:
                continue
            lines.append(line)
    return lines


def _br_lines(tag: Tag) -> list[str]:
    """Like :func:`_block_lines`, but *only* ``<br>`` starts a new line.

    ``_block_lines`` splits on the newlines already present in the source, which
    would tear "(a)" away from the text that follows it in the current template.
    """
    chunks: list[list[str]] = [[]]
    for node in tag.descendants:
        if isinstance(node, NavigableString):
            chunks[-1].append(str(node))
        elif isinstance(node, Tag) and node.name == "br":
            chunks.append([])
    lines = []
    for chunk in chunks:
        line = _clean(re.sub(r"\s+", " ", "".join(chunk)))
        if line:
            lines.append(line)
    return lines


def structured_lines(root: Tag) -> list[str]:
    """Lines from the ``mb-requirement-*`` template, marker rejoined to its text.

    Returns ``[]`` when the page does not use that template, so the caller can
    fall back to :func:`extract_lines`.
    """
    items = root.find_all(class_=MB_ITEM)
    if not items:
        return []

    lines: list[str] = []
    for item in items:
        parent = item.find(class_=MB_PARENT)
        if parent is not None:
            lines.extend(_br_lines(parent))
        for child in item.find_all(class_=MB_CHILD):
            lines.extend(_br_lines(child))
    return lines


def find_requirements_root(soup: BeautifulSoup) -> Tag:
    """Return the region of the page that holds the requirements.

    Falls back to the whole body; the line filters downstream tolerate that.
    """
    for tag in DROP_TAGS:
        for node in soup.find_all(tag):
            node.decompose()

    headings = [
        h
        for h in soup.find_all(["h1", "h2", "h3", "h4", "h5"])
        if REQ_HEADING.search(h.get_text(" ", strip=True))
    ]
    for heading in headings:
        # Walk up until we find an ancestor that also contains numbered items.
        node: Tag | None = heading.parent
        for _ in range(6):
            if node is None:
                break
            text = node.get_text(" ", strip=True)
            if re.search(r"\b1\.\s+\S", text) and re.search(r"\b2\.\s+\S", text):
                return node
            node = node.parent
    return soup.body or soup


# --------------------------------------------------------------------------
# Tree building
# --------------------------------------------------------------------------


def split_marker(line: str) -> tuple[str, str, str] | None:
    """Return (marker_type, marker_value, remaining_text) if the line is marked."""
    for kind, pattern in MARKER_PATTERNS:
        match = pattern.match(line)
        if match:
            return kind, match.group(1), line[match.end():].strip()
    return None


def build_tree(lines: list[str]) -> list[Requirement]:
    """Rebuild the requirement hierarchy from marker prefixes.

    A stack of marker types tracks nesting. Seeing a type already on the stack
    means "sibling of that level"; seeing a new type means "one level deeper".
    This handles 1 / a / (1) as well as any other scheme a badge happens to use.
    """
    roots: list[Requirement] = []
    stack: list[tuple[str, Requirement]] = []  # (marker_type, node)
    started = False

    for line in lines:
        if STOP_LINE.match(line):
            if started:
                break
            continue
        if NOISE_LINE.match(line):
            continue

        parsed = split_marker(line)

        if parsed is None:
            if not started:
                continue
            lowered = line.lower()
            target = stack[-1][1] if stack else (roots[-1] if roots else None)
            if target is None:
                continue
            if lowered.startswith(NOTE_PREFIXES) or target.notes:
                target.notes.append(line)
            else:
                # A wrapped continuation of the previous requirement.
                target.text = f"{target.text} {line}".strip()
            continue

        kind, value, text = parsed

        # The first marked line must be requirement 1; anything before it is
        # page furniture (article text that happens to contain "3. ").
        if not started:
            if not (kind == "num" and value == "1"):
                continue
            started = True

        if not text:
            continue

        types = [t for t, _ in stack]
        if kind in types:
            depth = types.index(kind)
            del stack[depth:]
        else:
            rank = TYPE_RANK.get(kind, len(types))
            while stack and TYPE_RANK.get(stack[-1][0], 0) >= rank:
                stack.pop()

        node = Requirement(
            marker=MARKER_FORMAT[kind].format(value),
            text=text,
            level=len(stack) + 1,
        )
        if stack:
            stack[-1][1].children.append(node)
        else:
            roots.append(node)
        stack.append((kind, node))

    return roots


# --------------------------------------------------------------------------
# Page-level parsing
# --------------------------------------------------------------------------


def _badge_name(soup: BeautifulSoup, fallback: str) -> str:
    for h in soup.find_all(["h1", "h2"]):
        text = h.get_text(" ", strip=True)
        m = re.match(r"^(.*?)\s+Merit Badge\b", text, re.I)
        if m and m.group(1):
            return _clean(m.group(1))
    if soup.title:
        m = re.match(r"^(.*?)\s+Merit Badge", soup.title.get_text(strip=True), re.I)
        if m:
            return _clean(m.group(1))
    return fallback


def _overview(soup: BeautifulSoup) -> str:
    for h in soup.find_all(["h2", "h3", "h4"]):
        if re.search(r"\boverview\b", h.get_text(" ", strip=True), re.I):
            for sib in h.find_all_next("p", limit=6):
                text = _clean(sib.get_text(" ", strip=True))
                if len(text) > 80:
                    return text
    return ""


def parse_badge_page(
    html: str,
    *,
    slug: str,
    url: str,
    eagle_required: bool = False,
    name: str | None = None,
) -> Badge:
    """Parse a merit badge page into a :class:`Badge`."""
    soup = BeautifulSoup(html, "lxml")
    display_name = name or _badge_name(soup, slug.replace("-", " ").title())
    overview = _overview(soup)

    root = find_requirements_root(soup)
    lines = structured_lines(root) or structured_lines(soup) or extract_lines(root)
    requirements = build_tree(lines)

    return Badge(
        name=display_name,
        slug=slug,
        url=url,
        eagle_required=eagle_required,
        overview=overview,
        requirements=requirements,
        source_retrieved=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
