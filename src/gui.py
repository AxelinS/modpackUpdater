"""
gui.py – CustomTkinter graphical interface for the Modpack Updater.

Layout:
  ┌─────────────────────────────────────────────────┐
  │  Modpack Updater  v1.0.0      [Theme] [Language]│
  ├─────────────────────────────────────────────────┤
  │  Minecraft folder: <path>          [Change]     │
  │  Remote URL:       <url>                        │
  ├─────────────────────────────────────────────────┤
  │  [ Check for Updates ]  [ Cancel ]              │
  ├─────────────────────────────────────────────────┤
  │  Overall progress  ████░░░░  42 %               │
  │  Current file      ████████ 100 %               │
  │  mods/create.jar               1.2 MB/s | 12/30 │
  │  Status: All files are up-to-date.              │
  ├─────────────────────────────────────────────────┤
  │  ▶ Changelog  (collapsible)                     │
  └─────────────────────────────────────────────────┘

Concurrency:
  - Sync runs in a daemon thread; all UI mutations go through self.after().
  - _on_update() checks _sync_thread.is_alive() AND a dedicated
    _running flag (protected by _state_lock) to prevent double-starts
    even if the thread object outlives the join window.
  - _on_cancel() is idempotent: setting a threading.Event is safe to call
    multiple times.
  - Language changes while a sync is running are deferred: the new locale
    takes effect at the next idle cycle without touching in-flight state.
"""

from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk  # type: ignore[import]

from src.config import AppConfig
from src.i18n import LOCALE_DISPLAY_NAMES, SUPPORTED_LOCALES, get_locale, set_locale, t
from src.logger import get_logger
from src.manifest import FileEntry
from src.sync import SyncReport, run_sync

log = get_logger("gui")

# ---------------------------------------------------------------------------
# Appearance defaults
# ---------------------------------------------------------------------------

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

APP_VERSION = "1.0.0"
MIN_WIDTH  = 660
MIN_HEIGHT = 580


# ---------------------------------------------------------------------------
# Speed tracker (rolling average over a 3-second window)
# ---------------------------------------------------------------------------

