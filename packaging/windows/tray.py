"""Cinefin Windows tray.

Ships in the installer next to the bundled Python. The Start-Menu shortcut runs
``python\\pythonw.exe tray.py``; the tray manages ``cinefin.cli serve`` as a
child of that same Python (so it uses the pip-installed cinefin + all its deps —
no freezing). The server's output is redirected to the log file, which also
sidesteps the windowed-process ``sys.stdout is None`` problem.
"""

import os
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

APP_NAME = "Cinefin"
HOST = "127.0.0.1"
PORT = os.environ.get("CINEFIN_PORT", "8000")
URL = f"http://{HOST}:{PORT}/app/"

HERE = Path(__file__).resolve().parent  # the install dir
PYW = HERE / "python" / "pythonw.exe"  # bundled interpreter (no console)
FFMPEG = HERE / "ffmpeg"
CREATE_NO_WINDOW = 0x08000000


def _data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = Path(base) / APP_NAME
    (d / "logs").mkdir(parents=True, exist_ok=True)
    return d


def _child_env() -> dict:
    env = dict(os.environ)
    env["CINEFIN_USERDATA_DIR"] = str(_data_dir())
    env.setdefault("CINEFIN_HOST", "0.0.0.0")  # reachable by the kiosk / playout host
    env["CINEFIN_PORT"] = str(PORT)
    if FFMPEG.is_dir():
        env["PATH"] = str(FFMPEG) + os.pathsep + env.get("PATH", "")
    return env


class Server:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.running():
                return
            log = open(_data_dir() / "logs" / "server.log", "a", buffering=1, encoding="utf-8", errors="replace")
            # cli.serve migrates then runs uvicorn; redirecting stdout/stderr to
            # the log gives the child real streams (no None) and captures output.
            self._proc = subprocess.Popen(
                [str(PYW), "-m", "cinefin.cli", "serve"],
                env=_child_env(),
                stdout=log,
                stderr=log,
                creationflags=CREATE_NO_WINDOW,
            )

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


def _icon_image(running: bool):
    """The Cinefin logo with a small status dot (green = running, grey = stopped)."""
    from PIL import Image, ImageDraw

    dot = (37, 232, 138, 255) if running else (120, 120, 120, 255)
    logo = HERE / "cinefin.ico"
    if logo.exists():
        try:
            img = Image.open(logo).convert("RGBA").resize((64, 64))
            ImageDraw.Draw(img).ellipse((45, 45, 63, 63), fill=dot, outline=(0, 0, 0, 255))
            return img
        except Exception:
            pass
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).ellipse((8, 8, 56, 56), fill=dot)
    return img


def _run_key():
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS
    )


def _login_enabled() -> bool:
    import winreg

    try:
        with _run_key() as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except FileNotFoundError:
        return False


def _set_login(enable: bool) -> None:
    import winreg

    with _run_key() as k:
        if enable:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{PYW}" "{HERE / "tray.py"}"')
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


def main() -> None:
    import pystray

    server = Server()
    server.start()

    def refresh(icon):
        icon.icon = _icon_image(server.running())
        icon.update_menu()

    menu = pystray.Menu(
        pystray.MenuItem(lambda i: f"Cinefin — {'running' if server.running() else 'stopped'}", None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Cinefin", lambda i, item: webbrowser.open(URL), default=True),
        pystray.MenuItem("Start", lambda i, item: (server.start(), refresh(i))),
        pystray.MenuItem("Stop", lambda i, item: (server.stop(), refresh(i))),
        pystray.MenuItem("Restart", lambda i, item: (server.restart(), refresh(i))),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open logs", lambda i, item: os.startfile(_data_dir() / "logs")),
        pystray.MenuItem("Open data folder", lambda i, item: os.startfile(_data_dir())),
        pystray.MenuItem("Run at login", lambda i, item: _set_login(not _login_enabled()), checked=lambda i: _login_enabled()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda i, item: (server.stop(), i.stop())),
    )
    pystray.Icon(APP_NAME, _icon_image(server.running()), APP_NAME, menu).run()


if __name__ == "__main__":
    # pythonw has no console -> sys.stdout/stderr are None; guard the tray itself.
    if sys.stdout is None or sys.stderr is None:
        _log = open(_data_dir() / "logs" / "tray.log", "a", buffering=1, encoding="utf-8", errors="replace")
        sys.stdout = sys.stdout or _log
        sys.stderr = sys.stderr or _log
    main()
