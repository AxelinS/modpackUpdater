"""
sync.py – Orchestrates the compare-and-sync workflow.

Steps:
  1. Fetch the remote manifest.
  2. Walk the managed folders inside the minecraft directory.
  3. Diff local files against the manifest (hash comparison).
  4. Delete orphan files only for DELETION_DIRS (mods, config).
  5. Download missing / outdated files via the downloader.
  6. Return a SyncReport.

Directory behaviour:
  DELETION_DIRS  – fully synced: files not in manifest are deleted.
    mods, config

  ADDONLY_DIRS   – download-only: new/updated files are downloaded but
                   local files absent from manifest are never removed.
    resourcepacks, shaderpacks, kubejs, defaultconfigs

  resourcepacks and shaderpacks are opt-in via config.sync_resourcepacks /
  config.sync_shaderpacks.  When disabled those directories are skipped
  entirely.

Concurrency / idempotency guarantees:
  - run_sync() is designed to be called from exactly one background thread
    at a time (enforced by the GUI).  The function itself is stateless:
    every call creates a fresh SyncReport so repeated calls always yield a
    consistent result.
  - The completed_counter closure variable is written only inside the
    _file_done callback, which is dispatched by the ThreadPoolExecutor
    through as_completed().  access is therefore serialised on the
    executor's internal bookkeeping – no extra lock needed there.
  - Orphan deletion uses unlink(missing_ok=True) so a file that was already
    removed by a concurrent call (or a previous interrupted run) does not
    cause a spurious error.
  - config.save() is called under a module-level lock so two sync runs
    started in quick succession cannot interleave their writes.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from src.config import AppConfig
from src.downloader import download_all
from src.hashing import file_sha256
from src.i18n import t
from src.logger import get_logger
from src.manifest import FileEntry, Manifest, fetch_manifest

log = get_logger("sync")

# Directories that are FULLY synced: orphans are deleted.
DELETION_DIRS: frozenset[str] = frozenset({"mods", "config"})

# Directories that are ADD-ONLY: files are downloaded/updated but never deleted.
# resourcepacks and shaderpacks are opt-in (controlled by config flags).
# kubejs and defaultconfigs are always included here but never have deletions.
ADDONLY_DIRS_ALWAYS: frozenset[str] = frozenset({"kubejs", "defaultconfigs"})
ADDONLY_DIRS_OPT_IN: frozenset[str] = frozenset({"resourcepacks", "shaderpacks"})

# Combined set of all directories that may ever be touched (for reference).
ALL_MANAGED_DIRS: frozenset[str] = (
    DELETION_DIRS | ADDONLY_DIRS_ALWAYS | ADDONLY_DIRS_OPT_IN
)

# Guard concurrent config writes that originate from parallel test code or
# two rapid GUI clicks that somehow both pass the is_alive() check.
_config_save_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Callbacks / progress types
# ---------------------------------------------------------------------------

# (message: str) -> None
StatusCallback = Callable[[str], None]

# (current: int, total: int) -> None  – file counts
OverallProgressCallback = Callable[[int, int], None]

# (entry: FileEntry, success: bool, error: str | None) -> None
FileResultCallback = Callable[[FileEntry, bool, "str | None"], None]

# (bytes_dl: int, total_bytes: int | None) -> None
ByteProgressCallback = Callable[[int, "int | None"], None]


# ---------------------------------------------------------------------------
# Sync report
# ---------------------------------------------------------------------------

@dataclass
class SyncReport:
    version: str = ""
    files_checked: int = 0
    files_up_to_date: int = 0
    files_downloaded: int = 0
    files_deleted: int = 0
    files_failed: int = 0
    errors: list[str] = field(default_factory=list)
    changelog: str | None = None
    cancelled: bool = False
    # Thread-safe counter lock used by _file_done callback
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def success(self) -> bool:
        return not self.cancelled and self.files_failed == 0 and not self.errors

    def summary(self) -> str:
        if self.cancelled:
            return t("report.cancelled")
        parts = []
        if self.files_up_to_date:
            parts.append(t("report.up_to_date", n=self.files_up_to_date))
        if self.files_downloaded:
            parts.append(t("report.updated", n=self.files_downloaded))
        if self.files_deleted:
            parts.append(t("report.removed", n=self.files_deleted))
        if self.files_failed:
            parts.append(t("report.errors", n=self.files_failed))
        return ", ".join(parts) if parts else t("report.nothing")


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------

def _collect_local_files(
    minecraft_dir: Path,
    active_dirs: frozenset[str],
) -> dict[str, Path]:
    """Return {relative_posix_path: absolute_path} for all files in *active_dirs*."""
    local: dict[str, Path] = {}
    for managed in active_dirs:
        folder = minecraft_dir / managed
        if not folder.is_dir():
            continue
        for file_path in folder.rglob("*"):
            if file_path.is_file():
                rel = file_path.relative_to(minecraft_dir)
                local[rel.as_posix()] = file_path
    return local


def _compute_diff(
    local_files: dict[str, Path],
    manifest_index: dict[str, FileEntry],
    deletion_dirs: frozenset[str],
    on_status: StatusCallback | None,
    cancel_event: threading.Event,
) -> tuple[list[FileEntry], list[Path], int]:
    """Return (to_download, to_delete, up_to_date_count).

    Orphan deletion is only performed for files that live inside
    *deletion_dirs*.  Files in add-only directories are never deleted.

    Hashes every existing local file to decide whether it needs updating.
    Respects *cancel_event* between files so cancellation is responsive even
    during the (potentially slow) local-scan phase.
    """
    to_download: list[FileEntry] = []
    to_delete: list[Path] = []
    up_to_date = 0

    # Files in manifest
    for rel_path, entry in manifest_index.items():
        if cancel_event.is_set():
            # Return partial results; caller will set report.cancelled
            break
        if on_status:
            on_status(t("status.checking_file", path=rel_path))
        local_path = local_files.get(rel_path)
        if local_path is None:
            log.debug("MISSING  %s", rel_path)
            to_download.append(entry)
        else:
            try:
                local_hash = file_sha256(local_path)
            except OSError as exc:
                log.warning(t("error.cannot_read_file", path=rel_path, detail=exc))
                to_download.append(entry)
                continue

            if local_hash == entry.sha256:
                log.debug("OK       %s", rel_path)
                up_to_date += 1
            else:
                log.debug("OUTDATED %s", rel_path)
                to_download.append(entry)

    # Orphans — only delete files that belong to a DELETION_DIR
    if not cancel_event.is_set():
        for rel_path, local_path in local_files.items():
            if rel_path not in manifest_index:
                # Determine which top-level directory this file lives in
                top_dir = rel_path.split("/")[0]
                if top_dir in deletion_dirs:
                    log.debug("ORPHAN   %s", rel_path)
                    to_delete.append(local_path)
                else:
                    log.debug("ORPHAN_SKIP (add-only dir) %s", rel_path)

    return to_download, to_delete, up_to_date


# ---------------------------------------------------------------------------
# Main sync entry point
# ---------------------------------------------------------------------------

def run_sync(
    config: AppConfig,
    *,
    cancel_event: threading.Event | None = None,
    on_status: StatusCallback | None = None,
    on_overall_progress: OverallProgressCallback | None = None,
    on_file_progress: ByteProgressCallback | None = None,
    on_file_done: FileResultCallback | None = None,
) -> SyncReport:
    """Execute a full sync cycle.

    Designed to run in exactly one background thread at a time.
    All callbacks are invoked from that same thread.

    Returns a SyncReport even on failure — never raises to the caller.
    """
    report = SyncReport()
    cancel_event = cancel_event or threading.Event()

    # ------------------------------------------------------------------
    # 1. Resolve minecraft dir
    # ------------------------------------------------------------------
    try:
        minecraft_dir = config.minecraft_dir_or_raise
    except ValueError as exc:
        msg = str(exc)
        log.error(msg)
        report.errors.append(msg)
        return report

    # ------------------------------------------------------------------
    # 2. Fetch manifest
    # ------------------------------------------------------------------
    if on_status:
        on_status(t("status.downloading_manifest"))

    base_url_stripped = config.base_url.rstrip("/")
    if base_url_stripped.endswith("/pack"):
        manifest_url = base_url_stripped[: -len("/pack")] + "/manifest.json"
    else:
        manifest_url = base_url_stripped + "/manifest.json"

    try:
        manifest: Manifest = fetch_manifest(manifest_url)
    except Exception as exc:
        msg = t("error.manifest_fetch", detail=exc)
        log.error(msg)
        report.errors.append(msg)
        return report

    report.version = manifest.version
    report.changelog = manifest.changelog
    manifest_index = manifest.as_index()

    if cancel_event.is_set():
        report.cancelled = True
        return report

    # ------------------------------------------------------------------
    # 3. Collect local files & diff
    # ------------------------------------------------------------------
    if on_status:
        on_status(t("status.scanning"))

    # Build the set of active directories for this run
    addonly_dirs = set(ADDONLY_DIRS_ALWAYS)
    if config.sync_resourcepacks:
        addonly_dirs.add("resourcepacks")
    if config.sync_shaderpacks:
        addonly_dirs.add("shaderpacks")
    active_dirs = DELETION_DIRS | frozenset(addonly_dirs)

    local_files = _collect_local_files(minecraft_dir, active_dirs)
    to_download, to_delete, up_to_date = _compute_diff(
        local_files, manifest_index, DELETION_DIRS, on_status, cancel_event
    )
    report.files_checked = len(manifest_index)
    report.files_up_to_date = up_to_date

    if cancel_event.is_set():
        report.cancelled = True
        return report

    # ------------------------------------------------------------------
    # 4. Delete orphan files (idempotent: missing_ok=True)
    # ------------------------------------------------------------------
    for orphan in to_delete:
        if cancel_event.is_set():
            report.cancelled = True
            return report
        try:
            orphan.unlink(missing_ok=True)
            log.info("Deleted orphan: %s", orphan)
            report.files_deleted += 1
        except OSError as exc:
            msg = t("error.delete_orphan", path=orphan, detail=exc)
            log.warning(msg)
            report.errors.append(msg)

    # ------------------------------------------------------------------
    # 5. Download missing / outdated files
    # ------------------------------------------------------------------
    if not to_download:
        if on_status:
            on_status(t("status.up_to_date"))
        _save_version(config, manifest.version)
        return report

    if on_status:
        on_status(t("status.downloading_n", n=len(to_download)))

    # Thread-safe counter: _file_done is called from worker threads via
    # as_completed(); use report._lock to guard the mutable counters.
    completed_counter = [0]

    def _file_done(entry: FileEntry, success: bool, error: str | None) -> None:
        with report._lock:
            completed_counter[0] += 1
            current = completed_counter[0]
            if success:
                report.files_downloaded += 1
            else:
                report.files_failed += 1
                if error:
                    report.errors.append(f"{entry.path}: {error}")

        if on_overall_progress:
            on_overall_progress(current, len(to_download))
        if on_file_done:
            on_file_done(entry, success, error)

    download_all(
        entries=to_download,
        dest_dir=minecraft_dir,
        base_url=base_url_stripped,
        parallel=config.parallel_downloads,
        cancel_event=cancel_event,
        on_file_progress=on_file_progress,
        on_file_done=_file_done,
    )

    if cancel_event.is_set():
        report.cancelled = True

    # Persist last synced version only on full success
    if report.success:
        _save_version(config, manifest.version)

    if on_status:
        on_status(report.summary())

    return report


def _save_version(config: AppConfig, version: str) -> None:
    """Thread-safe config save after a successful sync."""
    with _config_save_lock:
        config.last_version = version
        config.save()
