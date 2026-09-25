"""
Single source of truth for the application version.

The canonical version is a git tag of the form ``vMAJOR.MINOR.PATCH`` (SemVer).
We never hand-edit a version string — it is resolved at runtime in priority order:

1. ``CINEFIN_VERSION`` env var — set in the Docker image at build time
   (the container has no git history to describe).
2. ``git describe --tags --always`` — for dev checkouts run from the repo.
3. ``"dev"`` — last-resort fallback (no env, no git).

Use ``get_version()`` for the human-facing string (e.g. ``v0.1.0`` or
``v0.1.0-3-gabc1234`` for an untagged commit past a tag), ``get_commit()``
for the short SHA, and ``get_version_info()`` for a parsed breakdown the UI
can explain (release vs dev build, commits-ahead, dirty tree).

Git-derived values are cached with a short TTL rather than for the process
lifetime: long-running gunicorn workers on a git-checkout deployment pick up
a ``git pull`` (new tags, new commits) without needing a restart.
"""

import os
import re
import subprocess
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Re-resolve git state at most this often (seconds). Cheap insurance against
# a subprocess call on every request without pinning the string to boot time.
_CACHE_TTL = 300

_cache = {}  # key -> (expires_at, value)

# vX.Y.Z-<ahead>-g<sha>[-dirty] — the describe shape for an untagged commit.
_DESCRIBE_RE = re.compile(r"^(?P<tag>.*?)-(?P<ahead>\d+)-g(?P<sha>[0-9a-f]+?)(?P<dirty>-dirty)?$")


def _git(*args):
    """Run a git command in the repo root, returning stripped stdout or None."""
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _cached(key, resolve):
    """TTL-cached call: resolve() at most once per _CACHE_TTL per key."""
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = resolve()
    _cache[key] = (now + _CACHE_TTL, value)
    return value


def get_version():
    """Return the application version string (e.g. ``v0.1.0`` or ``dev``)."""
    env = os.environ.get("CINEFIN_VERSION", "").strip()
    if env:
        return env
    described = _cached("describe", lambda: _git("describe", "--tags", "--always", "--dirty"))
    return described or "dev"


def get_commit():
    """Return the short git commit SHA, or the env override / ``unknown``."""
    env = os.environ.get("CINEFIN_COMMIT", "").strip()
    if env:
        return env
    sha = _cached("commit", lambda: _git("rev-parse", "--short", "HEAD"))
    return sha or "unknown"


def get_channel():
    """Return the release channel: ``release`` / ``edge`` / ``dev``.

    An explicit ``CINEFIN_CHANNEL`` env var (stamped at build time — ``edge`` on
    main CI builds, ``release`` on tag builds, ``dev`` on local compose builds)
    always wins, so a git-describe version on a locally built image still reads
    as ``dev`` rather than being mistaken for an edge build. Absent the env var
    it is derived from the version string.
    """
    env = os.environ.get("CINEFIN_CHANNEL", "").strip()
    if env:
        return env
    version = get_version()
    if re.fullmatch(r"v\d+\.\d+\.\d+", version):
        return "release"
    if version == "dev":
        return "dev"
    return "edge"


def get_version_info():
    """
    Parse the version string into a dict the UI can explain.

    Returns ``{"version", "channel", "is_release", "tag", "ahead", "commit", "dirty"}``.
    ``is_release`` is True only for an exact ``vX.Y.Z`` build (env-stamped
    Docker images and exactly-tagged checkouts). For dev builds, ``tag`` is
    the nearest release, ``ahead`` how many commits past it, and ``dirty``
    whether the working tree had uncommitted changes.
    """
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
    if re.fullmatch(r"v\d+\.\d+\.\d+", version):
        info["is_release"] = True
        info["tag"] = version
        return info
    m = _DESCRIBE_RE.match(version)
    if m:
        info["tag"] = m.group("tag")
        info["ahead"] = int(m.group("ahead"))
        info["commit"] = m.group("sha")
        info["dirty"] = bool(m.group("dirty"))
    elif version.endswith("-dirty"):
        info["dirty"] = True
    return info
