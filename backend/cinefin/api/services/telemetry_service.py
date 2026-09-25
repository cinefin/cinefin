"""Opt-in anonymous telemetry — a daily Aptabase heartbeat.

Off by default. When enabled (Settings → Telemetry, or the setup wizard) a
background thread sends one ``heartbeat`` event per day carrying the version
and *config shape* only — which integration types exist, not their URLs,
credentials, paths, titles or counts. The single per-install identifier is a
random UUID minted on first opt-in (``telemetry.install_id``); a disabled
install has no identifier at all.

Aptabase ingestion: ``POST {host}/api/v0/events`` with an ``App-Key`` header and
a JSON list of events (max 25). Both cloud and self-hosted instances are
supported — ``telemetry.host`` points wherever you run the receiver.
See docs/TELEMETRY.md for the exact payload.
"""

import logging
import os
import platform
import random
import threading
import time
import uuid
from datetime import UTC, datetime

import django
import requests
from django.conf import settings as django_settings
from django.db import close_old_connections

from cinefin.api.models import Settings
from cinefin.version import get_channel, get_version

logger = logging.getLogger(__name__)

SDK_VERSION = "cinefin-py/1"
INTERVAL_SECONDS = 86_400  # one heartbeat per day
CHECK_SECONDS = 3_600  # wake hourly to see if a day has elapsed
INITIAL_DELAY = 60  # let the app settle before the first check
HTTP_TIMEOUT = 8

_thread: threading.Thread | None = None
_started = False
_lock = threading.Lock()
_stop = threading.Event()


def is_enabled() -> bool:
    return bool(Settings.get("telemetry.enabled"))


def _target() -> tuple[str, str] | None:
    """(host, app_key) when fully configured, else None."""
    host = (Settings.get("telemetry.host") or "").strip().rstrip("/")
    app_key = (Settings.get("telemetry.app_key") or "").strip()
    return (host, app_key) if host and app_key else None


def ensure_install_id() -> str:
    """Return the install UUID, minting it on first call. Only ever called on opt-in."""
    install_id = (Settings.get("telemetry.install_id") or "").strip()
    if not install_id:
        install_id = uuid.uuid4().hex
        Settings.set("telemetry.install_id", install_id)
    return install_id


def _deployment() -> str:
    module = os.environ.get("DJANGO_SETTINGS_MODULE", "")
    if module.endswith("settings_docker") or os.path.exists("/.dockerenv"):
        return "docker"
    return "baremetal"


def _config_shape() -> dict:
    """Anonymous config props: which integrations exist, never their URLs/secrets/counts."""
    from cinefin import plugins
    from cinefin.api.models import PlayoutHost, SyncSource

    source_types = sorted(SyncSource.objects.values_list("sync_type", flat=True).distinct())
    active_host = PlayoutHost.get_active()
    enabled_plugins = sorted(p.id for p in plugins.list_providers() if plugins.is_enabled(p.id))

    return {
        "channel": get_channel(),
        "sync_source_types": ",".join(source_types),
        "playout_kind": active_host.kind if active_host else "none",
        "ratings_system": Settings.get_ratings_system(),
        "auth_enabled": bool(Settings.get("security.auth_enabled")),
        "plugins_enabled": ",".join(enabled_plugins),
        "python": platform.python_version(),
        "django": django.get_version(),
    }


def build_event() -> dict:
    """One Aptabase event describing this install anonymously."""
    now = datetime.now(UTC)
    session_id = f"{int(now.timestamp())}{random.randint(10_000_000, 99_999_999)}"
    return {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "sessionId": session_id,
        "eventName": "heartbeat",
        "systemProps": {
            "locale": "",
            "osName": platform.system(),
            "osVersion": platform.release(),
            "deviceModel": _deployment(),
            "isDebug": bool(django_settings.DEBUG),
            "appVersion": get_version(),
            "sdkVersion": SDK_VERSION,
        },
        "props": {"install_id": ensure_install_id(), **_config_shape()},
    }


def send() -> bool:
    """Send a heartbeat now. Returns True on success. Never raises."""
    if not is_enabled():
        return False
    target = _target()
    if target is None:
        return False
    host, app_key = target
    try:
        resp = requests.post(
            f"{host}/api/v0/events",
            json=[build_event()],
            headers={"App-Key": app_key, "Content-Type": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
        if resp.status_code >= 400:
            logger.warning("Telemetry send got HTTP %s", resp.status_code)
            return False
        return True
    except requests.RequestException as e:
        logger.debug("Telemetry send failed: %s", e)
        return False


def _send_if_due() -> None:
    if not is_enabled() or _target() is None:
        return
    last = Settings.get("telemetry.last_sent") or 0
    if time.time() - last < INTERVAL_SECONDS:
        return
    if send():
        Settings.set("telemetry.last_sent", int(time.time()))


def start():
    """Start the daily heartbeat thread once per process (idempotent)."""
    global _thread, _started
    with _lock:
        if _started:
            return
        _started = True
        _stop.clear()
        _thread = threading.Thread(target=_run_loop, name="telemetry", daemon=True)
        _thread.start()


def stop():
    _stop.set()


def _run_loop():
    if _stop.wait(INITIAL_DELAY):
        return
    while not _stop.is_set():
        try:
            _send_if_due()
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("Telemetry tick error")
        finally:
            close_old_connections()
        _stop.wait(CHECK_SECONDS)
