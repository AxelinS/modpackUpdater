"""
main.py – Entry point for the Modpack Updater.

Usage:
    python main.py          # run with GUI
    python main.py --cli    # headless sync (for scripting / CI)
"""

from __future__ import annotations

import argparse
import sys

from src.logger import setup_logging


def main() -> int:
    setup_logging()

    parser = argparse.ArgumentParser(description="Modpack Updater for Minecraft")
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run a headless sync without GUI (useful for scripting).",
    )
    args = parser.parse_args()

    if args.cli:
        return _run_cli()
    else:
        return _run_gui()


def _run_gui() -> int:
    from src.config import AppConfig
    from src.gui import App

    config = AppConfig().load()
    app = App(config)
    app.mainloop()
    return 0


def _run_cli() -> int:
    """Headless sync — prints progress to stdout and returns exit code."""
    from src.config import AppConfig
    from src.sync import run_sync

    config = AppConfig().load()

    print(f"Minecraft dir : {config.minecraft_dir}")
    print(f"Remote URL    : {config.base_url}")
    print()

    try:
        report = run_sync(
            config,
            on_status=lambda msg: print(f"  {msg}"),
            on_overall_progress=lambda c, t: print(f"  [{c}/{t}] files processed"),
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print()
    print(f"Result  : {'OK' if report.success else 'FAILED'}")
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