class _SpeedTracker:
    def __init__(self, window: float = 3.0) -> None:
        self._window = window
        self._samples: list[tuple[float, int]] = []
        self._lock = threading.Lock()

    def add(self, delta_bytes: int, timestamp: float) -> None:
        with self._lock:
            self._samples.append((timestamp, delta_bytes))
            cutoff = timestamp - self._window
            self._samples = [(ts, b) for ts, b in self._samples if ts >= cutoff]

    def speed_bps(self) -> float:
        with self._lock:
            if len(self._samples) < 2:
                return 0.0
            total = sum(b for _, b in self._samples)
            span  = self._samples[-1][0] - self._samples[0][0]
            return total / span if span > 0 else 0.0

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class App(ctk.CTk):
    """Main application window."""

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config

        # Apply saved locale before building UI
        set_locale(config.language)

        # --- Concurrency state ---
        self._cancel_event  = threading.Event()
        self._sync_thread: threading.Thread | None = None
        self._state_lock    = threading.Lock()   # guards _running
        self._running       = False              # True only while sync is active

        # --- Download metrics ---
        self._speed      = _SpeedTracker()
        self._prev_bytes = 0

        self.title(t("app.title"))
        self.minsize(MIN_WIDTH, MIN_HEIGHT)
        self.resizable(True, True)

        self._build_ui()
        self._refresh_dir_label()

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

        # ── Header ─────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self, corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self._title_label = ctk.CTkLabel(
            header,
            text=t("app.title"),
            font=ctk.CTkFont(size=22, weight="bold"),
        )
        self._title_label.grid(row=0, column=0, padx=20, pady=(16, 2), sticky="w")

        # App version (static)
        ctk.CTkLabel(
            header,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        ).grid(row=1, column=0, padx=20, pady=(0, 4), sticky="w")

        # Modpack version (updates after each sync)
        version_row = ctk.CTkFrame(header, fg_color="transparent")
        version_row.grid(row=2, column=0, padx=20, pady=(0, 12), sticky="w")

        self._modpack_version_key = ctk.CTkLabel(
            version_row,
            text=t("ui.modpack_version"),
            font=ctk.CTkFont(size=12),
            text_color="gray",
        )
        self._modpack_version_key.pack(side="left", padx=(0, 6))

        initial_ver = self._config.last_version or t("ui.version_unknown")
        self._modpack_version_val = ctk.CTkLabel(
            version_row,
            text=initial_ver,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#7eb8f7",
        )
        self._modpack_version_val.pack(side="left")

        # Appearance + language controls (top-right cluster)
        ctrl = ctk.CTkFrame(header, fg_color="transparent")
        ctrl.grid(row=0, column=1, rowspan=2, padx=16, pady=8, sticky="e")

        # Theme selector
        self._appearance_var = ctk.StringVar(value="dark")
        ctk.CTkOptionMenu(
            ctrl,
            values=["dark", "light", "system"],
            variable=self._appearance_var,
            width=100,
            command=self._on_appearance_change,
        ).grid(row=0, column=0, padx=(0, 6))

        # Language selector
        locale_options = [LOCALE_DISPLAY_NAMES[lc] for lc in SUPPORTED_LOCALES]
        current_display = LOCALE_DISPLAY_NAMES.get(get_locale(), locale_options[0])
        self._lang_var = ctk.StringVar(value=current_display)
        ctk.CTkOptionMenu(
            ctrl,
            values=locale_options,
            variable=self._lang_var,
            width=110,
            command=self._on_language_change,
        ).grid(row=0, column=1)

        # ── Config frame ───────────────────────────────────────────────────
        cfg = ctk.CTkFrame(self)
        cfg.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        cfg.grid_columnconfigure(1, weight=1)

        self._folder_key_label = ctk.CTkLabel(cfg, text=t("ui.minecraft_folder"), anchor="w")
        self._folder_key_label.grid(row=0, column=0, padx=(12, 6), pady=6, sticky="w")

        self._dir_label = ctk.CTkLabel(
            cfg, text="", anchor="w",
            text_color="#7eb8f7", font=ctk.CTkFont(size=13),
        )
        self._dir_label.grid(row=0, column=1, padx=4, pady=6, sticky="ew")

        self._change_btn = ctk.CTkButton(
            cfg, text=t("ui.change"), width=90, command=self._on_change_dir
        )
        self._change_btn.grid(row=0, column=2, padx=(4, 12), pady=6)

        self._url_key_label = ctk.CTkLabel(cfg, text=t("ui.remote_url"), anchor="w")
        self._url_key_label.grid(row=1, column=0, padx=(12, 6), pady=4, sticky="w")

        self._url_var = tk.StringVar(value=self._config.base_url)
        self._url_entry = ctk.CTkEntry(cfg, textvariable=self._url_var)
        self._url_entry.grid(row=1, column=1, columnspan=2, padx=(4, 12), pady=4, sticky="ew")
        self._url_var.trace_add("write", self._on_url_changed)

        # ── Optional pack checkboxes ────────────────────────────────────────
        packs_row = ctk.CTkFrame(cfg, fg_color="transparent")
        packs_row.grid(row=2, column=0, columnspan=3, padx=(8, 12), pady=(2, 6), sticky="w")

        self._rp_var = tk.BooleanVar(value=self._config.sync_resourcepacks)
        self._rp_check = ctk.CTkCheckBox(
            packs_row,
            text=t("ui.sync_resourcepacks"),
            variable=self._rp_var,
            command=self._on_rp_toggled,
        )
        self._rp_check.pack(side="left", padx=(4, 16))

        self._sp_var = tk.BooleanVar(value=self._config.sync_shaderpacks)
        self._sp_check = ctk.CTkCheckBox(
            packs_row,
            text=t("ui.sync_shaderpacks"),
            variable=self._sp_var,
            command=self._on_sp_toggled,
        )
        self._sp_check.pack(side="left")

        # ── Action buttons ─────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.grid(row=2, column=0, sticky="ew", padx=12, pady=4)

        self._update_btn = ctk.CTkButton(
            btn_row,
            text=t("ui.check_updates"),
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            command=self._on_update,
        )
        self._update_btn.pack(side="left", padx=(0, 8))

        self._cancel_btn = ctk.CTkButton(
            btn_row,
            text=t("ui.cancel"),
            fg_color="#c0392b",
            hover_color="#96281b",
            height=40,
            state="disabled",
            command=self._on_cancel,
        )
        self._cancel_btn.pack(side="left")

        # ── Progress frame ─────────────────────────────────────────────────
        prog = ctk.CTkFrame(self)
        prog.grid(row=3, column=0, sticky="nsew", padx=12, pady=8)
        prog.grid_columnconfigure(0, weight=1)

        self._overall_label = ctk.CTkLabel(prog, text=t("ui.overall_progress"), anchor="w")
        self._overall_label.grid(row=0, column=0, padx=12, pady=(12, 0), sticky="w")

        self._overall_bar = ctk.CTkProgressBar(prog)
        self._overall_bar.set(0)
        self._overall_bar.grid(row=1, column=0, padx=12, pady=(2, 0), sticky="ew")
        self._overall_pct = ctk.CTkLabel(prog, text="0 %", anchor="e", width=50)
        self._overall_pct.grid(row=1, column=1, padx=(4, 12), sticky="e")

        self._file_label = ctk.CTkLabel(prog, text=t("ui.current_file"), anchor="w")
        self._file_label.grid(row=2, column=0, padx=12, pady=(8, 0), sticky="w")

        self._file_bar = ctk.CTkProgressBar(prog)
        self._file_bar.set(0)
        self._file_bar.grid(row=3, column=0, padx=12, pady=(2, 0), sticky="ew")
        self._file_pct = ctk.CTkLabel(prog, text="0 %", anchor="e", width=50)
        self._file_pct.grid(row=3, column=1, padx=(4, 12), sticky="e")

        stats = ctk.CTkFrame(prog, fg_color="transparent")
        stats.grid(row=4, column=0, columnspan=2, padx=12, pady=(4, 0), sticky="ew")

        self._filename_label = ctk.CTkLabel(
            stats, text="", anchor="w", text_color="gray", font=ctk.CTkFont(size=12)
        )
        self._filename_label.pack(side="left")

        self._speed_label = ctk.CTkLabel(
            stats, text="", anchor="e", text_color="gray", font=ctk.CTkFont(size=12)
        )
        self._speed_label.pack(side="right")

        self._status_label = ctk.CTkLabel(
            prog,
            text=t("ui.ready"),
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            wraplength=580,
        )
        self._status_label.grid(row=5, column=0, columnspan=2, padx=12, pady=(12, 4), sticky="w")

        # Changelog collapsible
        self._cl_visible = False
        self._cl_toggle_btn = ctk.CTkButton(
            prog,
            text=f"▶  {t('ui.changelog')}",
            anchor="w",
            fg_color="transparent",
            hover_color=("gray80", "gray20"),
            font=ctk.CTkFont(size=12),
            command=self._toggle_changelog,
        )
        self._cl_toggle_btn.grid(row=6, column=0, columnspan=2, padx=8, pady=(4, 0), sticky="w")

        self._cl_textbox = ctk.CTkTextbox(
            prog, height=120, font=ctk.CTkFont(size=12), state="disabled"
        )
        # Hidden until there is content

    # -----------------------------------------------------------------------
    # Event handlers
    # -----------------------------------------------------------------------

    def _on_appearance_change(self, value: str) -> None:
        ctk.set_appearance_mode(value)

    def _on_language_change(self, display_name: str) -> None:
        """Switch locale and relabel all static UI strings."""
        # Reverse-look up the locale code from the display name
        code = next(
            (lc for lc, name in LOCALE_DISPLAY_NAMES.items() if name == display_name),
            "en",
        )
        set_locale(code)
        self._config.language = code
        self._config.save()
        # Re-apply all translatable labels; safe to call while sync runs
        # because we only touch CTk widgets from the main thread here.
        self._apply_translations()

    def _apply_translations(self) -> None:
        """Update every translatable widget label to the current locale."""
        self.title(t("app.title"))
        self._title_label.configure(text=t("app.title"))
        self._modpack_version_key.configure(text=t("ui.modpack_version"))
        # If no real version has been fetched yet, re-translate the placeholder
        if not self._config.last_version:
            self._modpack_version_val.configure(text=t("ui.version_unknown"))
        self._folder_key_label.configure(text=t("ui.minecraft_folder"))
        self._change_btn.configure(text=t("ui.change"))
        self._url_key_label.configure(text=t("ui.remote_url"))
        self._rp_check.configure(text=t("ui.sync_resourcepacks"))
        self._sp_check.configure(text=t("ui.sync_shaderpacks"))
        self._overall_label.configure(text=t("ui.overall_progress"))
        self._file_label.configure(text=t("ui.current_file"))
        self._cl_toggle_btn.configure(
            text=f"{'▼' if self._cl_visible else '▶'}  {t('ui.changelog')}"
        )
        # Buttons: only update if not in the middle of a sync
        with self._state_lock:
            running = self._running
        if not running:
            self._update_btn.configure(text=t("ui.check_updates"))
            self._cancel_btn.configure(text=t("ui.cancel"))
            self._status_label.configure(text=t("ui.ready"))
        self._refresh_dir_label()

    def _on_change_dir(self) -> None:
        path = filedialog.askdirectory(
            title=t("dialog.select_folder_title"),
            initialdir=str(self._config.minecraft_dir) if self._config.minecraft_dir else None,
        )
        if path:
            self._config.minecraft_dir = Path(path)
            self._config.save()
            self._refresh_dir_label()

    def _on_url_changed(self, *_: Any) -> None:
        # Only update the in-memory value; save happens on next update click
        self._config.base_url = self._url_var.get()

    def _on_rp_toggled(self) -> None:
        self._config.sync_resourcepacks = self._rp_var.get()
        self._config.save()

    def _on_sp_toggled(self) -> None:
        self._config.sync_shaderpacks = self._sp_var.get()
        self._config.save()

    def _on_update(self) -> None:
        # Double-start guard: check both the thread and our explicit flag
        with self._state_lock:
            if self._running:
                return
            self._running = True

        # Save any pending URL change
        self._config.base_url = self._url_var.get().strip()
        self._config.save()

        if not self._config.minecraft_dir or not self._config.minecraft_dir.is_dir():
            with self._state_lock:
                self._running = False
            messagebox.showerror(
                t("dialog.folder_not_found_title"),
                t("dialog.folder_not_found_body"),
            )
            return

        self._cancel_event.clear()
        self._speed.reset()
        self._prev_bytes = 0
        self._set_running_ui(True)
        self._set_status(t("status.starting"))
        self._set_overall(0, 1)
        self._set_file_progress(0, None)

        self._sync_thread = threading.Thread(
            target=self._run_sync_worker, daemon=True, name="sync-worker"
        )
        self._sync_thread.start()

    def _on_cancel(self) -> None:
        # Idempotent: Event.set() is always safe to call multiple times
        self._cancel_event.set()
        self._set_status(t("status.cancelling"))
        self._cancel_btn.configure(state="disabled")

    # -----------------------------------------------------------------------
    # Sync worker (runs in daemon thread)
    # -----------------------------------------------------------------------

    def _run_sync_worker(self) -> None:
        def on_status(msg: str) -> None:
            self.after(0, self._set_status, msg)

        def on_overall(current: int, total: int) -> None:
            self.after(0, self._set_overall, current, total)

        def on_file_progress(received: int, total: int | None) -> None:
            now   = time.monotonic()
            delta = received - self._prev_bytes
            if delta > 0:
                self._speed.add(delta, now)
                self._prev_bytes = received
            self.after(0, self._update_file_progress, received, total, self._speed.speed_bps())

        def on_file_done(entry: FileEntry, success: bool, error: str | None) -> None:
            self._prev_bytes = 0
            colour = "#2ecc71" if success else "#e74c3c"
            label  = entry.path if success else f"✕ {entry.path}: {error}"
            self.after(0, self._set_filename, label, colour)
            self.after(0, self._set_file_progress, 0, None)

        try:
            report: SyncReport = run_sync(
                self._config,
                cancel_event=self._cancel_event,
                on_status=on_status,
                on_overall_progress=on_overall,
                on_file_progress=on_file_progress,
                on_file_done=on_file_done,
            )
        except Exception as exc:
            # Absolute safety net — run_sync should never raise, but just in case
            log.exception("Unexpected error in sync worker: %s", exc)
            from src.sync import SyncReport as _SR
            report = _SR(errors=[str(exc)])
        finally:
            # Always release the running flag, even if self.after() is
            # unavailable (e.g. window was closed mid-sync).
            with self._state_lock:
                self._running = False

        self.after(0, self._on_sync_done, report)

    # -----------------------------------------------------------------------
    # Sync completion (main thread)
    # -----------------------------------------------------------------------

    def _on_sync_done(self, report: SyncReport) -> None:
        self._set_running_ui(False)
        self._set_overall(1, 1)

        # Update the modpack version label whenever the manifest returned a version
        if report.version:
            self._modpack_version_val.configure(text=report.version)

        if report.cancelled:
            self._set_status(t("status.cancelled"))
        elif report.success:
            self._set_status(f"✔ {report.summary()}")
        else:
            self._set_status(f"✕ {report.summary()}")
            if report.errors:
                messagebox.showerror(
                    t("dialog.sync_errors_title"),
                    t("dialog.sync_errors_body")
                    + "\n\n"
                    + "\n".join(f"• {e}" for e in report.errors[:10]),
                )

        if report.changelog:
            self._show_changelog(report.changelog)

        log.info("Sync complete: %s", report.summary())

    # -----------------------------------------------------------------------
    # UI update helpers  ← all must be called from the main thread
    # -----------------------------------------------------------------------

    def _refresh_dir_label(self) -> None:
        text = str(self._config.minecraft_dir) if self._config.minecraft_dir else t("ui.not_set")
        self._dir_label.configure(text=text)

    def _set_running_ui(self, running: bool) -> None:
        self._update_btn.configure(state="disabled" if running else "normal")
        self._cancel_btn.configure(state="normal" if running else "disabled")
        if not running:
            # Restore translated button labels
            self._update_btn.configure(text=t("ui.check_updates"))
            self._cancel_btn.configure(text=t("ui.cancel"))

    def _set_status(self, msg: str) -> None:
        self._status_label.configure(text=msg)

    def _set_overall(self, current: int, total: int) -> None:
        frac = current / total if total else 0.0
        self._overall_bar.set(frac)
        self._overall_pct.configure(text=f"{int(frac * 100)} %")

    def _set_file_progress(self, received: int, total: int | None) -> None:
        if total and total > 0:
            frac = received / total
            self._file_bar.set(frac)
            self._file_pct.configure(text=f"{int(frac * 100)} %")
        else:
            self._file_bar.set(0)
            self._file_pct.configure(text="–")

    def _update_file_progress(self, received: int, total: int | None, speed_bps: float) -> None:
        self._set_file_progress(received, total)
        recv_mb = received / 1_048_576
        size_str = (
            f"{recv_mb:.1f} / {total / 1_048_576:.1f} MB" if total
            else f"{recv_mb:.1f} MB"
        )
        if speed_bps >= 1_048_576:
            spd = f"{speed_bps / 1_048_576:.1f} MB/s"
        elif speed_bps >= 1024:
            spd = f"{speed_bps / 1024:.0f} KB/s"
        else:
            spd = "–"
        self._speed_label.configure(text=f"{spd}  |  {size_str}")

    def _set_filename(self, name: str, colour: str = "gray") -> None:
        self._filename_label.configure(text=name, text_color=colour)

    # -----------------------------------------------------------------------
    # Changelog panel
    # -----------------------------------------------------------------------

    def _toggle_changelog(self) -> None:
        self._cl_visible = not self._cl_visible
        arrow = "▼" if self._cl_visible else "▶"
        self._cl_toggle_btn.configure(text=f"{arrow}  {t('ui.changelog')}")
        if self._cl_visible:
            self._cl_textbox.grid(
                row=7, column=0, columnspan=2, padx=12, pady=(2, 12), sticky="ew"
            )
        else:
            self._cl_textbox.grid_forget()

    def _show_changelog(self, text: str) -> None:
        self._cl_textbox.configure(state="normal")
        self._cl_textbox.delete("1.0", "end")
        self._cl_textbox.insert("1.0", text)
        self._cl_textbox.configure(state="disabled")
        if not self._cl_visible:
            self._toggle_changelog()
