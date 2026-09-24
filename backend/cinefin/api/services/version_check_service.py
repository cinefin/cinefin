"""Best-effort "update available" check against the release host's API.

Never raises (chrome must not break a page load), only nags real release builds,
and caches results in-process with a TTL."""

import re
import threading
import time

import requests
from django.conf import settings
from django.utils import timezone

from cinefin.api.models import Settings
from cinefin.version import get_version_info

_CACHE_TTL = 6 * 60 * 60

# Must be short — this runs inline on a page fetch path.
_HTTP_TIMEOUT = 3

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")

_lock = threading.Lock()
_cache = {"expires_at": 0.0, "result": None}


def _parse_semver(tag):
    if not tag:
        return None
    cleaned = tag.strip().lstrip("vV")
    m = _SEMVER_RE.match(cleaned)
    if not m:
        return None
    return tuple(int(part) for part in m.groups())


def _latest_release_url():
    # GitHub and Gitea expose the same fields at different paths; GitHub via api.github.com, else Gitea.
    host = getattr(settings, "CINEFIN_UPDATE_HOST", "https://github.com").rstrip("/")
    repo = getattr(settings, "CINEFIN_UPDATE_REPO", "cinefin-dev/cinefin").strip("/")
    if "github.com" in host:
        return f"https://api.github.com/repos/{repo}/releases/latest"
    return f"{host}/api/v1/repos/{repo}/releases/latest"


def _fetch_latest_release():
    """Returns ``(tag, html_url)`` or ``(None, None)`` on any failure. Never raises."""
    try:
        resp = requests.get(
            _latest_release_url(),
            timeout=_HTTP_TIMEOUT,
            headers={"Accept": "application/json"},
        )
        if resp.status_code != 200:
            return None, None
        data = resp.json()
    except (requests.RequestException, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    return data.get("tag_name"), data.get("html_url")


def _no_update(latest=None, url=None):
    return {
        "update_available": False,
        "latest": latest,
        "url": url,
        "checked_at": timezone.now().isoformat(),
    }


def _compute():
    """The actual comparison (no caching). Never raises."""
    info = get_version_info()
    # Only ever nag a real release build — dev checkouts are left alone.
    if not info.get("is_release"):
        return _no_update()

    current = _parse_semver(info.get("tag") or info.get("version"))
    if current is None:
        return _no_update()

    tag, url = _fetch_latest_release()
    latest = _parse_semver(tag)
    if latest is None:
        return _no_update()

    if latest > current:
        return {
            "update_available": True,
            "latest": tag,
            "url": url,
            "checked_at": timezone.now().isoformat(),
        }
    return _no_update(latest=tag, url=url)


def check_for_update(force=False):
    """Update status dict via the in-process TTL cache. Never raises."""
    try:
        if not Settings.get("display.update_check"):
            return _no_update()
    except Exception:
        # DB unavailable (e.g. very early startup) — fail quiet.
        return _no_update()

    now = time.monotonic()
    with _lock:
        if not force and _cache["result"] is not None and _cache["expires_at"] > now:
            return _cache["result"]

    result = _compute()

    with _lock:
        _cache["result"] = result
        _cache["expires_at"] = time.monotonic() + _CACHE_TTL
    return result


def _clear_cache():
    with _lock:
        _cache["result"] = None
        _cache["expires_at"] = 0.0
