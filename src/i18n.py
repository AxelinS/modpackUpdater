"""
i18n.py – Minimal internationalisation engine.

Supported locales: "en" (English), "es" (Spanish).

Usage:
    from src.i18n import t, set_locale
    set_locale("es")
    print(t("app.title"))   # → "Actualizador de Modpack"

All user-visible strings live here.  No external dependencies.
"""

from __future__ import annotations

_STRINGS: dict[str, dict[str, str]] = {
    # ── Application ────────────────────────────────────────────────────────
    "app.title": {
        "en": "Modpack Updater",
        "es": "Actualizador de Modpack",
    },
    # ── Header / controls ──────────────────────────────────────────────────
    "ui.appearance": {
        "en": "Theme",
        "es": "Tema",
    },
    "ui.language": {
        "en": "Language",
        "es": "Idioma",
    },
    "ui.minecraft_folder": {
        "en": "Minecraft folder:",
        "es": "Carpeta de Minecraft:",
    },
    "ui.remote_url": {
        "en": "Remote URL:",
        "es": "URL remota:",
    },
    "ui.change": {
        "en": "Change",
        "es": "Cambiar",
    },
    "ui.check_updates": {
        "en": "⟳  Check for Updates",
        "es": "⟳  Buscar actualizaciones",
    },
    "ui.cancel": {
        "en": "✕  Cancel",
        "es": "✕  Cancelar",
    },
    "ui.overall_progress": {
        "en": "Overall progress",
        "es": "Progreso general",
    },
    "ui.current_file": {
        "en": "Current file",
        "es": "Archivo actual",
    },
    "ui.changelog": {
        "en": "Changelog",
        "es": "Registro de cambios",
    },
    "ui.modpack_version": {
        "en": "Modpack version:",
        "es": "Versión del modpack:",
    },
    "ui.version_unknown": {
        "en": "unknown",
        "es": "desconocida",
    },
    "ui.sync_resourcepacks": {
        "en": "Sync resourcepacks",
        "es": "Sincronizar resourcepacks",
    },
    "ui.sync_shaderpacks": {
        "en": "Sync shaderpacks",
        "es": "Sincronizar shaderpacks",
    },
    "ui.not_set": {
        "en": "Not set",
        "es": "No configurada",
    },
    "ui.ready": {
        "en": "Ready.",
        "es": "Listo.",
    },
    # ── Dialogs ────────────────────────────────────────────────────────────
    "dialog.select_folder_title": {
        "en": "Select .minecraft folder",
        "es": "Seleccionar carpeta .minecraft",
    },
    "dialog.folder_not_found_title": {
        "en": "Folder not found",
        "es": "Carpeta no encontrada",
    },
    "dialog.folder_not_found_body": {
        "en": "The Minecraft folder does not exist.\nPlease select a valid folder.",
        "es": "La carpeta de Minecraft no existe.\nPor favor selecciona una carpeta válida.",
    },
    "dialog.sync_errors_title": {
        "en": "Sync errors",
        "es": "Errores de sincronización",
    },
    "dialog.sync_errors_body": {
        "en": "Some files could not be updated:",
        "es": "Algunos archivos no pudieron actualizarse:",
    },
    # ── Status messages ────────────────────────────────────────────────────
    "status.starting": {
        "en": "Starting…",
        "es": "Iniciando…",
    },
    "status.cancelling": {
        "en": "Cancelling…",
        "es": "Cancelando…",
    },
    "status.cancelled": {
        "en": "⚠ Update cancelled.",
        "es": "⚠ Actualización cancelada.",
    },
    "status.downloading_manifest": {
        "en": "Downloading manifest…",
        "es": "Descargando manifiesto…",
    },
    "status.scanning": {
        "en": "Scanning local files…",
        "es": "Escaneando archivos locales…",
    },
    "status.checking_file": {
        "en": "Checking {path}…",
        "es": "Verificando {path}…",
    },
    "status.up_to_date": {
        "en": "Everything is up-to-date.",
        "es": "Todo está al día.",
    },
    "status.downloading_n": {
        "en": "Downloading {n} file(s)…",
        "es": "Descargando {n} archivo(s)…",
    },
    # ── SyncReport summary ─────────────────────────────────────────────────
    "report.nothing": {
        "en": "Nothing to do.",
        "es": "Nada que hacer.",
    },
    "report.up_to_date": {
        "en": "{n} file(s) up-to-date",
        "es": "{n} archivo(s) al día",
    },
    "report.updated": {
        "en": "{n} file(s) updated",
        "es": "{n} archivo(s) actualizados",
    },
    "report.removed": {
        "en": "{n} file(s) removed",
        "es": "{n} archivo(s) eliminados",
    },
    "report.errors": {
        "en": "{n} error(s)",
        "es": "{n} error(es)",
    },
    "report.cancelled": {
        "en": "Update cancelled by user.",
        "es": "Actualización cancelada por el usuario.",
    },
    # ── Error messages ─────────────────────────────────────────────────────
    "error.manifest_fetch": {
        "en": "Failed to fetch manifest: {detail}",
        "es": "Error al obtener el manifiesto: {detail}",
    },
    "error.cannot_read_file": {
        "en": "Cannot read {path}: {detail} – will re-download.",
        "es": "No se puede leer {path}: {detail} – se volverá a descargar.",
    },
    "error.delete_orphan": {
        "en": "Could not delete {path}: {detail}",
        "es": "No se pudo eliminar {path}: {detail}",
    },
    "error.hash_mismatch": {
        "en": "SHA-256 mismatch for {path}: expected {expected}… got {actual}…",
        "es": "Error SHA-256 en {path}: se esperaba {expected}… se obtuvo {actual}…",
    },
    "error.dir_not_set": {
        "en": "Minecraft directory is not set or does not exist. Please select it manually.",
        "es": "La carpeta de Minecraft no está configurada o no existe. Por favor selecciónala manualmente.",
    },
    # ── CLI ────────────────────────────────────────────────────────────────
    "cli.result_ok": {
        "en": "OK",
        "es": "CORRECTO",
    },
    "cli.result_failed": {
        "en": "FAILED",
        "es": "FALLIDO",
    },
}

# Active locale (module-level singleton — only the GUI thread writes to it)
_active_locale: str = "en"

SUPPORTED_LOCALES: tuple[str, ...] = ("en", "es")
LOCALE_DISPLAY_NAMES: dict[str, str] = {
    "en": "English",
    "es": "Español",
}


def set_locale(locale: str) -> None:
    """Change the active locale.  Falls back to 'en' for unknown codes."""
    global _active_locale
    _active_locale = locale if locale in SUPPORTED_LOCALES else "en"


def get_locale() -> str:
    return _active_locale


def t(key: str, **kwargs: object) -> str:
    """Return the translated string for *key* in the active locale.

    Keyword arguments are substituted via ``str.format_map``.
    Unknown keys fall back to the key itself (never raises).
    """
    entry = _STRINGS.get(key)
    if entry is None:
        return key  # graceful fallback

    text = entry.get(_active_locale) or entry.get("en") or key
    if kwargs:
        try:
            text = text.format_map(kwargs)
        except (KeyError, IndexError):
            pass  # return unformatted string rather than crash
    return text
