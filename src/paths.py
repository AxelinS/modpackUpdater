"""
paths.py – Runtime path resolution for both dev and compiled (Nuitka/PyInstaller) modes.

Rule:
  - When running as a compiled binary (Nuitka sets sys.frozen = True, or the
    __compiled__ dunder is present; PyInstaller also sets sys.frozen):
      base dir = directory that contains the executable
  - When running from source:
      base dir = project root  (parent of the src/ package)

All runtime-generated files (config, log) must live in the base dir so that
they are always writable and always next to the executable.  Using __file__
inside a Nuitka bundle is unreliable because it can point into a temp
extraction directory instead of the actual install location.
"""

from __future__ import annotations

import sys
from pathlib import Path


def exe_dir() -> Path:
    """Return the directory that should contain runtime-generated files.

    Resolves correctly for:
      - Plain ``python main.py``   → project root
      - Nuitka onefile/standalone  → directory containing the .exe
      - PyInstaller onefile        → directory containing the .exe
    """
    # Nuitka compiled: __compiled__ is injected into the module namespace.
    # PyInstaller compiled: sys.frozen is set to True.
    # Both set sys.executable to the actual binary path.
    if getattr(sys, "frozen", False) or "__compiled__" in dir():
        return Path(sys.executable).resolve().parent

    # Dev / source mode: go up from src/paths.py → src/ → project root
    return Path(__file__).resolve().parent.parent


CONFIG_FILE = "mupdater_config.json"
LOG_FILE    = "mupdater.log"
