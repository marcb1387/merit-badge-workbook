"""Tests for parsing and rendering. Run with: python -m pytest -q"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mbworkbook.catalog import parse_catalog, resolve  # noqa: E402
from mbworkbook.models import CatalogEntry  # noqa: E402
from mbworkbook.parser import build_tree, parse_badge_page, split_marker  # noqa: E402
from mbworkbook.render import WorkbookOptions, render_markdown  # noqa: E402
from mbworkbook.render.html import render_html  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "sample_badge.html"
STRUCTURED = Path(__file__).parent / "fixtures" / "sample_badge_structured.html"


def load():
    return parse_badge_page(
        FIXTURE.read_text(encoding="utf-8"),
        slug="widgetry",
        url="https://www.scouting.org/merit-badges/widgetry/",
    )


# ---------------------------------------------------------------- markers


def test_split_marker_recognizes_each_style():
    assert split_marker("1. Safety. Do the following:")[:2] == ("num", "1")
    assert split_marker("a. Explain the hazards")[:2] == ("alpha", "a")
    assert split_marker("(2) Eye irritation")[:2] == ("paren_num", "2")
    assert split_marker("iii. A roman sub-item")[:2] == ("roman", "iii")
    assert split_marker("No marker at all") is None
    # A decimal in prose must not be read as a marker.
    assert split_marker("3.5 miles") is None


def test_build_tree_nests_by_marker_type():
    tree = build_tree([
        "1. First",
        "a. First sub",
        "(1) Deep one",
        "(2) Deep two",
        "b. Second sub",
        "2. Second",
    ])
    assert [r.marker for r in tree] == ["1", "2"]
    assert [c.marker for c in tree[0].children] == ["a", "b"]
    assert [c.marker for c in tree[0].children[0].children] == ["(1)", "(2)"]
    assert tree[0].children[0].children[1].level == 3


def test_build_tree_ignores_prose_before_requirement_one():
    tree = build_tree([
        "Van Horn likes to connect requirement 4 with requirement 7.",
        "1. Real first requirement",
        "2. Real second requirement",
    ])
    assert len(tree) == 2
    assert tree[0].text == "Real first requirement"


def test_build_tree_stops_at_related_badges():
    tree = build_tree(["1. Keep me", "View Related Merit Badges", "1. Drop me"])
    assert len(tree) == 1


# ---------------------------------------------------------------- page parse


def test_parses_all_top_level_requirements():
    badge = load()
    assert [r.marker for r in badge.requirements] == ["1", "2", "3", "4", "5"]
    assert badge.name == "Widgetry"


def test_accordion_panels_become_children():
    badge = load()
    req1 = badge.requirements[0]
    assert [c.marker for c in req1.children] == ["a", "b"]
    assert [c.marker for c in req1.children[1].children] == ["(1)", "(2)", "(3)"]


def test_br_separated_subrequirements_are_split():
    badge = load()
    assert [c.marker for c in badge.requirements[1].children] == ["a", "b"]


def test_ordered_list_subrequirements_are_captured():
    badge = load()
    assert [c.marker for c in badge.requirements[2].children] == ["a", "b"]


def test_resource_lines_become_notes_not_requirements():
    badge = load()
    req4 = badge.requirements[3]
    assert req4.children == []
    assert len(req4.notes) == 2
    assert req4.notes[0].startswith("Resources:")


def test_boilerplate_is_dropped():
    badge = load()
    flat = [node.text for _, node in _walk(badge)]
    assert not any("fed dynamically" in t for t in flat)
    assert not any("previous version" in t for t in flat)


def test_counts_and_overview():
    badge = load()
    assert badge.total_requirements() == 16
    assert "Widgetry merit badge" in badge.overview


def test_walk_yields_dotted_paths():
    badge = load()
    paths = {".".join(p) for p, _ in _walk(badge)}
    assert "1.b.(3)" in paths


def _walk(badge):
    for req in badge.requirements:
        yield from req.walk()


# ---------------------------------------------------------------- catalog


def test_catalog_marks_eagle_required():
    html = """
    <a href="https://www.scouting.org/merit-badges/camping/">Eagle Required</a>
    <a href="https://www.scouting.org/merit-badges/camping/">Camping</a>
    <a href="https://www.scouting.org/merit-badges/basketry/">Basketry</a>
    <a href="https://www.scouting.org/skills/merit-badges/digital-resource-guides/aviation/">DRG</a>
    <a href="https://www.scouting.org/merit-badges/athletics/">Athletics (2) (3)</a>
    """
    catalog = parse_catalog(html)
    by_slug = {e.slug: e for e in catalog}
    assert by_slug["camping"].eagle_required is True
    assert by_slug["basketry"].eagle_required is False
    assert by_slug["athletics"].name == "Athletics"
    assert "aviation" not in by_slug


def test_resolve_is_forgiving():
    catalog = [
        CatalogEntry("Camping", "camping", "u", True),
        CatalogEntry("Personal Management", "personal-management", "u", True),
        CatalogEntry("Personal Fitness", "personal-fitness", "u", True),
        CatalogEntry("Fish & Wildlife Management", "fish-wildlife-management", "u"),
    ]
    assert resolve("camping", catalog).slug == "camping"
    assert resolve("CAMPING", catalog).slug == "camping"
    assert resolve("personal-management", catalog).slug == "personal-management"
    assert resolve("fish and wildlife", catalog).slug == "fish-wildlife-management"

    for bad in ["personal", "kayakking"]:
        try:
            resolve(bad, catalog)
        except LookupError:
            pass
        else:
            raise AssertionError(f"{bad!r} should not resolve")


# ---------------------------------------------------------------- renderers


def test_markdown_has_a_checkbox_per_item():
    badge = load()
    text = render_markdown(badge, WorkbookOptions())
    assert text.count("- [ ]") == badge.total_requirements()
    assert "**1.**" in text and "**(3)**" in text


def test_workbook_style_adds_ruled_lines_only_to_leaves():
    badge = load()
    text = render_markdown(badge, WorkbookOptions(style="workbook", note_lines=3))
    leaves = sum(1 for _, n in _walk(badge) if not n.children)
    assert text.count("_" * 70) == leaves * 3


def test_html_is_self_contained_and_escaped():
    badge = load()
    badge.requirements[0].text = "Tools & <safety>"
    html = render_html(badge, WorkbookOptions())
    assert "<style>" in html and "http-equiv" not in html
    assert "&amp; &lt;safety&gt;" in html


# ------------------------------------------------- current scouting.org template


def load_structured():
    return parse_badge_page(
        STRUCTURED.read_text(encoding="utf-8"),
        slug="widgetry",
        url="https://www.scouting.org/merit-badges/widgetry/",
    )


def test_structured_template_rejoins_marker_and_text():
    """The live template puts "1." in a <span> and the text in a sibling node."""
    badge = load_structured()
    assert [r.marker for r in badge.requirements] == ["1", "2"]
    assert badge.requirements[0].text == "Do the following:"
    assert badge.requirements[1].text.startswith("Describe the three classes")


def test_structured_template_nests_children():
    badge = load_structured()
    req1 = badge.requirements[0]
    assert [c.marker for c in req1.children] == ["(a)", "(b)"]
    assert req1.children[0].text.endswith("while working with widgets.")


def test_structured_template_keeps_resources_as_notes():
    badge = load_structured()
    notes = badge.requirements[0].children[0].notes
    assert notes[0] == "Resources: Widget Safety Tips (video)"
    assert notes[1] == "Widget Dust and Your Eyes (website)"


def test_structured_template_drops_the_unnumbered_note_item():
    badge = load_structured()
    flat = [n.text for _, n in _walk(badge)]
    assert not any("pamphlets are now free" in t for t in flat)
    assert not any("fed dynamically" in t for t in flat)


def test_legacy_fixture_still_uses_the_flattening_path():
    """No mb-requirement-* classes, so structured_lines must decline."""
    from mbworkbook.parser import structured_lines
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "lxml")
    assert structured_lines(soup) == []
