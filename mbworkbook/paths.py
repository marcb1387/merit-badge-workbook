"""Where this app keeps its settings and its cache, per platform.

Windows has its own conventions and they are not the XDG ones: roaming settings
belong in ``%APPDATA%``, and a re-downloadable cache belongs in
``%LOCALAPPDATA%`` so it neither roams between machines nor counts against a
profile quota. Earlier versions wrote ``~/.config`` and ``~/.cache`` everywhere,
which on Windows just litters the user profile with dotfolders that nothing
cleans up, so :func:`migrate_legacy_dirs` moves them once.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

APP_NAME = "MeritBadgeWorkbook"
POSIX_NAME = "merit-badge-workbook"

# Honoured on every platform, and the escape hatch the tests use.
CONFIG_ENV = "MBW_CONFIG_DIR"
CACHE_ENV = "MBW_CACHE_DIR"


def _windows_dir(env_var: str, fallback: Path, *subdirs: str) -> Path:
    base = os.environ.get(env_var)
    root = Path(base) if base else fallback
    return root.joinpath(APP_NAME, *subdirs)


def config_dir() -> Path:
    """Directory for settings the user would miss if it vanished."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        return _windows_dir("APPDATA", Path.home() / "AppData" / "Roaming")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_CONFIG_HOME")
    return (Path(xdg) if xdg else Path.home() / ".config") / POSIX_NAME


def cache_dir() -> Path:
    """Directory for anything we could download again."""
    override = os.environ.get(CACHE_ENV)
    if override:
        return Path(override)
    if sys.platform == "win32":
        return _windows_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local", "Cache")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / APP_NAME
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / POSIX_NAME


def settings_path() -> Path:
    return config_dir() / "gui.json"


LEGACY_CONFIG = Path.home() / ".config" / POSIX_NAME
LEGACY_CACHE = Path.home() / ".cache" / POSIX_NAME


def migrate_legacy_dirs() -> list[tuple[Path, Path]]:
    """Move pre-1.1 XDG directories to the platform-correct ones.

    Only runs when the old directory exists and the new one does not, so it
    cannot clobber newer settings. Returns what it moved, for logging.
    """
    moved: list[tuple[Path, Path]] = []
    if os.environ.get(CONFIG_ENV) or os.environ.get(CACHE_ENV):
        return moved  # An explicit override means the caller knows better.

    for legacy, current in ((LEGACY_CONFIG, config_dir()), (LEGACY_CACHE, cache_dir())):
        if legacy == current or not legacy.is_dir() or current.exists():
            continue
        try:
            current.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(current))
            moved.append((legacy, current))
        except OSError:
            # A failed migration is not worth crashing over; we just re-fetch.
            pass
    return moved
