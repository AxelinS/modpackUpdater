"""
manifest.py – Manifest download and parsing.

The remote manifest.json schema:

    {
        "version": "1.0.0",
        "files": [
            {
                "path":   "mods/create.jar",
                "sha256": "<hex>",
                "size":   123456
            }
        ],
        "changelog": "optional text"   # optional
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

try:
    import orjson as _json  # type: ignore[import]

    def _loads(data: bytes | str) -> Any:
        return _json.loads(data)

except ModuleNotFoundError:
    import json as _json  # type: ignore[no-redef]

    def _loads(data: bytes | str) -> Any:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return _json.loads(data)


import httpx

from src.logger import get_logger

log = get_logger("manifest")

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FileEntry:
    """A single file described in the manifest."""

    path: str       # relative, forward-slash separated  e.g. "mods/create.jar"
    sha256: str     # lowercase hex
    size: int       # bytes

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FileEntry":
        return cls(
            path=str(PurePosixPath(data["path"])),
            sha256=data["sha256"].lower(),
            size=int(data["size"]),
        )


@dataclass
class Manifest:
    """The parsed remote manifest."""

    version: str
    files: list[FileEntry] = field(default_factory=list)
    changelog: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Manifest":
        entries = [FileEntry.from_dict(f) for f in data.get("files", [])]
        return cls(
            version=str(data.get("version", "unknown")),
            files=entries,
            changelog=data.get("changelog"),
        )

    def as_index(self) -> dict[str, FileEntry]:
        """Return {relative_path: FileEntry} for O(1) lookup."""
        return {e.path: e for e in self.files}


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

MANIFEST_TIMEOUT = 30  # seconds


def fetch_manifest(manifest_url: str) -> Manifest:
    """Download and parse the remote manifest.

    Raises:
        httpx.HTTPError      – network / HTTP error
        ValueError           – invalid JSON or schema
    """
    log.info("Fetching manifest from %s", manifest_url)
    with httpx.Client(follow_redirects=True, timeout=MANIFEST_TIMEOUT) as client:
        response = client.get(manifest_url)
        response.raise_for_status()

    try:
        data: dict[str, Any] = _loads(response.content)
    except Exception as exc:
        raise ValueError(f"Invalid manifest JSON: {exc}") from exc

    if "files" not in data:
        raise ValueError("Manifest is missing required 'files' key.")

    manifest = Manifest.from_dict(data)
    log.info(
        "Manifest v%s loaded: %d file(s).",
        manifest.version,
        len(manifest.files),
    )
    return manifest
