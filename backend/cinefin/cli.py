"""`cinefin` console entry point for a pip / pipx install — run the server headless.

    cinefin            # migrate, then serve (default)
    cinefin serve      # same
    cinefin migrate    # apply migrations and exit

Data lives in the XDG data dir (``~/.local/share/cinefin``) unless
``CINEFIN_USERDATA_DIR`` is set. Host/port default to ``0.0.0.0:8000``
(``CINEFIN_HOST`` / ``CINEFIN_PORT`` override). The SPA build and collected
static ship inside the wheel, so no source tree is needed at runtime; ffmpeg is
an optional system dependency (certification/title cards need it).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = "8000"


def _data_dir() -> Path:
    if os.environ.get("CINEFIN_USERDATA_DIR"):
        return Path(os.environ["CINEFIN_USERDATA_DIR"])
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "Cinefin"
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(xdg) / "cinefin"


def _setup_env() -> None:
    """Point Django at the packaged assets and the per-user data dir (idempotent)."""
    pkg = Path(__file__).resolve().parent  # the installed `cinefin` package dir
    data = _data_dir()
    data.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinefin.settings")
    os.environ.setdefault("CINEFIN_USERDATA_DIR", str(data))
    host = os.environ.get("CINEFIN_HOST", DEFAULT_HOST)
    port = os.environ.get("CINEFIN_PORT", DEFAULT_PORT)
    os.environ.setdefault("CINEFIN_SERVER_URL", f"http://{host}:{port}")

    # The SPA build ships inside the wheel at cinefin/spa (settings reads the env).
    spa = pkg / "spa"
    if spa.is_dir():
        os.environ.setdefault("CINEFIN_FRONTEND_BUILD_DIR", str(spa))


def run_migrate() -> int:
    # argv[1] == "migrate" -> ApiConfig skips the background workers, so this is
    # a clean schema-only pass.
    _setup_env()
    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=1)
    return 0


def run_serve() -> int:
    _setup_env()
    # Migrate in a child first (workers skipped there); then serve in this
    # process, where ApiConfig starts the sync engine + schedule runner.
    subprocess.run([sys.executable, "-m", "cinefin.cli", "migrate"], check=True)

    import django

    django.setup()
    import uvicorn

    from cinefin.asgi import application

    uvicorn.run(
        application,
        host=os.environ.get("CINEFIN_HOST", DEFAULT_HOST),
        port=int(os.environ.get("CINEFIN_PORT", DEFAULT_PORT)),
        log_level="info",
        # Per-request access log is noise by default; CINEFIN_ACCESS_LOG=1 restores it.
        access_log=os.environ.get("CINEFIN_ACCESS_LOG") == "1",
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="cinefin", description="Run the Cinefin server.")
    parser.add_argument("command", nargs="?", default="serve", choices=["serve", "migrate"])
    args = parser.parse_args()
    return run_migrate() if args.command == "migrate" else run_serve()


if __name__ == "__main__":
    sys.exit(main())
