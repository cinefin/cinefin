# Cinefin — Windows build

A lean native Windows package of the Cinefin **server**: a single frozen
`Cinefin.exe` that runs the Django app under uvicorn and a minimal system-tray
UI to manage it, wrapped in a GUI installer. Playout stays on the remote agent —
this box is the server only.

## What the user gets

- **GUI installer** (`Cinefin-Setup-<version>.exe`, Inno Setup) — per-user, no
  admin. Start-Menu shortcut, optional "start at login", clean uninstaller.
- **Tray app** — one icon (green = running, grey = stopped) with:
  Open Cinefin · Start · Stop · Restart · Open logs · Open data folder ·
  Run at login · Quit. Double-click / "Open Cinefin" opens `http://localhost:8000/app/`.
- **Data** in `%LOCALAPPDATA%\Cinefin` (SQLite db, media, secret key, logs) —
  survives uninstall/upgrade.
- **Bundled** SPA build, app assets, contrib plugins, and static ffmpeg/ffprobe
  (so certification/title cards work out of the box).

## Architecture

`Cinefin.exe` is one binary dispatched by argv (`cinefin_tray.py`):

| mode | what it does |
|------|--------------|
| *(none)* / `tray` | the tray app; spawns and manages the server child |
| `serve` | configures Django (paths → bundle + `%LOCALAPPDATA%`) and runs uvicorn |
| `migrate` | applies DB migrations, then exits |

The tray never imports Django — it runs `Cinefin.exe migrate` once, then
`Cinefin.exe serve` as a child, so Stop/Restart just kill/respawn the child.
The frozen app points Django at bundled data via `CINEFIN_FRONTEND_BUILD_DIR`,
`CINEFIN_ASSETS_DIR`, `CINEFIN_PLUGINS_DIR` and `CINEFIN_USERDATA_DIR` (all
env-overridable in `settings.py`), and prepends the bundled `ffmpeg\` to `PATH`.

## Releases

The installer is built and published by `.github/workflows/release.yml`
alongside the container:

- push to `main` → attached to the rolling **`edge`** pre-release
  (version = `git describe`);
- tag `vX.Y.Z` → attached to that **release**.

A manual `workflow_dispatch` run builds it (and the image) without publishing.

## Building locally

Neither the build nor the artifact can be produced on Linux — build on Windows.

Prerequisites: Python 3.13 + Poetry, Node 20+, Inno Setup 6 (`iscc` on PATH).

```powershell
pwsh packaging/windows/build.ps1            # -> packaging/windows/Output/Cinefin-Setup-<ver>.exe
```

`build.ps1`: builds the SPA → installs backend deps + `pyinstaller`/`pystray` →
`collectstatic` → downloads a static ffmpeg once → makes the icon → runs
PyInstaller (`cinefin.spec`) → runs Inno Setup (`installer.iss`).

## Tuning points (validate on Windows)

Freezing Django + uvicorn always needs a pass on a real Windows box:

- **Missing modules** at runtime → add to `hiddenimports` in `cinefin.spec`
  (dynamically imported: sync plugins, ratings providers, DB backends,
  uvicorn/websockets internals). `collect_submodules` covers most of the tree.
- **Missing package data** (a template/static file 404s) → add to `datas`.
- ffmpeg source is BtbN's static build; pin a release tag in `build.ps1` if you
  want reproducibility instead of `latest`.
