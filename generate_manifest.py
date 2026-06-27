#!/usr/bin/env python3
"""
generate_manifest.py
Usage: python generate_manifest.py [--pack-dir pack] [--version 1.0.0] [--changelog "..."]

Run from the root of your modpack repository.
Produces manifest.json next to this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate manifest.json for the Modpack Updater."
    )
    parser.add_argument(
        "--pack-dir", default="pack", help="Path to the pack directory (default: pack)"
    )
    parser.add_argument(
        "--version", default="1.0.0", help="Manifest version string (default: 1.0.0)"
    )
    parser.add_argument(
        "--changelog", default=None, help="Optional changelog text to embed"
    )
    parser.add_argument(
        "--output", default="manifest.json", help="Output file path (default: manifest.json)"
    )
    args = parser.parse_args()

    pack_dir = Path(args.pack_dir)
    if not pack_dir.is_dir():
        raise SystemExit(f"ERROR: pack directory not found: {pack_dir}")

    files: list[dict] = []
    for path in sorted(pack_dir.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": path.relative_to(pack_dir).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )

    manifest: dict = {"version": args.version, "files": files}
    if args.changelog:
        manifest["changelog"] = args.changelog

    output = Path(args.output)
    output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {output} ({len(files)} files, version {args.version})")


if __name__ == "__main__":
    main()
