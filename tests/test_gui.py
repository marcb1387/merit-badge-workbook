"""Tests for the service layer the GUI and CLI share.

The window itself needs a display, so it is not exercised here; the background
job plumbing it uses lives in test_paths_and_jobs.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from mbworkbook.models import Badge, CatalogEntry  # noqa: E402
from mbworkbook.render import WorkbookOptions  # noqa: E402
from mbworkbook.service import (  # noqa: E402
    fetch_badge,
    output_filename,
    write_cards,
    write_output,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_badge.html"


# ---------------------------------------------------------------- service


def test_fetch_badge_reads_a_local_page():
    badge = fetch_badge(None, html_file=FIXTURE)
    assert badge.name == "Widgetry"
    assert len(badge.requirements) == 5


def test_fetch_badge_keeps_catalog_metadata():
    entry = CatalogEntry("Widgetry", "widgetry", "https://example.invalid/", True)
    badge = fetch_badge(entry, html_file=FIXTURE)
    assert badge.eagle_required is True
    assert badge.url == "https://example.invalid/"


def test_fetch_badge_needs_a_source():
    with pytest.raises(ValueError):
        fetch_badge(None)


def test_output_filename_reflects_style_and_format():
    badge = Badge(name="Widgetry", slug="widgetry", url="u")
    assert output_filename(badge, "checklist", "md") == "widgetry-checklist.md"
    assert output_filename(badge, "workbook", "pdf") == "widgetry-workbook.pdf"


@pytest.mark.parametrize("fmt", ["md", "html", "json", "pdf"])
def test_write_output_creates_a_file_in_every_format(tmp_path, fmt):
    badge = fetch_badge(None, html_file=FIXTURE)
    path = write_output(
        badge, WorkbookOptions(style="workbook"), fmt,
        tmp_path / "nested" / output_filename(badge, "workbook", fmt),
    )
    assert path.exists() and path.stat().st_size > 0


# ------------------------------------------------------------------ cards


def test_write_cards_draws_its_own_card_without_a_template(tmp_path):
    badge = fetch_badge(None, html_file=FIXTURE)
    path = write_cards([badge], WorkbookOptions(scout="A. Scout"),
                       tmp_path / "cards.pdf")
    assert path.exists() and path.stat().st_size > 0
    assert path.read_bytes().startswith(b"%PDF")


def test_write_cards_packs_several_badges_into_one_file(tmp_path):
    badge = fetch_badge(None, html_file=FIXTURE)
    one = write_cards([badge], WorkbookOptions(), tmp_path / "one.pdf")
    many = write_cards([badge] * 5, WorkbookOptions(), tmp_path / "many.pdf")
    assert many.stat().st_size > one.stat().st_size


def test_card_filename_is_not_the_checklist_filename():
    badge = Badge(name="Widgetry", slug="widgetry", url="u")
    assert output_filename(badge, "checklist", "card") == "widgetry-blue-card.pdf"
    assert output_filename(badge, "workbook", "card") == "widgetry-blue-card.pdf"


def test_a_template_that_is_not_a_blue_card_is_rejected(tmp_path):
    """Better a clear error than a stack of blank forms."""
    from mbworkbook.render.cardform import TemplateError, fill_template, looks_like_template

    badge = fetch_badge(None, html_file=FIXTURE)
    decoy = write_output(badge, WorkbookOptions(), "pdf", tmp_path / "decoy.pdf")

    assert looks_like_template(decoy) is False
    assert looks_like_template(tmp_path / "missing.pdf") is False
    with pytest.raises(TemplateError):
        fill_template(decoy, [badge], WorkbookOptions(), str(tmp_path / "out.pdf"))


def test_unit_number_is_pulled_out_of_the_unit_name():
    from mbworkbook.render.cardform import _unit_number

    assert _unit_number("Troop 379") == "379"
    assert _unit_number("Crew 1") == "1"
    assert _unit_number("") == ""
