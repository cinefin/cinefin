# Cinefin — Windows build

A native Windows package of the Cinefin **server**, built by **bundling a real
Python** rather than freezing it: a relocatable Python with the `cinefin` wheel
pip-installed, plus ffmpeg and a small tray, wrapped in a GUI installer. Because
it's an ordinary Python environment, every data file / native lib / dynamic
import resolves the way it does in dev — no PyInstaller spec, no hidden-imports,
no per-dependency whack-a-mole. Playout stays on the remote agent; this box is
the server only.

## What the user gets

- **GUI installer** (`Cinefin-Setup-<version>.exe`, Inno Setup) — per-user, no
  admin. Start-Menu shortcut, optional "start at login", clean uninstaller.
- **Tray app** (`tray.py`, green = running / grey = stopped): Open Cinefin ·
  Start · Stop · Restart · Open logs · Open data folder · Run at login · Quit.
- **Data** in `%LOCALAPPDATA%\Cinefin` (SQLite db, media, secret key, logs) —
  survives uninstall/upgrade.

## How it's laid out

The installer drops a self-contained tree under `%LOCALAPPDATA%\Programs\Cinefin`:

```
python\      relocatable CPython 3.13 with the cinefin wheel + deps pip-installed
ffmpeg\      static ffmpeg/ffprobe (cert/title cards)
tray.py      the system tray
cinefin.ico
```

The shortcut runs `python\pythonw.exe tray.py`. The tray sets
`CINEFIN_USERDATA_DIR=%LOCALAPPDATA%\Cinefin`, prepends `ffmpeg\` to `PATH`, and
runs `python\pythonw.exe -m cinefin.cli serve` as a child (start/stop/restart =
manage that child), redirecting its output to `logs\server.log`. `cinefin.cli`
migrates then runs uvicorn — the same command the pipx package exposes.

## Releases

Built and published by `.github/workflows/release.yml` alongside the container:
the `windows` job **reuses the wheel** from the `wheel` job (no SPA/backend build
on Windows), so it only downloads a Python, `pip install`s the wheel, grabs
ffmpeg and runs Inno Setup. Attached to the rolling **`edge`** pre-release on
`main` and to the **release** on a `vX.Y.Z` tag.

## Building locally

Needs a Windows box with Inno Setup 6 (`iscc` on PATH) + internet. Build the
wheel first (works on Linux/WSL/git-bash), then assemble:

```bash
bash packaging/pip/build-wheel.sh                      # -> backend/dist/cinefin3-<ver>-py3-none-any.whl
```
```powershell
pwsh packaging/windows/build.ps1 -Wheel backend\dist\cinefin3-<ver>-py3-none-any.whl
# -> packaging/windows/Output/Cinefin-Setup-<ver>.exe
```

`build.ps1` downloads a relocatable Python (python-build-standalone, latest
`install_only`), `pip install`s the wheel + `pystray` into it, fetches a static
ffmpeg, generates the icon, and runs Inno Setup — no PyInstaller.

> ffmpeg comes from BtbN's `latest` static build; pin a release tag in
> `build.ps1` if you want reproducibility.
