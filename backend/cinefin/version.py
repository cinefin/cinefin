"""The application version, resolved at runtime (never hand-edited).

In order: the ``CINEFIN_VERSION`` env var (stamped into the Docker image, which has
no git history), ``git describe`` in a checkout, else ``"dev"``. Git results are
cached with a short TTL, so a long-running checkout deployment sees a ``git pull``.
"""

import os
import re
import subprocess
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CACHE_TTL = 300  # seconds

_cache = {}  # key -> (expires_at, value)

_RELEASE_RE = re.compile(r"v\d+\.\d+\.\d+")
# vX.Y.Z-<ahead>-g<sha>[-dirty] — the describe shape for an untagged commit.
_DESCRIBE_RE = re.compile(r"^(?P<tag>.*?)-(?P<ahead>\d+)-g(?P<sha>[0-9a-f]+?)(?P<dirty>-dirty)?$")


def _git(*args):
    """Stripped stdout of a git command in the repo root, or None."""
    try:
        out = subprocess.run(["git", *args], cwd=_REPO_ROOT, capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def _cached(key, resolve):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = resolve()
    _cache[key] = (now + _CACHE_TTL, value)
    return value


def _env(name):
    return os.environ.get(name, "").strip()


def get_version():
    """E.g. ``v0.1.0``, ``v0.1.0-3-gabc1234`` past a tag, or ``dev``."""
    return (
        _env("CINEFIN_VERSION")
        or _cached("describe", lambda: _git("describe", "--tags", "--always", "--dirty"))
        or "dev"
    )


def get_commit():
    return _env("CINEFIN_COMMIT") or _cached("commit", lambda: _git("rev-parse", "--short", "HEAD")) or "unknown"


def get_channel():
    """``release`` / ``edge`` / ``dev``. CINEFIN_CHANNEL (stamped at build time) wins, so a
    locally built image with a describe version still reads as ``dev``."""
    env = _env("CINEFIN_CHANNEL")
    if env:
        return env
    version = get_version()
    if _RELEASE_RE.fullmatch(version):
        return "release"
    return "dev" if version == "dev" else "edge"


def get_version_info():
    """``{version, channel, is_release, tag, ahead, commit, dirty}``; for a dev build
    ``tag`` is the nearest release and ``ahead`` the commits past it."""
    version = get_version()
    info = {
        "version": version,
        "channel": get_channel(),
        "is_release": False,
        "tag": None,
        "ahead": 0,
        "commit": get_commit(),
        "dirty": False,
    }
    if _RELEASE_RE.fullmatch(version):
        info.update(is_release=True, tag=version)
    elif m := _DESCRIBE_RE.match(version):
        info.update(tag=m["tag"], ahead=int(m["ahead"]), commit=m["sha"], dirty=bool(m["dirty"]))
    elif version.endswith("-dirty"):
        info["dirty"] = True
    return info
