"""
downloader.py – Single-file and parallel download engine.

Features:
  - Streaming download with per-chunk progress callbacks
  - SHA-256 verification after each download
  - Configurable retries with back-off
  - Cancellation via threading.Event
  - Parallel downloads via ThreadPoolExecutor

Concurrency / idempotency notes:
  - Every download writes to a private *.tmp file and atomically renames it
    to the final destination only after a successful hash check.  If two
    workers were ever asked to download the same path (which run_sync never
    does) the last rename wins and the result is still a valid file.
  - Stale *.tmp files left from a previous crashed/cancelled run are cleaned
    up at the start of each attempt so they never accumulate.
  - The shared httpx.Client is thread-safe for concurrent requests; each
    worker opens its own stream context so there is no request interleaving.
  - DownloadBatch.record() is protected by an internal Lock.
  - The on_progress callback is invoked from individual worker threads.
    The GUI always marshals these to the main thread via self.after().
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

from src.hashing import bytes_sha256
from src.logger import get_logger
from src.manifest import FileEntry

log = get_logger("downloader")

# ---------------------------------------------------------------------------
# Types / callbacks
# ---------------------------------------------------------------------------

# Signature: (bytes_downloaded: int, total_bytes: int | None) -> None
ProgressCallback = Callable[[int, int | None], None]

# Signature: (entry: FileEntry, success: bool, error: str | None) -> None
FileResultCallback = Callable[["FileEntry", bool, "str | None"], None]

_RETRY_DELAYS = (1.0, 3.0, 7.0)   # seconds between successive retries
_DOWNLOAD_TIMEOUT = httpx.Timeout(connect=15, read=60, write=10, pool=5)
_CHUNK_SIZE = 1024 * 64  # 64 KiB


# ---------------------------------------------------------------------------
# Download result
# ---------------------------------------------------------------------------

@dataclass
class DownloadResult:
    entry: FileEntry
    success: bool
    error: str | None = None
    bytes_downloaded: int = 0
    elapsed: float = 0.0


# ---------------------------------------------------------------------------
# Core download function
# ---------------------------------------------------------------------------

def download_file(
    entry: FileEntry,
    dest_dir: Path,
    base_url: str,
    *,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
    client: httpx.Client | None = None,
) -> DownloadResult:
    """Download *entry* into *dest_dir* and verify its SHA-256.

    Parameters
    ----------
    entry:
        The manifest file entry to download.
    dest_dir:
        Root directory where files are written (preserving *entry.path* structure).
    base_url:
        Raw-file base URL, **without** a trailing slash.
    cancel_event:
        If set, the download is aborted and a cancelled result is returned.
    on_progress:
        Called repeatedly with ``(bytes_downloaded, total_or_None)``.
    client:
        An existing ``httpx.Client`` to reuse; one is created if *None*.
    """
    url = f"{base_url.rstrip('/')}/{entry.path}"
    dest = dest_dir / Path(entry.path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Clean up any stale temp file from a previous interrupted run
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    if tmp_dest.exists():
        try:
            tmp_dest.unlink()
            log.debug("Removed stale temp file: %s", tmp_dest)
        except OSError:
            pass  # non-fatal; _attempt_download will overwrite it

    t0 = time.monotonic()

    for attempt, delay in enumerate((*_RETRY_DELAYS, None), start=1):
        if cancel_event and cancel_event.is_set():
            log.info("Download cancelled before attempt %d: %s", attempt, entry.path)
            return DownloadResult(entry=entry, success=False, error="Cancelled")

        try:
            result = _attempt_download(
                entry=entry,
                url=url,
                dest=dest,
                tmp_dest=tmp_dest,
                cancel_event=cancel_event,
                on_progress=on_progress,
                client=client,
            )
            result.elapsed = time.monotonic() - t0
            return result

        except Exception as exc:
            log.warning("Attempt %d failed for %s: %s", attempt, entry.path, exc)
            # Ensure no partial .tmp is left between retries
            if tmp_dest.exists():
                try:
                    tmp_dest.unlink()
                except OSError:
                    pass
            if delay is None:
                # All retries exhausted
                elapsed = time.monotonic() - t0
                return DownloadResult(
                    entry=entry,
                    success=False,
                    error=str(exc),
                    elapsed=elapsed,
                )
            if cancel_event:
                cancelled = cancel_event.wait(timeout=delay)
                if cancelled:
                    return DownloadResult(entry=entry, success=False, error="Cancelled")
            else:
                time.sleep(delay)

    # Unreachable, but satisfies the type checker
    return DownloadResult(entry=entry, success=False, error="Unknown error")


def _attempt_download(
    entry: FileEntry,
    url: str,
    dest: Path,
    tmp_dest: Path,
    *,
    cancel_event: threading.Event | None,
    on_progress: ProgressCallback | None,
    client: httpx.Client | None,
) -> DownloadResult:
    """Single download attempt; raises on any error."""
    close_client = False

    if client is None:
        client = httpx.Client(follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT)
        close_client = True

    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            total: int | None = (
                int(response.headers["content-length"])
                if "content-length" in response.headers
                else None
            )
            received = 0
            chunks: list[bytes] = []

            for chunk in response.iter_bytes(chunk_size=_CHUNK_SIZE):
                if cancel_event and cancel_event.is_set():
                    raise RuntimeError("Cancelled")
                chunks.append(chunk)
                received += len(chunk)
                if on_progress:
                    on_progress(received, total)

        data = b"".join(chunks)
    finally:
        if close_client:
            client.close()

    # Verify hash — on mismatch raise so the retry loop can handle it;
    # the caller cleans up the tmp file between retries.
    actual_hash = bytes_sha256(data)
    if actual_hash != entry.sha256:
        log.error(
            "Hash mismatch for %s: expected %s got %s",
            entry.path,
            entry.sha256,
            actual_hash,
        )
        raise ValueError(
            f"SHA-256 mismatch for {entry.path}: "
            f"expected {entry.sha256[:12]}… got {actual_hash[:12]}…"
        )

    # Atomic-ish write: write to .tmp then rename to final destination.
    # If dest already has a valid file (e.g. a concurrent worker put it
    # there), replace() overwrites it with an equally valid copy — idempotent.
    tmp_dest.write_bytes(data)
    tmp_dest.replace(dest)

    log.info("Downloaded %s (%d bytes)", entry.path, received)
    return DownloadResult(entry=entry, success=True, bytes_downloaded=received)


# ---------------------------------------------------------------------------
# Parallel download engine
# ---------------------------------------------------------------------------

@dataclass
class DownloadBatch:
    """Tracks the aggregate state of a multi-file download job."""

    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    total_bytes: int = 0
    downloaded_bytes: int = 0
    results: list[DownloadResult] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, result: DownloadResult) -> None:
        with self._lock:
            self.results.append(result)
            self.completed_files += 1
            if result.success:
                self.downloaded_bytes += result.bytes_downloaded
            else:
                self.failed_files += 1


def download_all(
    entries: list[FileEntry],
    dest_dir: Path,
    base_url: str,
    *,
    parallel: int = 4,
    cancel_event: threading.Event | None = None,
    on_file_progress: ProgressCallback | None = None,
    on_file_done: FileResultCallback | None = None,
) -> DownloadBatch:
    """Download *entries* in parallel.

    Parameters
    ----------
    entries:
        Files to download.
    dest_dir:
        Root of the managed minecraft folder.
    base_url:
        Raw-file base URL.
    parallel:
        Number of concurrent downloads (clamped to at least 1).
    cancel_event:
        Shared cancellation flag.
    on_file_progress:
        Progress callback forwarded to each individual download.
        Called from worker threads; GUI must marshal to the main thread.
    on_file_done:
        Called once per completed file with ``(entry, success, error_or_None)``.
        Also called from worker threads via as_completed().
    """
    batch = DownloadBatch(
        total_files=len(entries),
        total_bytes=sum(e.size for e in entries),
    )
    if not entries:
        return batch

    parallel = max(1, parallel)

    # One shared httpx.Client for connection reuse.
    # httpx.Client is documented as thread-safe for concurrent requests.
    shared_client = httpx.Client(follow_redirects=True, timeout=_DOWNLOAD_TIMEOUT)

    try:
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            futures: dict[Future[DownloadResult], FileEntry] = {
                pool.submit(
                    download_file,
                    entry,
                    dest_dir,
                    base_url,
                    cancel_event=cancel_event,
                    on_progress=on_file_progress,
                    client=shared_client,
                ): entry
                for entry in entries
            }

            for future in as_completed(futures):
                try:
                    result: DownloadResult = future.result()
                except Exception as exc:
                    # Should not happen — download_file catches all errors —
                    # but guard against unexpected exceptions from the executor.
                    entry = futures[future]
                    log.error("Unexpected executor error for %s: %s", entry.path, exc)
                    result = DownloadResult(entry=entry, success=False, error=str(exc))

                batch.record(result)
                if on_file_done:
                    on_file_done(result.entry, result.success, result.error)
    finally:
        shared_client.close()

    return batch
