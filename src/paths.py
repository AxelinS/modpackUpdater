"""
paths.py – Runtime path resolution for both dev and compiled (Nuitka/PyInstaller) modes.

Config and log files are stored in a per-user application-data directory so
they are always writable, survive across .exe updates or moves, and are
completely independent of where the binary lives:

  Windows  : %APPDATA%\\ModPackUpdater\\          (C:\\Users\\<user>\\AppData\\Roaming\\ModPackUpdater)
  macOS    : ~/Library/Application Support/ModPackUpdater/
  Linux    : ~/.config/ModPackUpdater/

The directory is created automatically on first use.

Dev / source mode uses the same user-data directory so behaviour is identical
when iterating without recompiling.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIRNAME = "ModPackUpdater"
CONFIG_FILE = "mupdater_config.json"
LOG_FILE    = "mupdater.log"


def app_data_dir() -> Path:
    """Return the per-user data directory for the application.

    Creates the directory (and any parents) if it does not yet exist.

    Platform resolution:
      Windows : %APPDATA%\\ModPackUpdater
      macOS   : ~/Library/Application Support/ModPackUpdater
      Linux   : $XDG_CONFIG_HOME/ModPackUpdater  (fallback: ~/.config/ModPackUpdater)
    """
    if sys.platform == "win32":
        # %APPDATA% is guaranteed on every Windows installation; fall back to
        # the home directory only if the env-var is somehow missing.
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        # Respect XDG on Linux / BSD
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"

    directory = base / APP_DIRNAME
    directory.mkdir(parents=True, exist_ok=True)
    return directory


# ---------------------------------------------------------------------------
# Convenience helpers used by config.py and logger.py
# ---------------------------------------------------------------------------

def config_path() -> Path:
    """Return the absolute path to the config file."""
    return app_data_dir() / CONFIG_FILE


def log_path() -> Path:
    """Return the absolute path to the log file."""
    return app_data_dir() / LOG_FILE


# ---------------------------------------------------------------------------
# Kept for backward-compatibility with any code that still calls exe_dir().
# Points to the same app_data_dir() so old call sites continue to work.
# ---------------------------------------------------------------------------

def exe_dir() -> Path:
    """Deprecated alias for app_data_dir(). Use app_data_dir() for new code."""
    return app_data_dir()
