"""The `cinefin` command: run the Cinefin server.

    cinefin [serve] [--data-dir DIR] [--listen HOST:PORT] [--public-url URL]
                    [--log-level LEVEL] [--log-file PATH] [--no-migrate]
    cinefin migrate [--data-dir DIR]
    cinefin info    [serve options]   # the resolved values and where each came from
    cinefin manage  <command> [args]  # any Django management command
    cinefin --version

Every option maps onto an environment variable (named in --help). A flag wins
over the variable, which wins over the default. The chosen values are written
back into the environment, so settings.py and child processes see the same
thing. The SPA build and collected static ship inside the wheel, so no source
tree is needed at runtime.
"""

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = PACKAGE_DIR.parent  # backend/ in a source checkout; site-packages in a wheel install
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8000
WILDCARD_HOSTS = {"0.0.0.0", "::", ""}
LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

Resolved = dict[str, tuple[str, str]]  # name -> (value, where it came from)


def resolve_data_dir(flag: str | None = None) -> tuple[Path, str]:
    """The data folder and where the choice came from.

    The one place this is decided: settings.py, the Windows tray and every
    subcommand call it. A source checkout (backend/manage.py next to the
    package) keeps its data in <repo>/userdata so `manage.py` and `cinefin`
    share one database; a wheel install has no manage.py and uses the
    per-user platform folder.
    """
    if flag:
        return Path(flag).expanduser().resolve(), "--data-dir"
    if os.environ.get("CINEFIN_USERDATA_DIR"):
        return Path(os.environ["CINEFIN_USERDATA_DIR"]), "CINEFIN_USERDATA_DIR"
    if (BACKEND_DIR / "manage.py").is_file() and (BACKEND_DIR / "pyproject.toml").is_file():
        return BACKEND_DIR.parent / "userdata", "source checkout"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Cinefin", "platform default"
    xdg = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    return Path(xdg) / "cinefin", "platform default"


def parse_listen(value: str) -> tuple[str, int]:
    """`HOST:PORT`, `[IPV6]:PORT`, `:PORT` or a bare `PORT`."""
    host, _, port = value.rpartition(":")
    host = host.removeprefix("[").removesuffix("]") or DEFAULT_HOST
    if not port.isdigit() or not 0 < int(port) < 65536:
        raise argparse.ArgumentTypeError(f"not HOST:PORT: {value!r}")
    return host, int(port)


def _hostport(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def lan_address() -> str:
    """This machine's default-route IPv4 address, or 127.0.0.1 without one.

    Connecting a UDP socket sends nothing; it only makes the kernel pick the
    outgoing interface, whose address is what other machines on the LAN use.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))  # TEST-NET-1: any routable address will do
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def default_public_url(host: str, port: int) -> str:
    """The address players and browsers should use when none is configured."""
    return "http://" + _hostport(lan_address() if host in WILDCARD_HOSTS else host, port)


def _pick(flag_value, flag: str, env: str, default: str, default_source: str = "default") -> tuple[str, str]:
    if flag_value is not None:
        return str(flag_value), flag
    if os.environ.get(env):
        return os.environ[env], env
    return default, default_source


def resolve(args: argparse.Namespace) -> Resolved:
    """Every runtime value as (value, source): flag, then env, then default."""
    data, data_src = resolve_data_dir(getattr(args, "data_dir", None))
    cfg = {"data folder": (str(data), data_src)}
    cfg["database"] = _pick(None, "", "SQLITE_PATH", str(data / "db.sqlite3"), "data folder")
    cfg["media folder"] = _pick(None, "", "CINEFIN_USERMEDIA_DIR", str(data / "media"), "data folder")

    if getattr(args, "listen", None):
        (host, port), listen_src = args.listen, "--listen"
    else:
        host = os.environ.get("CINEFIN_HOST") or DEFAULT_HOST
        port = int(os.environ.get("CINEFIN_PORT") or DEFAULT_PORT)
        listen_src = "/".join(v for v in ("CINEFIN_HOST", "CINEFIN_PORT") if os.environ.get(v)) or "default"
    cfg["listen"] = (_hostport(host, port), listen_src)

    url_src = "LAN address" if host in WILDCARD_HOSTS else "listen address"
    public = default_public_url(host, port)
    cfg["public URL"] = _pick(getattr(args, "public_url", None), "--public-url", "CINEFIN_SERVER_URL", public, url_src)
    cfg["log level"] = _pick(getattr(args, "log_level", None), "--log-level", "CINEFIN_LOG_LEVEL", "INFO")
    cfg["log file"] = _pick(getattr(args, "log_file", None), "--log-file", "CINEFIN_LOG_FILE", "", "off")
    return cfg


def apply_env(cfg: Resolved) -> None:
    """Hand the resolved values to Django (settings.py reads the environment)."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cinefin.settings")
    host, port = parse_listen(cfg["listen"][0])
    os.environ["CINEFIN_HOST"], os.environ["CINEFIN_PORT"] = host, str(port)
    for key, env in [
        ("data folder", "CINEFIN_USERDATA_DIR"),
        ("public URL", "CINEFIN_SERVER_URL"),
        ("log level", "CINEFIN_LOG_LEVEL"),
        ("log file", "CINEFIN_LOG_FILE"),
    ]:
        if cfg[key][0]:
            os.environ[env] = cfg[key][0]
    Path(cfg["data folder"][0]).mkdir(parents=True, exist_ok=True)
    spa = PACKAGE_DIR / "spa"  # the SPA build bundled in the wheel
    if spa.is_dir():
        os.environ.setdefault("CINEFIN_FRONTEND_BUILD_DIR", str(spa))


