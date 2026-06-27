"""
main.py – Entry point for the Modpack Updater.

Usage
-----
GUI (default):
    ModpackUpdater.exe
    python main.py

GUI with pre-filled values (opens window but overrides config fields):
    ModpackUpdater.exe --dir "C:\\Users\\x\\AppData\\Roaming\\.minecraft"
    ModpackUpdater.exe --url "https://raw.githubusercontent.com/..."
    ModpackUpdater.exe --dir <path> --url <url>

Headless / CLI (no window, exits with 0 on success, 1 on failure):
    ModpackUpdater.exe --sync
    ModpackUpdater.exe --sync --dir <path> --url <url>
    ModpackUpdater.exe --sync --dir <path> --url <url> --parallel 8

Argument reference
------------------
--dir PATH      Path to the .minecraft folder.
                Overrides the saved config for this run (or permanently when
                combined with --save).
--url URL       Remote raw-file base URL (pack root).
                Overrides the saved config for this run (or permanently with
                --save).
--parallel N    Number of simultaneous downloads (default: from config).
--sync          Run headless sync instead of opening the GUI.
--save          Persist --dir / --url / --parallel back to mupdater_config.json
                before running.  Has no effect without at least one of those
                flags.
--lang LOCALE   Override the UI language for this run (en / es).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.logger import setup_logging


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ModpackUpdater",
        description="Minecraft Modpack Updater — keeps your .minecraft in sync with a remote repository.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Open GUI with a custom minecraft folder pre-selected:
  ModpackUpdater.exe --dir "C:\\Users\\Steve\\AppData\\Roaming\\.minecraft"

  # Headless sync with explicit folder + URL, save values for next time:
  ModpackUpdater.exe --sync --dir "C:\\...minecraft" --url "https://..." --save

  # Headless sync using whatever is already in the config file:
  ModpackUpdater.exe --sync
""",
    )
    parser.add_argument(
        "--dir",
        metavar="PATH",
        help="Path to the .minecraft folder (overrides saved config for this run).",
    )
    parser.add_argument(
        "--url",
        metavar="URL",
        help="Remote raw-file base URL, e.g. https://raw.githubusercontent.com/user/repo/main/pack",
    )
    parser.add_argument(
        "--parallel",
        metavar="N",
        type=int,
        help="Number of parallel downloads (overrides saved config for this run).",
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Run a headless sync without opening the GUI.  Exits 0 on success, 1 on error.",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Persist --dir / --url / --parallel to mupdater_config.json before running.",
    )
    parser.add_argument(
        "--lang",
        metavar="LOCALE",
        choices=["en", "es"],
        help="UI language for this run: en or es (does not change saved config).",
    )
    return parser


# ---------------------------------------------------------------------------
# Config override helper
# ---------------------------------------------------------------------------

def _apply_overrides(config, args: argparse.Namespace) -> None:
    """Apply CLI argument overrides onto *config* in-place."""
    if args.dir:
        config.minecraft_dir = Path(args.dir).expanduser().resolve()
    if args.url:
        config.base_url = args.url.rstrip("/")
    if args.parallel is not None:
        config.parallel_downloads = max(1, args.parallel)
    if args.save:
        config.save()


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def main() -> int:
    setup_logging()

    parser = _build_parser()
    args = parser.parse_args()

    # Load base config then layer CLI overrides on top
    from src.config import AppConfig
    config = AppConfig().load()

    # Language override (runtime only, not saved unless --save is also given)
    if args.lang:
        from src.i18n import set_locale
        set_locale(args.lang)

    _apply_overrides(config, args)

    if args.sync:
        return _run_cli(config)
    else:
        return _run_gui(config)


def _run_gui(config) -> int:
    """Launch the CustomTkinter window, pre-populated with *config*."""
    from src.gui import App

    app = App(config)
    app.mainloop()
    return 0


def _run_cli(config) -> int:
    """Headless sync — prints progress to stdout, returns exit code."""
    from src.i18n import t
    from src.sync import run_sync

    # Validate before starting so the error is visible without a GUI
    if not config.minecraft_dir or not config.minecraft_dir.is_dir():
        print(
            f"ERROR: .minecraft folder not found: {config.minecraft_dir}\n"
            "       Use --dir to specify the correct path.",
            file=sys.stderr,
        )
        return 1

    print(f"Minecraft dir : {config.minecraft_dir}")
    print(f"Remote URL    : {config.base_url}")
    print(f"Parallel      : {config.parallel_downloads}")
    print()

    report = run_sync(
        config,
        on_status=lambda msg: print(f"  {msg}"),
        on_overall_progress=lambda c, total: print(f"  [{c}/{total}] files processed"),
    )

    print()
    print(f"Result  : {t('cli.result_ok') if report.success else t('cli.result_failed')}")
    print(f"Version : {report.version}")
    print(f"Summary : {report.summary()}")

    if report.errors:
        print("\nErrors:")
        for err in report.errors:
            print(f"  • {err}")

    if report.changelog:
        print(f"\nChangelog:\n{report.changelog}")

    return 0 if report.success else 1


if __name__ == "__main__":
    sys.exit(main())
