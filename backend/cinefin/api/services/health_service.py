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


def _human_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024.0 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def _check(key, label, status, detail, hint=None, action=None):
    """``action`` is an optional {"label", "href"} link to where the fix lives."""
    return {"key": key, "label": label, "status": status, "detail": detail, "hint": hint, "action": action}


# Individual checks: each returns a check dict and must not raise.


def _check_version():
    from cinefin.version import get_version_info

    info = get_version_info()
    kind = "release build" if info.get("is_release") else "development build"
    detail = f"{info.get('version')} ({kind})"
    return _check("version", "Version", "info", detail)


def _check_mpv():
    from cinefin.api.services.playout_agent_service import playout_agent_service

    if not playout_agent_service.is_configured():
        return _check(
            "mpv",
            "MPV player",
            "warn",
            "No playout host configured — add one in Settings > Playout. Playout is unavailable until then.",
        )
    try:
        status = playout_agent_service.get_status()
    except Exception as e:  # noqa: BLE001 — agent down is a normal, non-fatal state
        return _check(
            "mpv",
            "MPV player",
            "warn",
            f"Playout agent unreachable — {e}. Playout is unavailable until it responds.",
        )
    mpv = status.get("mpv") or {}
    if mpv.get("running") or mpv.get("socket_responding"):
        return _check("mpv", "MPV player", "ok", "Player running on the playout host")
    return _check(
        "mpv",
        "MPV player",
        "warn",
        "Playout agent reachable but the player is stopped — start it from Settings > Playout.",
    )


def _check_scheduler():
    from cinefin.api.services import schedule_runner

    status = schedule_runner.runner_status()
    if status.get("running"):
        return _check("scheduler", "Schedule runner", "ok", "Running (heartbeat is fresh)")
    age = status.get("age_seconds")
    if age is not None:
        detail = f"No fresh heartbeat — last seen {age:.0f}s ago"
    else:
        detail = "No heartbeat file — the schedule runner has not started"
    return _check(
        "scheduler",
        "Schedule runner",
        "warn",
        detail,
        "Scheduled screenings will not fire. Restart the app so the runner thread starts.",
    )


def _disk_check(key, label, path, what):
    if not path or not os.path.isdir(path):
        return _check(key, label, "warn", f"{what} path is not a directory: {path}")
    usage = shutil.disk_usage(path)
    free = usage.free
    frac = free / usage.total if usage.total else 0.0
    detail = f"{_human_bytes(free)} free of {_human_bytes(usage.total)} ({frac * 100:.0f}%)"
    if free < _DISK_ERROR_BYTES:
        return _check(key, label, "error", detail, "Free up space now — writes will start failing.")
    if free < _DISK_WARN_BYTES or frac < _DISK_WARN_FRACTION:
        return _check(key, label, "warn", detail, "Running low — consider freeing up space.")
    return _check(key, label, "ok", detail)


def _check_disk_media():
    return _disk_check("disk_media", "Disk space (media)", settings.MEDIA_ROOT, "Media")


def _check_disk_db():
    db_path = connection.settings_dict.get("NAME")
    db_dir = os.path.dirname(db_path) if db_path else None
    return _disk_check("disk_db", "Disk space (database)", db_dir, "Database")


def _check_db():
    db_path = connection.settings_dict.get("NAME")
    if not db_path or not os.path.exists(db_path):
        return _check("db", "Database", "info", "Database file not found on disk")
    # Basename only — never leak the host path into a diagnostic report.
    name = os.path.basename(db_path)
    size = os.path.getsize(db_path)
    return _check("db", "Database", "info", f"{name} ({_human_bytes(size)})")