def _version() -> str:
    from cinefin.version import get_version

    return get_version()


def _describe(cfg: Resolved, keys: list[str]) -> str:
    return "\n".join(f"  {k:<13} {cfg[k][0] or '-'}  ({cfg[k][1]})" for k in keys)


def cmd_info(args) -> int:
    cfg = resolve(args)
    print(f"Cinefin {_version()}")
    print(_describe(cfg, ["data folder", "database", "media folder", "listen", "public URL", "log level", "log file"]))
    print("A server URL saved under Settings > Playout overrides the public URL for streams.")
    return 0


def cmd_migrate(args) -> int:
    # argv[1] == "migrate", so ApiConfig skips the background workers.
    apply_env(resolve(args))
    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=1)
    return 0


def cmd_manage(args) -> int:
    apply_env(resolve(args))
    from django.core.management import execute_from_command_line

    # ApiConfig reads sys.argv[1] to skip the workers for one-shot commands.
    sys.argv = ["cinefin manage", *args.args]
    execute_from_command_line(sys.argv)
    return 0


def _saved_server_url() -> str:
    try:
        from cinefin.api.models import Settings

        return (Settings.get("playout.server_url") or "").strip()
    except Exception:  # noqa: BLE001 - informational only
        return ""


def cmd_serve(args) -> int:
    cfg = resolve(args)
    apply_env(cfg)
    if not args.no_migrate:
        # In a child: here, django.setup() starts the sync engine and schedule
        # runner, which must not race the schema change. Pass our streams on:
        # on Windows a child given none has no stdout at all (see main()), and
        # its output, errors included, would be lost instead of reaching the log.
        rc = subprocess.run(
            [sys.executable, "-m", "cinefin.cli", "migrate"], stdout=sys.stdout, stderr=sys.stderr
        ).returncode
        if rc:
            print(f"cinefin: migrating the database failed (exit {rc}); not starting.", file=sys.stderr)
            return rc

    import django

    django.setup()
    import uvicorn

    from cinefin.asgi import application

    public = cfg["public URL"][0].rstrip("/")
    saved = _saved_server_url()
    print(f"Cinefin {_version()}")
    print(_describe(cfg, ["data folder", "listen", "public URL"]))
    print(f"  Open {public}/app/ in a browser; players stream from {saved or public}.")
    if saved:
        print("  (That stream address is saved under Settings > Playout and overrides the public URL.)")
    sys.stdout.flush()

    host, port = parse_listen(cfg["listen"][0])
    uvicorn.run(
        application,
        host=host,
        port=port,
        log_level=cfg["log level"][0].lower() if cfg["log level"][0].upper() in LOG_LEVELS else "info",
        # Per-request access log is noise by default; CINEFIN_ACCESS_LOG=1 restores it.
        access_log=os.environ.get("CINEFIN_ACCESS_LOG") == "1",
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    data = argparse.ArgumentParser(add_help=False)
    data.add_argument(
        "--data-dir",
        metavar="DIR",
        help="folder for the database, media and secret key (env CINEFIN_USERDATA_DIR; default <repo>/userdata "
        "in a source checkout, else ~/.local/share/cinefin or %%LOCALAPPDATA%%\\Cinefin)",
    )
    server = argparse.ArgumentParser(add_help=False)
    server.add_argument(
        "--listen",
        metavar="HOST:PORT",
        type=parse_listen,
        help=f"address to bind, e.g. 127.0.0.1:8000 or [::]:8000 (env CINEFIN_HOST and CINEFIN_PORT; "
        f"default {DEFAULT_HOST}:{DEFAULT_PORT})",
    )
    server.add_argument(
        "--public-url",
        metavar="URL",
        help="address players and browsers use to reach this server (env CINEFIN_SERVER_URL; default "
        "http://<LAN address>:<port> when listening on all interfaces, else the listen address)",
    )
    server.add_argument(
        "--log-level", type=str.upper, choices=LOG_LEVELS, help="log level (env CINEFIN_LOG_LEVEL; default INFO)"
    )
    server.add_argument(
        "--log-file", metavar="PATH", help="also write a rotating logfile here (env CINEFIN_LOG_FILE; default off)"
    )

    parser = argparse.ArgumentParser(prog="cinefin", description="Run the Cinefin server.")
    parser.add_argument("--version", action="version", version=f"cinefin {_version()}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    serve = sub.add_parser("serve", parents=[data, server], help="migrate, then serve (the default)")
    serve.add_argument("--no-migrate", action="store_true", help="do not apply database migrations first")
    serve.set_defaults(func=cmd_serve)
    migrate = sub.add_parser("migrate", parents=[data], help="apply database migrations and exit")
    migrate.set_defaults(func=cmd_migrate)
    info = sub.add_parser("info", parents=[data, server], help="show the resolved settings and where each came from")
    info.set_defaults(func=cmd_info)
    manage = sub.add_parser("manage", parents=[data], help="run a Django management command, e.g. createsuperuser")
    manage.add_argument("args", nargs=argparse.REMAINDER, help="the command and its arguments")
    manage.set_defaults(func=cmd_manage)
    return parser


def main(argv: list[str] | None = None) -> int:
    # Under pythonw.exe (the Windows tray) a process given no handles has
    # sys.stdout/stderr = None, and Django's commands crash on their first write.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115 - lives as long as the process
    argv = sys.argv[1:] if argv is None else argv
    # `cinefin` alone, or with serve options only, means `cinefin serve`.
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv = ["serve", *argv]
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
