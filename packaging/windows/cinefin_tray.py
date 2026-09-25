"""Cinefin Windows entry point: tray launcher + server, in one frozen exe.

Dispatched by argv:
  (none) / tray  -> the system-tray app; it manages the server as a child process
  serve          -> configure Django + run uvicorn (blocking)
  migrate        -> apply DB migrations and exit

The tray never imports Django — it spawns `Cinefin.exe serve` as a child and
starts/stops/restarts that, which keeps stop/restart robust (kill the child) and
the tray lightweight. All paths are set up here, before Django loads, and are
inherited by the children.
"""

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

HOST = "127.0.0.1"
PORT = int(os.environ.get("CINEFIN_PORT", "8000"))
URL = f"http://{HOST}:{PORT}/app/"
APP_NAME = "Cinefin"


def _bundle_dir() -> Path:
    """Where bundled data lives: PyInstaller's _MEIPASS when frozen, else the repo."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
    # Dev fallback: run from the repo (packaging/windows/ -> repo root).
    return Path(__file__).resolve().parent.parent.parent


def _data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def _setup_environment() -> None:
    """Point Django at the bundled assets and the per-user data dir. Idempotent."""
    bundle = _bundle_dir()
    data = _data_dir()

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinefin.settings")
    os.environ.setdefault("CINEFIN_USERDATA_DIR", str(data))
    os.environ.setdefault("CINEFIN_SERVER_URL", f"http://{HOST}:{PORT}")
    os.environ.setdefault("CINEFIN_LOG_FILE", str(data / "logs" / "cinefin.log"))

    if getattr(sys, "frozen", False):
        os.environ.setdefault("CINEFIN_FRONTEND_BUILD_DIR", str(bundle / "frontend" / "build"))
        os.environ.setdefault("CINEFIN_ASSETS_DIR", str(bundle / "cinefin" / "assets"))
        os.environ.setdefault("CINEFIN_PLUGINS_DIR", str(bundle / "contrib" / "plugins"))
        # Bundled ffmpeg/ffprobe found via shutil.which -> prepend to PATH.
        ffmpeg = bundle / "ffmpeg"
        if ffmpeg.is_dir():
            os.environ["PATH"] = str(ffmpeg) + os.pathsep + os.environ.get("PATH", "")

    (data / "logs").mkdir(parents=True, exist_ok=True)
    _redirect_std_streams(data / "logs" / "cinefin.log")


def _redirect_std_streams(logfile) -> None:
    """A windowed PyInstaller build has sys.stdout/stderr = None, so anything
    that writes to them (Django's migrate output, uvicorn's logs) raises
    AttributeError. Point the missing streams at the log file."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        stream = open(logfile, "a", buffering=1, encoding="utf-8", errors="replace")
    except OSError:
        stream = open(os.devnull, "w")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


# --------------------------------------------------------------------------- #
# serve / migrate — run inside child processes (Django imported here only)
# --------------------------------------------------------------------------- #


def run_migrate() -> int:
    _setup_environment()
    import django
    from django.core.management import call_command

    django.setup()  # sys.argv[1] == "migrate" -> ApiConfig skips background workers
    call_command("migrate", interactive=False, verbosity=1)
    return 0


def run_serve() -> int:
    _setup_environment()
    import django

    django.setup()
    import uvicorn

    from cinefin.asgi import application

    uvicorn.run(application, host=HOST, port=PORT, log_level="info", workers=1)
    return 0


# --------------------------------------------------------------------------- #
# tray — manages the server child; no Django import in this process
# --------------------------------------------------------------------------- #


class ServerController:
    """Owns the `Cinefin.exe serve` child process."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def _spawn(self, mode: str, wait: bool) -> subprocess.Popen:
        # Re-invoke this same executable in the given mode. CREATE_NO_WINDOW keeps
        # the child headless (no console flashes).
        flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
        args = [sys.executable, mode] if getattr(sys, "frozen", False) else [sys.executable, __file__, mode]
        proc = subprocess.Popen(args, creationflags=flags)
        if wait:
            proc.wait()
        return proc

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.running():
                return
            self._spawn("migrate", wait=True)  # ensure schema before serving
            self._proc = self._spawn("serve", wait=False)

    def stop(self) -> None:
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            self._proc = None

    def restart(self) -> None:
        self.stop()
        self.start()


def _make_icon_image(running: bool):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    color = (37, 232, 138, 255) if running else (120, 120, 120, 255)  # green / grey
    d.ellipse((8, 8, 56, 56), fill=color)
    return img


def _startup_registry_key():
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_ALL_ACCESS,
    )


def _run_at_login_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with _startup_registry_key() as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def _set_run_at_login(enable: bool) -> None:
    import winreg

    with _startup_registry_key() as key:
        if enable:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}"')
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


def run_tray() -> int:
    import pystray

    _setup_environment()
    server = ServerController()
    server.start()

    def on_open(icon, item):
        webbrowser.open(URL)

    def on_start(icon, item):
        server.start()
        icon.icon = _make_icon_image(server.running())
        icon.update_menu()

    def on_stop(icon, item):
        server.stop()
        icon.icon = _make_icon_image(server.running())
        icon.update_menu()

    def on_restart(icon, item):
        server.restart()
        icon.icon = _make_icon_image(server.running())
        icon.update_menu()

    def on_open_logs(icon, item):
        os.startfile(str(_data_dir() / "logs"))  # noqa: S606 - Windows shell open

    def on_open_data(icon, item):
        os.startfile(str(_data_dir()))  # noqa: S606

    def on_toggle_login(icon, item):
        _set_run_at_login(not _run_at_login_enabled())

    def on_quit(icon, item):
        server.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: f"Cinefin — {'running' if server.running() else 'stopped'}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Cinefin", on_open, default=True),
        pystray.MenuItem("Start", on_start),
        pystray.MenuItem("Stop", on_stop),
        pystray.MenuItem("Restart", on_restart),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open logs", on_open_logs),
        pystray.MenuItem("Open data folder", on_open_data),
        pystray.MenuItem("Run at login", on_toggle_login, checked=lambda item: _run_at_login_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )
    icon = pystray.Icon(APP_NAME, _make_icon_image(server.running()), APP_NAME, menu)
    icon.run()
    return 0


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "tray"
    if mode == "serve":
        return run_serve()
    if mode == "migrate":
        return run_migrate()
    return run_tray()


if __name__ == "__main__":
    sys.exit(main())
