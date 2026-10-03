"""Standby: the cinema's ident, played once and then held.

The player owns standby and Cinefin owns programmes. Each player is sent a
spec (``standby_spec``): the ident's stream URL, the file's sha256, per-file
mpv options that hold it, the cinema and player names and ``show_status``. An
agent keeps the spec and the file and plays it by itself; a local mpv is sent
the same ident and options by ``mpv_service.standby()``.

The System Ident loops its 4 to 34 s range (``ab-loop``); a cinema's own ident
stops at its hold point (``end=<t>``) or its end, where ``keep-open=always``
holds the frame, paused, instead of moving on to the next entry.
"""

import hashlib
import json
import logging
import os
import threading

from django.db import close_old_connections

from cinefin.api.models import Bumper, PlayoutHost, Settings
from cinefin.api.utils.assets import SYSTEM_IDENT_LOOP, system_ident_path, system_ident_stream_url
from cinefin.api.utils.media_paths import usermedia_abs_path

logger = logging.getLogger(__name__)


def _seconds(value: float) -> str:
    return f"{value:.3f}".rstrip("0").rstrip(".")


SYSTEM_IDENT_OPTIONS = f"ab-loop-a={_seconds(SYSTEM_IDENT_LOOP[0])},ab-loop-b={_seconds(SYSTEM_IDENT_LOOP[1])}"


def ident_options(hold_point: float | None) -> str:
    """mpv per-file options that play a cinema's own ident once and freeze it."""
    if hold_point is not None and hold_point > 0:
        return f"end={_seconds(hold_point)},keep-open=always"
    return "keep-open=always"


def resolve_ident() -> tuple[str, str, str, str]:
    """``(stream_url, file_path, options, label)`` of the ident standby plays.

    The user media item chosen in Settings wins when its file is here (the
    player downloads it, so the file must exist to hash and serve); otherwise
    the bundled System Ident does."""
    ident_id = Settings.get("cinema.default_ident_id")
    if ident_id:
        bumper = Bumper.objects.filter(id=ident_id).first()
        path = usermedia_abs_path(bumper.file_path) if bumper else ""
        if bumper is None:
            logger.warning("Ident %s not found; standby uses the System Ident", ident_id)
        elif not path or not os.path.isfile(path):
            logger.warning("Ident '%s' has no file at %s; standby uses the System Ident", bumper.title, path)
        else:
            return bumper.get_stream_url()["stream_url"], path, ident_options(bumper.hold_point), bumper.title
    return system_ident_stream_url(), system_ident_path(), SYSTEM_IDENT_OPTIONS, "System Ident"


_sha_cache: dict[str, tuple[float, int, str]] = {}
_sha_lock = threading.Lock()


def file_sha256(path: str) -> str:
    """sha256 of a file, cached by path, mtime and size (an ident can be large)."""
    st = os.stat(path)
    with _sha_lock:
        cached = _sha_cache.get(path)
        if cached and cached[:2] == (st.st_mtime, st.st_size):
            return cached[2]
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    sha = digest.hexdigest()
    with _sha_lock:
        _sha_cache[path] = (st.st_mtime, st.st_size, sha)
    return sha


def standby_spec(host: PlayoutHost) -> dict:
    """The standby spec for one host, in the shape the player's ``PUT /standby`` takes."""
    url, path, options, _label = resolve_ident()
    return {
        "ident": {"url": url, "sha256": file_sha256(path), "options": options},
        "cinema_name": Settings.get_cinema_name(),
        "player_name": host.name,
        "show_status": host.show_status,
    }


# host id -> the spec last accepted by that host's agent (as JSON), so it is
# only sent again when something in it changed (or this process is new).
_pushed: dict[int, str] = {}


def sync_spec(host: PlayoutHost, force: bool = False) -> dict | None:
    """PUT the host's spec when it may have changed. Returns the agent's standby
    status, or None when nothing was sent. Raises the agent service's errors."""
    from cinefin.api.services.playout_agent_service import playout_agent_service

    spec = standby_spec(host)
    key = json.dumps(spec, sort_keys=True)
    if not force and _pushed.get(host.id) == key:
        return None
    reply = playout_agent_service.put_standby(host, spec)
    _pushed[host.id] = key
    return reply


def in_sync(host: PlayoutHost, status: dict) -> bool:
    """Whether a player's standby status (``/status`` ``standby``, or a standby
    reply) holds this host's current spec, with its ident downloaded or on the
    way (a failed download is retried by sending the spec again). The URL is
    never echoed back."""
    status = status or {}
    spec = standby_spec(host)
    theirs = status.get("spec") or {}
    mine = {**spec, "ident": {k: v for k, v in spec["ident"].items() if k != "url"}}
    return {k: theirs.get(k) for k in mine} == mine and bool(status.get("file") or status.get("downloading"))


# local-socket host id -> the ident (URL and options) last loaded into its mpv,
# so a push only reloads an idle local mpv when the ident itself changed.
_shown_local: dict[int, tuple[str, str]] = {}


def shown_local(host_id: int, url: str, options: str) -> None:
    _shown_local[host_id] = (url, options)


def forget(host_id: int) -> None:
    """Send the spec again on the next standby (the player was re-paired or reset)."""
    _pushed.pop(host_id, None)


def push_now(host_ids: list[int] | None) -> None:
    from cinefin.api.mpv_service import mpv_service
    from cinefin.api.services.playout_agent_service import playout_agent_service

    hosts = PlayoutHost.objects.filter(kind=PlayoutHost.KIND_AGENT, enabled=True).exclude(token="")
    if host_ids is not None:
        hosts = hosts.filter(id__in=host_ids)
    for host in hosts:
        try:
            before = _pushed.get(host.id)
            reply = sync_spec(host)
            # The player swaps in an ident it had to download, but not one it
            # already had: put a changed, cached ident on screen now.
            if reply and reply.get("on_standby") and not reply.get("downloading"):
                if before is None or json.loads(before)["ident"] != json.loads(_pushed[host.id])["ident"]:
                    playout_agent_service.enter_standby(host)
        except Exception as e:  # noqa: BLE001 - a push is best effort; standby() sends it again
            forget(host.id)
            logger.info("Standby spec not sent to %s: %s", host.name, getattr(e, "message", e))
    # A local mpv holds no spec: put a changed ident up if it is on standby
    # (names and show_status mean nothing to it).
    active = PlayoutHost.get_active()
    if active is not None and active.kind == PlayoutHost.KIND_LOCAL_SOCKET and mpv_service.idle():
        url, _path, options, _label = resolve_ident()
        if _shown_local.get(active.id) != (url, options):
            mpv_service.standby()


def push(host_ids: list[int] | None = None) -> None:
    """Send the standby spec to agent hosts (all paired ones, or ``host_ids``),
    in the background. Called whenever the spec may have changed: pairing,
    activating, renaming a host or changing its show_status, and changes to the
    cinema name, the ident choice, an ident's hold point or the streaming URL."""

    def run():
        try:
            push_now(host_ids)
        except Exception:  # noqa: BLE001
            logger.warning("Standby spec push failed", exc_info=True)
        finally:
            close_old_connections()

    threading.Thread(target=run, name="standby-push", daemon=True).start()
