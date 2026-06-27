"""
logger.py – Centralised logging setup.

Writes to both the console (INFO+) and a rotating file (DEBUG+).
The log file sits next to the running executable / script so it is
always easy to find for support purposes.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _log_path() -> Path:
    """Return the absolute path to the log file next to the executable."""
    from src.paths import exe_dir, LOG_FILE
    return exe_dir() / LOG_FILE


def setup_logging(level: int = logging.DEBUG) -> logging.Logger:
    """Configure and return the root application logger."""
    logger = logging.getLogger("modpack_updater")
    if logger.handlers:
        # Already configured (e.g. called twice during tests)
        return logger

    logger.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Console handler (INFO and above) ---
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    logger.addHandler(console)

    # --- Rotating file handler (DEBUG and above, 5 MB × 3 backups) ---
    try:
        file_handler = RotatingFileHandler(
            _log_path(),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError as exc:
        logger.warning("Could not open log file: %s", exc)

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under the application namespace."""
    root = "modpack_updater"
    if name:
        return logging.getLogger(f"{root}.{name}")
    return logging.getLogger(root)
