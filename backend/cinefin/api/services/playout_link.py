"""Playout link keeper: keeps the control WebSocket to the active playout agent
open all the time, not only once something needs the player.

The agent shows an on-screen notice when Cinefin has not been connected for a
while, so an idle Cinefin must stay connected for the player to know it is
there. Once a link is up, ``WSMPV`` redials it by itself when it drops (with
its own backoff and keepalive pings); this thread only makes the first
connection, retries it with a backoff (2 s doubling to 30 s) while the agent is
unreachable, and reconnects when the active host changes (activate, pair,
delete: those call ``nudge()`` so it happens at once, and a periodic check
catches anything else). Local-socket hosts keep connecting on demand.

Started from ``ApiConfig.ready()`` like the schedule runner, never under tests
or management commands.
"""

import logging
import threading

from django.db import close_old_connections

logger = logging.getLogger(__name__)

RETRY_DELAY = 2.0  # first retry after a failed connect
RETRY_MAX_DELAY = 30.0
CHECK_INTERVAL = 10.0  # how often a healthy link is checked (host changes)

_thread: threading.Thread | None = None
_lock = threading.Lock()
_stop = threading.Event()
_wake = threading.Event()


def start():
    """Start the keeper once per process (idempotent)."""
    global _thread
    with _lock:
        if _thread is not None:
            return
        _stop.clear()
        _thread = threading.Thread(target=_run_loop, name="playout-link", daemon=True)
        _thread.start()
        logger.info("Playout link keeper started")


def stop():
    _stop.set()
    _wake.set()


def nudge():
    """Check the link now (the active host just changed)."""
    _wake.set()


def tick() -> bool:
    """One pass: connect to the active agent if not connected. False when the
    agent could not be reached."""
    from cinefin.api.mpv_service import mpv_service

    return mpv_service.ensure_link()


def _run_loop():
    delay = RETRY_DELAY
    while not _stop.is_set():
        try:
            ok = tick()
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("Playout link check failed")
            ok = False
        finally:
            close_old_connections()
        wait, delay = next_wait(ok, delay)
        _wake.wait(wait)
        _wake.clear()


def next_wait(ok: bool, delay: float) -> tuple[float, float]:
    """How long to wait after a pass, and the retry delay after that: the
    periodic check when connected, else the backoff (doubling up to the cap)."""
    if ok:
        return CHECK_INTERVAL, RETRY_DELAY
    return delay, min(delay * 2, RETRY_MAX_DELAY)
