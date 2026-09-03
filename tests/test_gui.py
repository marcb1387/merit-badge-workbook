"""Tests for the pieces the GUI leans on.

The window itself needs a display, so these cover the parts that do not:
the background-job plumbing and the shared service layer.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from mbworkbook.models import Badge, CatalogEntry  # noqa: E402
from mbworkbook.render import WorkbookOptions  # noqa: E402
from mbworkbook.service import (  # noqa: E402
    fetch_badge,
    output_filename,
    write_output,
)

FIXTURE = Path(__file__).parent / "fixtures" / "sample_badge.html"


def drain(worker, timeout: float = 3.0) -> list:
    """Collect every queued message until the worker signals it is done."""
    messages = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        while not worker.queue.empty():
            msg = worker.queue.get_nowait()
            messages.append(msg)
            if msg.kind == "done":
                return messages
        time.sleep(0.01)
    raise AssertionError("worker never finished")


def worker_class():
    try:
        from mbworkbook.gui import Worker
    except SystemExit:  # tkinter missing
        pytest.skip("tkinter is not installed")
    return Worker


# ---------------------------------------------------------------- worker


def test_worker_reports_results_then_done():
    worker = worker_class()()
    worker.start(lambda: worker.send("log", "hello"))
    kinds = [m.kind for m in drain(worker)]
    assert kinds == ["log", "done"]


def test_worker_turns_exceptions_into_error_messages():
    worker = worker_class()()

    def boom():
        raise ValueError("nope")

    worker.start(boom)
    messages = drain(worker)
    error = next(m for m in messages if m.kind == "error")
    assert "ValueError: nope" in str(error.payload)
    # A failed job must still report done, or the UI stays stuck on "busy".
    assert messages[-1].kind == "done"


def test_worker_refuses_a_second_job_while_busy():
    Worker = worker_class()
    worker = Worker()
    worker.start(lambda: time.sleep(0.25))
    assert worker.start(lambda: worker.send("log", "should not run")) is False
    drain(worker)


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
