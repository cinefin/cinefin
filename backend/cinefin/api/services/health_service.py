"""System health / diagnostics — backs GET /api/v2/system/health and /health/.

Every check is wrapped so one failing check can never break the whole report;
nothing here writes, connects destructively, or leaks host paths.
"""

import logging
import os
import shutil

from django.conf import settings
from django.db import connection
from django.utils import timezone

logger = logging.getLogger(__name__)

# worst-status ordering: info/ok both "fine", warn a nudge, error the loudest
_STATUS_RANK = {"info": 0, "ok": 0, "warn": 1, "error": 2}

_DISK_WARN_BYTES = 2 * 1024**3  # ~2 GB
_DISK_ERROR_BYTES = 200 * 1024**2  # ~200 MB
_DISK_WARN_FRACTION = 0.10  # 10% free

# Where each check's fix lives. Every check links there, whatever its status.
_FIX = {
    "mpv": ("Open playout settings", "/app/settings?tab=playout"),
    "scheduler": ("Open schedules", "/app/schedules"),
    "disk_media": ("Open the trailer library", "/app/trailers"),
    "disk_db": ("Open backup & restore", "/app/settings?tab=backup"),
    "db": ("Open backup & restore", "/app/settings?tab=backup"),
    "media_writable": ("Open user media", "/app/media"),
    "printer": ("Open printer settings", "/app/settings?tab=tickets&view=printer"),
    "auth": ("Open security settings", "/app/settings?tab=security"),
    "ratings": ("Open theater settings", "/app/settings?tab=cinema"),
    "sync_sources": ("Open library source", "/app/settings?tab=library"),
}

# (key, label, check) in report order; each check returns (status, detail[, hint]).
_CHECKS = []


def _human_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def _check(key, label, status, detail, hint=None):
    fix = _FIX.get(key)
    action = {"label": fix[0], "href": fix[1]} if fix else None
    return {"key": key, "label": label, "status": status, "detail": detail, "hint": hint, "action": action}


def _health_check(key, label):
    def register(fn):
        _CHECKS.append((key, label, fn))
        return fn

    return register


@_health_check("version", "Version")
def _check_version():
    from cinefin.version import get_version_info

    info = get_version_info()
    kind = "release build" if info.get("is_release") else "development build"
    return "info", f"{info.get('version')} ({kind})"


@_health_check("mpv", "MPV player")
def _check_mpv():
    from cinefin.api.services.playout_agent_service import playout_agent_service

    if not playout_agent_service.is_configured():
        return "warn", "No playout host configured — add one in Settings → Playout. Playout is unavailable until then."
    try:
        status = playout_agent_service.get_status()
    except Exception as e:  # noqa: BLE001 — agent down is a normal, non-fatal state
        return "warn", f"Playout agent unreachable — {e}. Playout is unavailable until it responds."
    mpv = status.get("mpv") or {}
    if mpv.get("running") or mpv.get("socket_responding"):
        return "ok", "Player running on the playout host"
    return "warn", "Playout agent reachable but the player is stopped — start it from Settings → Playout."


@_health_check("scheduler", "Schedule runner")
def _check_scheduler():
    from cinefin.api.services import schedule_runner

    status = schedule_runner.runner_status()
    if status.get("running"):
        return "ok", "Running (heartbeat is fresh)"
    age = status.get("age_seconds")
    detail = (
        f"No fresh heartbeat — last seen {age:.0f}s ago"
        if age is not None
        else "No heartbeat file — the schedule runner has not started"
    )
    return "warn", detail, "Scheduled screenings will not fire. Restart the app so the runner thread starts."


def _disk_check(path, what):
    if not path or not os.path.isdir(path):
        return "warn", f"{what} path is not a directory: {path}"
    usage = shutil.disk_usage(path)
    free = usage.free
    frac = free / usage.total if usage.total else 0.0
    detail = f"{_human_bytes(free)} free of {_human_bytes(usage.total)} ({frac * 100:.0f}%)"
    if free < _DISK_ERROR_BYTES:
        return "error", detail, "Free up space now — writes will start failing."
    if free < _DISK_WARN_BYTES or frac < _DISK_WARN_FRACTION:
        return "warn", detail, "Running low — consider freeing up space."
    return "ok", detail


@_health_check("disk_media", "Disk space (media)")
def _check_disk_media():
    return _disk_check(settings.MEDIA_ROOT, "Media")


@_health_check("disk_db", "Disk space (database)")
def _check_disk_db():
    db_path = connection.settings_dict.get("NAME")
    return _disk_check(os.path.dirname(db_path) if db_path else None, "Database")


