# Modpack Updater

A lightweight, zero-technical-knowledge Minecraft modpack synchroniser.  
Users run a single `.exe`; the tool compares their local `.minecraft` folder against a remote GitHub repository and downloads only what has changed.

---

## Features

| | |
|---|---|
| ✅ Auto-detects `.minecraft` on Windows (`%APPDATA%\.minecraft`) | ✅ SHA-256 integrity check after every download |
| ✅ Modern dark/light GUI (CustomTkinter) | ✅ Parallel downloads (configurable) |
| ✅ Per-file + overall progress bars | ✅ Download speed meter |
| ✅ Cancellation at any time | ✅ Changelog display |
| ✅ Rotating log file (`modpack_updater.log`) | ✅ Headless / CLI mode |
| ✅ Orphan file cleanup | ✅ Retry with back-off on failures |

---

## Build
```
python -m nuitka --onefile --windows-console-mode=disable --enable-plugin=tk-inter --windows-icon-from-ico=icon.ico --output-filename=ModpackUpdater.exe main.py
```

## Project structure

```
modpackUpdater/
├── main.py                  # Entry point
├── requirements.txt
├── build.ps1                # PyInstaller build (Windows)
├── build.sh                 # PyInstaller build (Linux/macOS)
└── src/
    ├── __init__.py
    ├── logger.py            # Logging setup (console + rotating file)
    ├── config.py            # config.json persistence
    ├── hashing.py           # SHA-256 helpers
    ├── manifest.py          # manifest.json download + parsing
    ├── downloader.py        # Single-file + parallel download engine
    ├── sync.py              # Full sync orchestration
    └── gui.py               # CustomTkinter UI
```

---

## Remote repository structure

Your GitHub repository must look like this:

```
manifest.json        ← root of the repo
pack/
    mods/
    config/
    resourcepacks/
    shaderpacks/
    kubejs/
    defaultconfigs/
```

### `manifest.json` schema

```json
{
    "version": "1.0.0",
    "changelog": "Optional human-readable changelog text.",
    "files": [
        {
            "path": "mods/create.jar",
            "sha256": "<64-char hex digest>",
            "size": 123456
        }
    ]
}
```

---

## Quick start

### 1 – Install dependencies

```bash
pip install -r requirements.txt
```

### 2 – Configure `config.json`

On first run the app auto-detects `.minecraft`.  
Set your remote URL in the GUI **Remote URL** field, or pre-populate `config.json`:

```json
{
    "minecraft_dir": "C:\\Users\\YourName\\AppData\\Roaming\\.minecraft",
    "base_url": "https://raw.githubusercontent.com/YOUR_USER/YOUR_REPO/main/pack",
    "parallel_downloads": 4
}
```

> **`base_url`** must point to the `pack/` directory of the raw GitHub content.  
> The updater automatically appends `/manifest.json` one level **above** the pack folder.

### 3 – Run

```bash
# GUI (default)
python main.py

# Headless / CLI
python main.py --cli
```

---

## Building a standalone `.exe`

### Windows (PowerShell)

```powershell
pip install pyinstaller
.\build.ps1
# Output: dist\ModpackUpdater.exe
```

### Linux / macOS

```bash
pip install pyinstaller
bash build.sh
# Output: dist/ModpackUpdater
```

---

## Generating `manifest.json`

Example Python script to generate a manifest from a local `pack/` folder:

```python
#!/usr/bin/env python3
"""generate_manifest.py – run from the repo root."""
import hashlib, json, os
from pathlib import Path

PACK_DIR = Path("pack")
VERSION = "1.0.0"

files = []
for path in sorted(PACK_DIR.rglob("*")):
    if path.is_file():
        data = path.read_bytes()
        files.append({
            "path": path.relative_to(PACK_DIR).as_posix(),
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        })

manifest = {"version": VERSION, "files": files}
Path("manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"manifest.json written ({len(files)} files)")
```

---

## Extending to other origins (Cloudflare R2, S3, …)

Change only the `base_url` in `config.json`.  
The downloader fetches files as `{base_url}/{relative_path}`, so any HTTP-accessible origin works with no code changes.

---

## Managed directories

The updater **only** touches files inside these sub-directories of `.minecraft`:

- `mods/`
- `config/`
- `resourcepacks/`
- `shaderpacks/`
- `kubejs/`
- `defaultconfigs/`

All other folders and files are **never read, modified, or deleted**.

---

## License

[MIT](LICENSE)
