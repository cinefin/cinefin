"""Non-destructive config validation helpers (paths, API keys, printer).

Every check returns a dict with at least `ok` (bool) and `message`. A failing
check is a result, not an error — the endpoints that expose these answer 200."""

import logging
import os
import socket

import requests

from cinefin.api.models import Settings

logger = logging.getLogger(__name__)

TMDB_BASE_URL = "https://api.themoviedb.org/3"

HTTP_TIMEOUT = 8
TCP_TIMEOUT = 3


def test_tmdb_key(api_key: str | None = None) -> dict:
    """Verify a TMDB API key with a cheap authenticated call (/configuration)."""
    key = (api_key or "").strip() or (Settings.get("trailers.tmdb_api_key") or "").strip()
    if not key:
        return {"ok": False, "message": "No TMDB API key configured"}

    try:
        resp = requests.get(f"{TMDB_BASE_URL}/configuration", params={"api_key": key}, timeout=HTTP_TIMEOUT)
    except requests.exceptions.Timeout:
        return {"ok": False, "message": "TMDB did not respond — try again later"}
    except requests.exceptions.RequestException as exc:
        logger.warning("TMDB key test failed: %s", exc)
        return {"ok": False, "message": "Could not reach TMDB — check your network connection"}

    if resp.status_code == 200:
        return {"ok": True, "message": "TMDB key is valid"}
    if resp.status_code == 401:
        return {"ok": False, "message": "TMDB rejected the key — check it for typos"}
    return {"ok": False, "message": f"TMDB returned HTTP {resp.status_code}"}


def test_ratings_provider(system: str | None = None) -> dict:
    """Lightweight reachability probe of a system's rating provider (not a full lookup)."""
    from cinefin.api import ratings

    system = (system or "").strip() or Settings.get_ratings_system()
    provider = ratings.get_provider(system)
    if provider is None:
        return {"ok": False, "message": f"No rating provider is registered for the {system} system"}
    result = provider.check()
    return {"ok": bool(result.get("ok")), "message": str(result.get("message", ""))}


def test_printer(
    printer_type: str | None = None,
    device: str | None = None,
    host: str | None = None,
    port: int | None = None,
) -> dict:
    """Check the ticket printer per its connection type, without printing."""
    ptype = (printer_type or "").strip() or Settings.get("tickets.printer_type") or "file"
    if ptype not in ("file", "network"):
        return {"ok": False, "message": f"Unknown printer type: {ptype}"}

    if ptype == "network":
        host = (host or "").strip() or (Settings.get("tickets.printer_host") or "").strip()
        if not host:
            return {"ok": False, "message": "No printer host configured"}
        port = port or int(Settings.get("tickets.printer_port") or 9100)
        try:
            with socket.create_connection((host, port), timeout=TCP_TIMEOUT):
                pass
        except OSError as exc:
            logger.warning("Printer TCP probe to %s:%s failed: %s", host, port, exc)
            return {"ok": False, "message": f"Could not connect to {host}:{port} — is the printer exposed there?"}
        return {"ok": True, "message": f"Printer port is reachable at {host}:{port}"}

    device = (device or "").strip() or (Settings.get("tickets.printer_device") or "").strip()
    if not device:
        return {"ok": False, "message": "No printer device configured"}
    if not os.path.exists(device):
        return {"ok": False, "message": f"{device} does not exist — is the printer plugged in?"}
    if os.path.isdir(device):
        return {"ok": False, "message": f"{device} is a directory, not a printer device"}
    if not os.access(device, os.W_OK):
        return {"ok": False, "message": f"{device} exists but is not writable — check permissions"}
    return {"ok": True, "message": f"{device} exists and is writable"}
