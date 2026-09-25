# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Cinefin Windows bundle (one-folder). Build via
# packaging/windows/build.ps1, which prepares the SPA build, collectstatic
# output and ffmpeg binaries this spec expects.
import os
import sys
import tempfile

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

REPO = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
BACKEND = os.path.join(REPO, "backend")

# The entry script imports Django/cinefin only inside functions (the tray must
# not load Django), so PyInstaller's static analysis can't see them — we rely on
# collect_submodules below. That imports the cinefin package, which needs the
# backend on sys.path and a ready app registry. Set a side-effect-free build env
# (no worker threads, no secret-key/media writes) and run django.setup() once.
sys.path.insert(0, BACKEND)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinefin.settings")
os.environ.setdefault("SECRET_KEY", "build-time-only-not-shipped")
os.environ.setdefault("CINEFIN_DISABLE_BACKGROUND_WORKERS", "1")
os.environ.setdefault("CINEFIN_USERDATA_DIR", tempfile.mkdtemp(prefix="cinefin-build-"))

import django

django.setup()

# Data bundled under _internal/… — the launcher points Django at these via
# CINEFIN_FRONTEND_BUILD_DIR / CINEFIN_ASSETS_DIR / CINEFIN_PLUGINS_DIR and the
# package-relative dirs (cinefin/static, staticfiles, templates) resolve normally.
datas = [
    (os.path.join(REPO, "frontend", "build"), "frontend/build"),
    (os.path.join(BACKEND, "cinefin", "assets"), "cinefin/assets"),
    (os.path.join(BACKEND, "cinefin", "static"), "cinefin/static"),
    (os.path.join(BACKEND, "cinefin", "staticfiles"), "cinefin/staticfiles"),
    (os.path.join(BACKEND, "cinefin", "templates"), "cinefin/templates"),
    (os.path.join(REPO, "contrib", "plugins"), "contrib/plugins"),
]
_ffmpeg = os.path.join(SPECPATH, "ffmpeg")
if os.path.isdir(_ffmpeg):
    datas.append((_ffmpeg, "ffmpeg"))

# Django/ninja ship templates + static as package data.
datas += collect_data_files("django")
datas += collect_data_files("ninja")

# cinefin has lots of dynamically imported modules (sync plugins, ratings
# providers, management commands, migrations); collect the whole tree. Django,
# uvicorn[standard] and ninja likewise import submodules dynamically.
hiddenimports = (
    collect_submodules("cinefin")
    + collect_submodules("django")
    + collect_submodules("uvicorn")
    + collect_submodules("ninja")
    + [
        "whitenoise",
        "whitenoise.middleware",
        "asgiref",
        "anyio",
        "websockets",
        "httptools",
        "PIL",
        "pystray",
    ]
)

a = Analysis(
    ["cinefin_tray.py"],
    pathex=[BACKEND, SPECPATH],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

_icon = os.path.join(SPECPATH, "cinefin.ico")
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Cinefin",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # tray app — no console window
    icon=_icon if os.path.exists(_icon) else None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Cinefin",
)
