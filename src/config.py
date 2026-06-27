"""
config.py – Persistent application configuration.

Stores:
  - minecraft_dir        : Path to the .minecraft folder
  - last_version         : Last successfully synced manifest version (optional)
  - base_url             : Remote raw-file base URL (GitHub or any CDN)
  - parallel_downloads   : Number of simultaneous downloads (default 4)
  - language             : UI locale code, e.g. "en" or "es" (default "en")
  - sync_resourcepacks   : Whether to download (but never delete) resourcepacks (default False)
  - sync_shaderpacks     : Whether to download (but never delete) shaderpacks (default False)

The config file (mupdater_config.json) is always written next to the
running executable.  Path resolution is handled by src.paths so it works
correctly under both plain Python and Nuitka/PyInstaller compiled builds.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

try:
    import orjson as _json  # type: ignore[import]

    def _dumps(obj: Any) -> bytes:
        return _json.dumps(obj, option=_json.OPT_INDENT_2)

    def _loads(data: bytes | str) -> Any:
        return _json.loads(data)

except ModuleNotFoundError:
    import json as _json  # type: ignore[no-redef]

    def _dumps(obj: Any) -> bytes:
        return _json.dumps(obj, indent=2, ensure_ascii=False).encode("utf-8")

    def _loads(data: bytes | str) -> Any:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return _json.loads(data)


from src.logger import get_logger

log = get_logger("config")

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

#: Public raw-content base URL for the modpack repository.
#: Change this to your own GitHub repo (or R2 / S3 bucket, etc.).
DEFAULT_BASE_URL = (
    "https://raw.githubusercontent.com/AxelinS/minecraftMods/main/modpack/pack"
)

DEFAULT_PARALLEL_DOWNLOADS = 4
DEFAULT_LANGUAGE = "en"


def _config_path() -> Path:
    """Return the absolute path to the config file in the user data directory."""
    from src.paths import config_path
    return config_path()


def _default_minecraft_dir() -> Path | None:
    """Return the default .minecraft path for the current platform."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidate = Path(appdata) / ".minecraft"
            if candidate.is_dir():
                return candidate
    elif sys.platform == "darwin":
        candidate = Path.home() / "Library" / "Application Support" / "minecraft"
        if candidate.is_dir():
            return candidate
    else:
        # Linux / other
        candidate = Path.home() / ".minecraft"
        if candidate.is_dir():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Config dataclass-like wrapper
# ---------------------------------------------------------------------------

class AppConfig:
    """Thin wrapper around the JSON config file."""

    def __init__(self) -> None:
        self.minecraft_dir: Path | None = None
        self.last_version: str | None = None
        self.base_url: str = DEFAULT_BASE_URL
        self.parallel_downloads: int = DEFAULT_PARALLEL_DOWNLOADS
        self.language: str = DEFAULT_LANGUAGE
        self.sync_resourcepacks: bool = False
        self.sync_shaderpacks: bool = False
        self._path: Path = _config_path()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> "AppConfig":
        """Load config from disk. Missing file → use defaults."""
        if not self._path.exists():
            log.debug("No config file found at %s; creating with defaults.", self._path)
            self.minecraft_dir = _default_minecraft_dir()
            self.save()
            return self

        try:
            raw = self._path.read_bytes()
            data: dict[str, Any] = _loads(raw)
        except Exception as exc:
            log.warning("Failed to read config (%s); using defaults.", exc)
            self.minecraft_dir = _default_minecraft_dir()
            return self

        mc = data.get("minecraft_dir")
        self.minecraft_dir = Path(mc) if mc else _default_minecraft_dir()
        self.last_version = data.get("last_version")
        self.base_url = data.get("base_url", DEFAULT_BASE_URL)
        self.parallel_downloads = int(
            data.get("parallel_downloads", DEFAULT_PARALLEL_DOWNLOADS)
        )
        self.language = data.get("language", DEFAULT_LANGUAGE)
        self.sync_resourcepacks = bool(data.get("sync_resourcepacks", False))
        self.sync_shaderpacks = bool(data.get("sync_shaderpacks", False))
        log.debug("Config loaded from %s", self._path)
        return self

    def save(self) -> None:
        """Persist the current configuration to disk."""
        data: dict[str, Any] = {
            "minecraft_dir": str(self.minecraft_dir) if self.minecraft_dir else None,
            "last_version": self.last_version,
            "base_url": self.base_url,
            "parallel_downloads": self.parallel_downloads,
            "language": self.language,
            "sync_resourcepacks": self.sync_resourcepacks,
            "sync_shaderpacks": self.sync_shaderpacks,
        }
        try:
            self._path.write_bytes(_dumps(data))
            log.debug("Config saved to %s", self._path)
        except OSError as exc:
            log.error("Could not save config: %s", exc)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def minecraft_dir_or_raise(self) -> Path:
        if not self.minecraft_dir or not self.minecraft_dir.is_dir():
            # Import here to avoid circular imports at module level
            from src.i18n import t
            raise ValueError(t("error.dir_not_set"))
        return self.minecraft_dir