def _check_media_writable():
    from cinefin.api.utils.media_tree import unwritable_media_subdirs

    unwritable = unwritable_media_subdirs()
    if not unwritable:
        return _check("media_writable", "Media directories", "ok", "All media directories are writable")
    names = ", ".join(os.path.basename(p.rstrip("/")) or p for p in unwritable)
    return _check(
        "media_writable",
        "Media directories",
        "error",
        f"Not writable: {names}. Uploads and generated media will fail.",
        f"Fix ownership, e.g. 'sudo chown -R <app-user> {settings.MEDIA_ROOT}'.",
    )


def _check_printer():
    from cinefin.api.models import Settings
    from cinefin.api.services import config_check_service

    host = (Settings.get("tickets.printer_host") or "").strip()
    device = (Settings.get("tickets.printer_device") or "").strip()
    # Nothing configured — ticketing is optional, so keep it non-alarming.
    if not host and not device:
        return _check(
            "printer",
            "Ticket printer",
            "info",
            "Not configured — not needed unless you print tickets",
        )
    result = config_check_service.test_printer()
    if result.get("ok"):
        return _check("printer", "Ticket printer", "ok", result.get("message", "Printer is reachable"))
    # Unreachable at the shipped-default device just means no printer was ever
    # set up — don't warn a fresh install about optional hardware.
    if not host and device == Settings.DEFAULTS["tickets"]["printer_device"]:
        return _check(
            "printer",
            "Ticket printer",
            "info",
            "Not configured — not needed unless you print tickets",
        )
    return _check(
        "printer",
        "Ticket printer",
        "warn",
        result.get("message", "Printer is configured but not reachable"),
        "Only affects ticket printing. Check the printer connection in Settings.",
        action={"label": "Open ticket settings", "href": "/app/settings"},
    )


def _check_auth():
    from cinefin.api.services.auth_service import auth_is_active

    if auth_is_active():
        return _check("auth", "Authentication", "ok", "Authentication is on")
    return _check(
        "auth",
        "Authentication",
        "warn",
        "Authentication is OFF — anyone on the network can control this cinema",
        "Turn on authentication in Settings → Security to require a login.",
        action={"label": "Open security settings", "href": "/app/settings"},
    )


def _check_ratings():
    from cinefin.api import ratings
    from cinefin.api.models import Settings

    system = Settings.get_ratings_system()
    provider = ratings.get_provider(system)
    if provider is None:
        return _check(
            "ratings",
            "Certificate lookups",
            "warn",
            f"No rating provider is registered for the {system} system",
            action={"label": "Open cinema settings", "href": "/app/settings"},
        )
    if not Settings.get("trailers.rating_lookup_enabled", True):
        return _check(
            "ratings",
            "Certificate lookups",
            "info",
            "Certificate lookups are turned off in Settings → Trailers",
        )
    return _check("ratings", "Certificate lookups", "info", f"{system} certificates via {provider.display_name}")


def _check_sync_sources():
    from cinefin.api.models import SyncSource

    sources = list(SyncSource.objects.all())
    if not sources:
        return _check("sync_sources", "Sync sources", "info", "No sync sources configured")

    from cinefin.api.models import Job

    worst = "info"
    lines = []
    for src in sources:
        last = None
        result = "never run"
        job = Job.sync.filter(source=src).order_by("-created_at").first()
        if job is not None:
            last = job.finished_at or job.created_at
            if job.state in (Job.STATE_FAILED, Job.STATE_CANCELLED):
                result = f"last run {job.state}"
                worst = "warn"
            elif job.state == Job.STATE_PARTIAL:
                result = "last run partial"
                worst = "warn"
            elif job.state == Job.STATE_SUCCESS:
                result = "last run OK"
            else:
                result = f"last run {job.state}"
        elif src.last_sync:
            last = src.last_sync
            result = "last synced"
        when = last.strftime("%Y-%m-%d %H:%M") if last else "never"
        lines.append(f"{src.name}: {result} ({when})")

    detail = f"{len(sources)} configured — " + "; ".join(lines)
    hint = "A source's last run did not succeed — check the Sync page." if worst == "warn" else None
    action = {"label": "Open the sync page", "href": "/app/sync"} if worst == "warn" else None
    return _check("sync_sources", "Sync sources", worst, detail, hint, action)


