"""Tests for the platform directories and the background-job plumbing."""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402

from mbworkbook import paths  # noqa: E402
from mbworkbook.jobs import Cancelled, Worker  # noqa: E402


def drain(worker: Worker, timeout: float = 3.0) -> list:
    messages = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        for msg in worker.drain():
            messages.append(msg)
            if msg.kind == "done":
                return messages
        time.sleep(0.01)
    raise AssertionError("worker never finished")


# ------------------------------------------------------------------- paths


def test_env_overrides_win_on_every_platform(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.CONFIG_ENV, str(tmp_path / "cfg"))
    monkeypatch.setenv(paths.CACHE_ENV, str(tmp_path / "cache"))
    assert paths.config_dir() == tmp_path / "cfg"
    assert paths.cache_dir() == tmp_path / "cache"
    assert paths.settings_path() == tmp_path / "cfg" / "gui.json"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows conventions")
def test_windows_uses_appdata_and_localappdata(monkeypatch, tmp_path):
    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    monkeypatch.delenv(paths.CACHE_ENV, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))

    # Settings roam, the cache does not: that is the whole point of the split.
    assert paths.config_dir() == tmp_path / "Roaming" / paths.APP_NAME
    assert paths.cache_dir() == tmp_path / "Local" / paths.APP_NAME / "Cache"


def test_config_and_cache_are_never_the_same_directory():
    assert paths.config_dir() != paths.cache_dir()


def test_migration_is_skipped_when_an_override_is_set(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.CONFIG_ENV, str(tmp_path / "cfg"))
    assert paths.migrate_legacy_dirs() == []


def test_migration_does_not_clobber_an_existing_directory(monkeypatch, tmp_path):
    """If the new location already has settings, the old one is left alone."""
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "gui.json").write_text("{}", encoding="utf-8")
    current = tmp_path / "current"
    current.mkdir()

    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    monkeypatch.delenv(paths.CACHE_ENV, raising=False)
    monkeypatch.setattr(paths, "LEGACY_CONFIG", legacy)
    monkeypatch.setattr(paths, "LEGACY_CACHE", tmp_path / "missing")
    monkeypatch.setattr(paths, "config_dir", lambda: current)
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")

    assert paths.migrate_legacy_dirs() == []
    assert (legacy / "gui.json").exists()


def test_migration_moves_a_legacy_directory(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    (legacy / "gui.json").write_text('{"unit": "Troop 379"}', encoding="utf-8")
    current = tmp_path / "new" / "MeritBadgeWorkbook"

    monkeypatch.delenv(paths.CONFIG_ENV, raising=False)
    monkeypatch.delenv(paths.CACHE_ENV, raising=False)
    monkeypatch.setattr(paths, "LEGACY_CONFIG", legacy)
    monkeypatch.setattr(paths, "LEGACY_CACHE", tmp_path / "missing")
    monkeypatch.setattr(paths, "config_dir", lambda: current)
    monkeypatch.setattr(paths, "cache_dir", lambda: tmp_path / "cache")

    moved = paths.migrate_legacy_dirs()
    assert moved == [(legacy, current)]
    assert (current / "gui.json").read_text(encoding="utf-8") == '{"unit": "Troop 379"}'
    assert not legacy.exists()


# ------------------------------------------------------------------ worker


def test_worker_reports_results_then_done():
    worker = Worker()
    worker.start(lambda: worker.send("log", "hello"))
    assert [m.kind for m in drain(worker)] == ["log", "done"]


def test_worker_turns_exceptions_into_error_messages():
    worker = Worker()

    def boom():
        raise ValueError("nope")

    worker.start(boom)
    messages = drain(worker)
    error = next(m for m in messages if m.kind == "error")
    assert "ValueError: nope" in str(error.payload)
    # A failed job must still report done, or the UI stays stuck on "busy".
    assert messages[-1].kind == "done"


def test_worker_refuses_a_second_job_while_busy():
    worker = Worker()
    worker.start(lambda: time.sleep(0.25))
    assert worker.start(lambda: worker.send("log", "should not run")) is False
    drain(worker)


def test_cancel_stops_a_long_job_and_reports_it():
    worker = Worker()
    done: list[int] = []

    def job():
        for i in range(100):
            worker.raise_if_cancelled()
            done.append(i)
            time.sleep(0.01)

    worker.start(job)
    time.sleep(0.05)
    worker.cancel()
    kinds = [m.kind for m in drain(worker)]

    assert "cancelled" in kinds
    assert kinds[-1] == "done"
    assert len(done) < 100  # It really did stop early.


def test_cancelling_raises_inside_the_job():
    worker = Worker()
    worker.cancel()
    with pytest.raises(Cancelled):
        worker.raise_if_cancelled()


def test_a_new_job_clears_the_previous_cancel():
    """Otherwise one cancel would poison every job after it."""
    worker = Worker()
    worker.cancel()
    assert worker.cancelled

    worker.start(lambda: worker.send("log", "fresh"))
    kinds = [m.kind for m in drain(worker)]
    assert kinds == ["log", "done"]
    assert not worker.cancelled


def test_drain_respects_its_limit():
    worker = Worker()
    for i in range(10):
        worker.send("log", i)
    assert len(worker.drain(limit=4)) == 4
    assert len(worker.drain()) == 6