@_health_check("db", "Database")
def _check_db():
    db_path = connection.settings_dict.get("NAME")
    if not db_path or not os.path.exists(db_path):
        return "info", "Database file not found on disk"
    # Basename only — never leak the host path into a diagnostic report.
    return "info", f"{os.path.basename(db_path)} ({_human_bytes(os.path.getsize(db_path))})"


@_health_check("media_writable", "Media directories")
def _check_media_writable():
    from cinefin.api.utils.media_tree import unwritable_media_subdirs

    unwritable = unwritable_media_subdirs()
    if not unwritable:
        return "ok", "All media directories are writable"
    names = ", ".join(os.path.basename(p.rstrip("/")) or p for p in unwritable)
    return (
        "error",
        f"Not writable: {names}. Uploads and generated media will fail.",
        f"Fix ownership, e.g. 'sudo chown -R <app-user> {settings.MEDIA_ROOT}'.",
    )


@_health_check("printer", "Ticket printer")
def _check_printer():
    from cinefin.api.models import Settings
    from cinefin.api.services import config_check_service

    not_configured = ("info", "Not configured — not needed unless you print tickets")
    host = (Settings.get("tickets.printer_host") or "").strip()
    device = (Settings.get("tickets.printer_device") or "").strip()
    if not host and not device:
        return not_configured
    result = config_check_service.test_printer()
    if result.get("ok"):
        return "ok", result.get("message", "Printer is reachable")
    # Unreachable at the shipped-default device just means no printer was ever
    # set up — don't warn a fresh install about optional hardware.
    if not host and device == Settings.DEFAULTS["tickets"]["printer_device"]:
        return not_configured
    return (
        "warn",
        result.get("message", "Printer is configured but not reachable"),
        "Only affects ticket printing. Check the printer connection in Settings → Tickets → Printer.",
    )


@_health_check("auth", "Authentication")
def _check_auth():
    from cinefin.api.services.auth_service import auth_is_active

    if auth_is_active():
        return "ok", "Authentication is on"
    return (
        "warn",
        "Authentication is OFF — anyone on the network can control this cinema",
        "Turn on authentication in Settings → Security to require a login.",
    )


@_health_check("ratings", "Certificate lookups")
def _check_ratings():
    from cinefin.api import ratings
    from cinefin.api.models import Settings

    system = Settings.get_ratings_system()
    provider = ratings.get_provider(system)
    if provider is None:
        return "warn", f"No rating provider is registered for the {system} system"
    if not Settings.get("trailers.rating_lookup_enabled", True):
        return "info", "Certificate lookups for trailers are turned off"
    return "info", f"{system} certificates via {provider.display_name}"


@_health_check("sync_sources", "Sync sources")
def _check_sync_sources():
    from cinefin.api.models import Job, SyncSource

    sources = list(SyncSource.objects.all())
    if not sources:
        return "info", "No sync sources configured"

    worst = "info"
    lines = []
    for src in sources:
        last = None
        result = "never run"
        job = Job.sync.filter(source=src).order_by("-created_at").first()
        if job is not None:
            last = job.finished_at or job.created_at
            result = f"last run {job.state}"
            if job.state in (Job.STATE_FAILED, Job.STATE_CANCELLED, Job.STATE_PARTIAL):
                worst = "warn"
            if job.state == Job.STATE_SUCCESS:
                result = "last run OK"
        elif src.last_sync:
            last = src.last_sync
            result = "last synced"
        when = last.strftime("%Y-%m-%d %H:%M") if last else "never"
        lines.append(f"{src.name}: {result} ({when})")

    detail = f"{len(sources)} configured — " + "; ".join(lines)
    hint = "A source's last run did not succeed — check Settings → Library source." if worst == "warn" else None
    return worst, detail, hint


def _run(key, label, fn):
    try:
        return _check(key, label, *fn())
    except Exception as exc:  # noqa: BLE001 - a failing check must not break the report
        logger.exception("Health check %s failed", fn.__name__)
        return _check(key, label, "error", f"Check failed: {exc}")


def run_check(key: str) -> dict | None:
    """Re-run one check by key; None for an unknown key."""
    return next((_run(*c) for c in _CHECKS if c[0] == key), None)


def collect_health() -> dict:
    """Run every check and return the report."""
    from cinefin.version import get_version

    checks = [_run(*c) for c in _CHECKS]
    worst = max((_STATUS_RANK.get(c["status"], 0) for c in checks), default=0)
    try:
        version = get_version()
    except Exception:  # noqa: BLE001
        version = "unknown"
    return {
        "overall": ("ok", "warn", "error")[worst],
        "version": version,
        "checked_at": timezone.now().isoformat(),
        "checks": checks,
    }