# newest local paths per media model to spot-check; bounded for speed
_MEDIA_FILE_SAMPLE = 250


def _check_media_files():
    from cinefin.api.models import Bumper, Movie

    sampled = []
    for model in (Movie, Bumper):
        rows = (
            model.objects.exclude(file_path="").order_by("-id").values_list("title", "file_path")[:_MEDIA_FILE_SAMPLE]
        )
        # Streaming URLs play over HTTP — there is no file on disk to check.
        sampled.extend((t, p) for t, p in rows if not p.startswith(("http://", "https://")))

    if not sampled:
        return _check("media_files", "Media files", "info", "No local media file paths to check")

    missing = [t for t, p in sampled if not os.path.exists(p)]
    if not missing:
        return _check("media_files", "Media files", "ok", f"All {len(sampled)} checked file paths exist on disk")
    names = ", ".join(missing[:3]) + (f" (+{len(missing) - 3} more)" if len(missing) > 3 else "")
    return _check(
        "media_files",
        "Media files",
        "warn",
        f"{len(missing)} of {len(sampled)} checked files are missing on disk: {names}",
        "Files may have moved or a mount is absent — check the source's path mappings.",
        action={"label": "Open the sync page", "href": "/app/sync"},
    )


_CHECKS = (
    _check_version,
    _check_mpv,
    _check_scheduler,
    _check_disk_media,
    _check_disk_db,
    _check_db,
    _check_media_writable,
    _check_printer,
    _check_auth,
    _check_ratings,
    _check_sync_sources,
    _check_media_files,
)

# labels keyed by function name, so a raising check still reports a sensible one
_CHECK_LABELS = {
    "_check_version": ("version", "Version"),
    "_check_mpv": ("mpv", "MPV player"),
    "_check_scheduler": ("scheduler", "Schedule runner"),
    "_check_disk_media": ("disk_media", "Disk space (media)"),
    "_check_disk_db": ("disk_db", "Disk space (database)"),
    "_check_db": ("db", "Database"),
    "_check_media_writable": ("media_writable", "Media directories"),
    "_check_printer": ("printer", "Ticket printer"),
    "_check_auth": ("auth", "Authentication"),
    "_check_ratings": ("ratings", "Certificate lookups"),
    "_check_sync_sources": ("sync_sources", "Sync sources"),
    "_check_media_files": ("media_files", "Media files"),
}


def run_check(key: str) -> dict | None:
    """Re-run one check by key; None for an unknown key. Degrades on raise."""
    for fn in _CHECKS:
        fn_key, label = _CHECK_LABELS.get(fn.__name__, (fn.__name__, fn.__name__))
        if fn_key != key:
            continue
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - a failing check must not raise
            logger.exception("Health check %s failed", fn.__name__)
            return _check(fn_key, label, "error", f"Check failed: {exc}")
    return None


def collect_health() -> dict:
    """Run every check and return the report; a raising check degrades to error."""
    from cinefin.version import get_version

    checks = []
    for fn in _CHECKS:
        try:
            checks.append(fn())
        except Exception as exc:  # noqa: BLE001 - a failing check must not break the report
            logger.exception("Health check %s failed", fn.__name__)
            key, label = _CHECK_LABELS.get(fn.__name__, (fn.__name__, fn.__name__))
            checks.append(_check(key, label, "error", f"Check failed: {exc}"))

    overall = "ok"
    for c in checks:
        if _STATUS_RANK.get(c["status"], 0) > _STATUS_RANK.get(overall, 0):
            overall = "error" if _STATUS_RANK[c["status"]] == 2 else "warn"

    try:
        version = get_version()
    except Exception:  # noqa: BLE001
        version = "unknown"

    return {
        "overall": overall,
        "version": version,
        "checked_at": timezone.now().isoformat(),
        "checks": checks,
    }
