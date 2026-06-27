"""
hashing.py – SHA-256 utilities.

Provides:
  - file_sha256(path)  : hash an existing file from disk
  - bytes_sha256(data) : hash an in-memory bytes object
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1024 * 256  # 256 KiB read buffer


def file_sha256(path: Path) -> str:
    """Return the lowercase hex SHA-256 digest of *path*.

    Reads the file in chunks so large mods don't spike memory.
    """
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def bytes_sha256(data: bytes) -> str:
    """Return the lowercase hex SHA-256 digest of *data*."""
    return hashlib.sha256(data).hexdigest()
