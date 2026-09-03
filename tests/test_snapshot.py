"""Tests for the shipped requirements snapshot and the update check."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from mbworkbook import snapshot as snap  # noqa: E402
from mbworkbook.models import Badge, CatalogEntry, Requirement  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "sample_badge.html"


def make_badge(slug="widgetry", texts=("First", "Second")) -> Badge:
    return Badge(
        name=slug.title(),
        slug=slug,
        url=f"https://example.invalid/{slug}/",
        requirements=[
            Requirement(marker=str(i), text=t) for i, t in enumerate(texts, 1)
        ],
        source_retrieved="2026-01-01T00:00:00+00:00",
    )


def entry(slug="widgetry") -> CatalogEntry:
    return CatalogEntry(slug.title(), slug, f"https://example.invalid/{slug}/")


# ---------------------------------------------------------------- fingerprint


def test_fingerprint_ignores_the_retrieval_date():
    a = make_badge()
    b = make_badge()
    b.source_retrieved = "2026-09-03T00:00:00+00:00"
    assert snap.fingerprint(a) == snap.fingerprint(b)


def test_fingerprint_ignores_whitespace_changes():
    a = make_badge(texts=("Do the thing",))
    b = make_badge(texts=("Do  the\n thing",))
    assert snap.fingerprint(a) == snap.fingerprint(b)


def test_fingerprint_changes_when_requirement_text_changes():
    a = make_badge(texts=("First", "Second"))
    b = make_badge(texts=("First", "Second, revised"))
    assert snap.fingerprint(a) != snap.fingerprint(b)


def test_fingerprint_changes_when_a_requirement_is_added():
    assert snap.fingerprint(make_badge(texts=("A",))) != snap.fingerprint(
        make_badge(texts=("A", "B")))


# ------------------------------------------------------------ round tripping


def test_snapshot_round_trips_through_disk(tmp_path):
    built, _ = snap.build([entry()], fetch=lambda e: make_badge())
    path = snap.save(built, tmp_path / "requirements.json")

    loaded = snap.load(path)
    assert loaded.built == built.built
    assert loaded.badge("widgetry").name == "Widgetry"
    assert loaded.catalog()[0].slug == "widgetry"
    assert loaded.fingerprints == built.fingerprints


def test_load_returns_an_empty_snapshot_when_the_file_is_missing(tmp_path):
    result = snap.load(tmp_path / "nope.json")
    assert not result
    assert result.badge("camping") is None


def test_load_survives_a_corrupt_file(tmp_path):
    """A bad snapshot must degrade to live fetching, not crash the app."""
    path = tmp_path / "requirements.json"
    path.write_text("{not json", encoding="utf-8")
    assert not snap.load(path)


def test_load_rejects_a_future_format(tmp_path):
    path = tmp_path / "requirements.json"
    path.write_text('{"format": 99, "badges": {}}', encoding="utf-8")
    assert not snap.load(path)


# ------------------------------------------------------------------- building


def test_build_skips_badges_that_parse_to_nothing():
    entries = [entry("good"), entry("empty")]

    def fetch(e):
        return make_badge(e.slug) if e.slug == "good" else Badge(
            name="Empty", slug="empty", url="u")

    result, problems = snap.build(entries, fetch=fetch)
    assert set(result.badges) == {"good"}
    assert any("zero requirements" in p for p in problems)


def test_build_reports_a_failure_without_losing_the_rest():
    entries = [entry("good"), entry("boom")]

    def fetch(e):
        if e.slug == "boom":
            raise RuntimeError("network went away")
        return make_badge(e.slug)

    result, problems = snap.build(entries, fetch=fetch)
    assert set(result.badges) == {"good"}
    assert any("network went away" in p for p in problems)


def test_build_stops_when_cancelled():
    entries = [entry(f"b{i}") for i in range(5)]
    seen: list[str] = []

    def fetch(e):
        seen.append(e.slug)
        return make_badge(e.slug)

    result, problems = snap.build(
        entries, fetch=fetch, should_cancel=lambda: len(seen) >= 2)
    assert len(seen) == 2
    assert any("cancelled" in p for p in problems)


# --------------------------------------------------------------- update check


def base_snapshot(slugs=("a", "b")) -> snap.Snapshot:
    built, _ = snap.build([entry(s) for s in slugs],
                          fetch=lambda e: make_badge(e.slug))
    return built


def test_check_reports_no_changes_when_the_site_matches():
    base = base_snapshot()
    report = snap.check_for_updates(
        base, [entry("a"), entry("b")], fetch=lambda e: make_badge(e.slug))
    assert not report.any_changes
    assert report.unchanged == 2
    assert "No changes" in report.summary()


def test_check_spots_edited_requirements():
    base = base_snapshot()

    def fetch(e):
        if e.slug == "b":
            return make_badge("b", texts=("First", "Second, revised in 2027"))
        return make_badge(e.slug)

    report = snap.check_for_updates(base, [entry("a"), entry("b")], fetch=fetch)
    assert report.changed == ["b"]
    assert report.unchanged == 1
    assert report.any_changes


def test_check_spots_badges_added_to_the_index():
    base = base_snapshot()
    report = snap.check_for_updates(
        base, [entry("a"), entry("b"), entry("c")],
        fetch=lambda e: make_badge(e.slug))
    assert report.added == ["c"]


def test_check_spots_badges_dropped_from_the_index():
    base = base_snapshot()
    report = snap.check_for_updates(
        base, [entry("a")], fetch=lambda e: make_badge(e.slug))
    assert report.removed == ["b"]


def test_check_records_a_fetch_failure_without_calling_it_a_change():
    base = base_snapshot()

    def fetch(e):
        raise RuntimeError("timed out")

    report = snap.check_for_updates(base, [entry("a"), entry("b")], fetch=fetch)
    assert not report.changed
    assert len(report.failed) == 2


def test_check_stops_when_cancelled():
    base = base_snapshot([f"b{i}" for i in range(5)])
    seen: list[str] = []

    def fetch(e):
        seen.append(e.slug)
        return make_badge(e.slug)

    report = snap.check_for_updates(
        base, [entry(f"b{i}") for i in range(5)], fetch=fetch,
        should_cancel=lambda: len(seen) >= 2)
    assert report.cancelled
    assert "cancelled" in report.summary().lower()


# ---------------------------------------------------------- the shipped file


def test_the_shipped_snapshot_is_present_and_sane():
    """The build is meant to ship one; a missing file means a broken release."""
    shipped = snap.load()
    if not shipped:
        pytest.skip("no snapshot built in this tree; run tools/build_snapshot.py")

    assert len(shipped.badges) > 100
    assert shipped.built_date
    for slug in ("camping", "cooking", "first-aid"):
        badge = shipped.badge(slug)
        assert badge is not None and badge.requirements
        assert slug in shipped.fingerprints
    assert shipped.badge("camping").eagle_required is True
