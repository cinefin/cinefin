"""The single real-time WebSocket (/ws/events): one connection per client carrying the playout
status, the sync and trailer job feeds, and resource invalidations.

A WebSocket because browsers cap ~6 HTTP/1.1 connections per host and held SSE streams ate
that budget. The work (the in-process playout bus, DB polling) is blocking, so a daemon producer
thread hands finished messages to the coroutine over an asyncio.Queue. Single process means the
in-process bus reaches every client.

Message envelope (JSON text frames):
    {"channel": "playout", "data": {...status...}}
    {"channel": "job", "event": "state|progress|log|complete", "data": {...}}
    {"channel": "invalidate", "keys": ["schedules", "movies", ...]}

"invalidate" is a change signal: the producer watches cheap DB fingerprints (COUNT/MAX
aggregates) plus probe-style timers and names the resources that changed, so clients refetch
over REST instead of polling.

Every connection is accepted (kiosks are auth-exempt), but the "job" channel, which carries
live operation logs, goes only to an authenticated session. "playout" is the public status and
"invalidate" carries only resource names.
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time

logger = logging.getLogger(__name__)

TICK_SECONDS = 0.25  # playout position cadence (also the bus wait timeout)
JOB_POLL_SECONDS = 1.0  # job-row poll cadence
INVALIDATE_TICK_SECONDS = 2.0  # how often cheap resource fingerprints are recomputed
# Probe-style feeds with no cheap change signal: emit their key on this cadence.
CADENCE_INVALIDATIONS = {"health": 60.0, "agent": 15.0, "setup": 4.0}
# Initial log backlog sent the first time a job is seen, so a reconnecting
# console shows recent context without replaying the whole history.
LOG_TAIL_ON_FIRST_SEE = {"sync": 50, "trailer": 200}
# Invalidations that change the playout status (its next screening, the player's reachability).
PLAYOUT_KEYS = {"schedules", "agent"}


def _patch_position(payload: dict, mpv_service) -> None:
    """Move the clocks on from mpv_service's live observer cache (no rebuild, no
    round-trips): the item's playback and, by the same step, the programme's
    elapsed time. Skipped during a hold, whose clock only the full rebuild reports."""
    pb = payload.get("playback")
    if not pb or mpv_service._hold_progress:
        return
    t = mpv_service._live.get("time")
    d = mpv_service._live.get("duration")
    if t is None:
        return
    t = float(t)
    step = t - pb["position"]
    pb["position"] = t
    if d:
        pb["duration"] = float(d)
    pb["remaining"] = max(0.0, pb["duration"] - t)
    pb["percentage"] = round(t / pb["duration"] * 100, 1) if pb["duration"] > 0 else 0.0
    pl = payload.get("playlist")
    if pl and pl.get("current_position") is not None:
        pl["programme_elapsed_time"] = max(0.0, pl["programme_elapsed_time"] + step)
        pl["programme_remaining_time"] = max(0.0, pl["programme_total_duration"] - pl["programme_elapsed_time"])


def _job_payload(job) -> dict:
    return {
        "job_id": job.id,
        "kind": job.kind,
        "source_id": job.source_id,
        "operation": job.operation,
        "state": job.state,
        "phase": job.phase,
        "current": job.current,
        "total": job.total,
        "percentage": job.percentage,
        "current_item": job.current_item,
        "counts": job.counts,
        "error": job.error,
    }


def _log_payload(job, entries: list) -> dict:
    return {"job_id": job.id, "kind": job.kind, "source_id": job.source_id, "entries": entries}


def _resource_signatures() -> dict[str, str]:
    """Cheap fingerprints of mutable resources; when one changes, clients holding
    it should refetch. Kept to COUNT/MAX aggregates (plus a tiny values_list for
    schedules and sources, which mutate status/freshness in place) so this is a
    handful of indexed queries per tick, not a serialization pass."""
    from django.db.models import Count, Max

    from cinefin.api.models import Job, Movie, Programme, ProgrammeSchedule, SyncSource, Trailer
    from cinefin.api.services import kiosk_service, schedule_runner

    def agg(qs, field: str | None) -> str:
        row = qs.aggregate(n=Count("id"), mx=Max(field)) if field else qs.aggregate(n=Count("id"))
        return f"{row['n']}:{row.get('mx')}"

    return {
        # Sync mutates movies (remote_updated_at) and adds/removes rows (count/pk).
        "movies": agg(Movie.objects, "remote_updated_at") + f":{Movie.objects.aggregate(m=Max('id'))['m']}",
        "programmes": agg(Programme.objects, "updated_at"),
        "trailers": agg(Trailer.objects, None) + f":{Trailer.objects.aggregate(m=Max('id'))['m']}",
        # Schedules flip status (scheduled→running→completed) with no timestamp.
        "schedules": str(list(ProgrammeSchedule.objects.values_list("id", "status", "start_time", "runtime"))),
        # Source freshness + running sync jobs — flips on sync start and finish.
        "sync": str(list(SyncSource.objects.values_list("id", "last_sync", "enabled")))
        + str(list(Job.sync.filter(state__in=Job.ACTIVE_STATES).values_list("id", "state"))),
        # The schedule-runner heartbeat is cheap to read, so change-detect it too.
        "runner": str(schedule_runner.runner_status()),
        # SPA build stamp — a change means "a deploy landed, reload for new code",
        # so idle kiosks catch it without a periodic display re-fetch.
        "deploy": kiosk_service.spa_reload_key(),
    }


def _produce(put, stop: threading.Event, authorized: bool) -> None:
    """Daemon thread: watch the playout bus, job rows and resource fingerprints and
    push message dicts through ``put``. All the blocking work lives here, off the
    event loop. ``authorized`` gates the private "job" channel (see module docs)."""
    from django.db import close_old_connections

    from cinefin.api.mpv_service import mpv_service
    from cinefin.api.services.playout_events import playout_event_bus
    from cinefin.api.services.playout_service import playout_status

    bus = playout_event_bus.subscribe()
    payload = None
    rebuild = True
    last_blob: str | None = None
    log_cursor: dict[int, int] = {}
    last_state: dict[int, str] = {}
    last_job_poll = 0.0
    last_sig: dict[str, str] | None = None  # None until the baseline is seeded
    last_invalidate_poll = 0.0
    cadence_emitted: dict[str, float] = {}

    try:
        while not stop.is_set():
            # Playout: rebuild on a discrete change, else patch just the position.
            try:
                if rebuild:
                    payload = playout_status().dict()
                    rebuild = False
                elif payload is not None:
                    _patch_position(payload, mpv_service)
                if payload is not None:
                    blob = json.dumps(payload, sort_keys=True, default=str)
                    if blob != last_blob:
                        last_blob = blob
                        put({"channel": "playout", "data": payload})
            except Exception:  # noqa: BLE001 — a bad build must not kill the socket
                logger.debug("WS playout build failed", exc_info=True)

            now = time.monotonic()
            if authorized and now - last_job_poll >= JOB_POLL_SECONDS:
                last_job_poll = now
                try:
                    _poll_jobs(put, log_cursor, last_state)
                except Exception:  # noqa: BLE001
                    logger.debug("WS job poll failed", exc_info=True)
                finally:
                    close_old_connections()

            if now - last_invalidate_poll >= INVALIDATE_TICK_SECONDS:
                last_invalidate_poll = now
                try:
                    last_sig, cadence_emitted, keys = _poll_invalidations(put, last_sig, cadence_emitted, now)
                    # The status carries the next screening and the player's reachability.
                    rebuild = rebuild or bool(keys & PLAYOUT_KEYS)
                except Exception:  # noqa: BLE001
                    logger.debug("WS invalidate poll failed", exc_info=True)
                finally:
                    close_old_connections()

            # Block up to a tick on the bus; a discrete change wakes a rebuild.
            try:
                bus.get(timeout=TICK_SECONDS)
                rebuild = True
            except queue.Empty:
                pass
    finally:
        playout_event_bus.unsubscribe(bus)


def _poll_invalidations(
    put, last_sig: dict[str, str] | None, cadence_emitted: dict[str, float], now: float
) -> tuple[dict[str, str], dict[str, float], set[str]]:
    """Emit an ``invalidate`` frame naming the resources that changed since the last
    tick, plus the probe-style keys whose cadence has elapsed. The first call only
    seeds the baseline (clients already load on mount, so don't double-fetch)."""
    from cinefin.api.models import Settings

    keys: set[str] = set()

    sig = _resource_signatures()
    if last_sig is not None:
        keys |= {k for k, v in sig.items() if last_sig.get(k) != v}

    setup_done = bool(Settings.get("setup.completed"))
    for key, cadence in CADENCE_INVALIDATIONS.items():
        if key == "setup" and setup_done:
            continue  # the readiness checklist only matters until setup finishes
        if now - cadence_emitted.get(key, 0.0) >= cadence:
            cadence_emitted[key] = now
            if last_sig is not None:  # skip the seeding tick, like the fingerprints
                keys.add(key)

    if keys:
        put({"channel": "invalidate", "keys": sorted(keys)})
    return sig, cadence_emitted, keys


def _poll_jobs(put, log_cursor: dict[int, int], last_state: dict[int, str]) -> None:
    """Emit state/progress/log for active jobs and complete for jobs that just finished.
    A first sighting sends a recent log tail, not the whole history."""
    from cinefin.api.models import Job

    active = list(Job.objects.filter(state__in=Job.ACTIVE_STATES))
    for job in active:
        put(
            {
                "channel": "job",
                "event": "state" if last_state.get(job.id) != job.state else "progress",
                "data": _job_payload(job),
            }
        )
        last_state[job.id] = job.state
        full_log = job.log or []
        start = log_cursor.get(job.id, max(0, len(full_log) - LOG_TAIL_ON_FIRST_SEE.get(job.kind, 50)))
        if start < len(full_log):
            log_cursor[job.id] = len(full_log)
            put({"channel": "job", "event": "log", "data": _log_payload(job, full_log[start:])})

    active_ids = {j.id for j in active}
    for job_id in [jid for jid, st in last_state.items() if jid not in active_ids and st in Job.ACTIVE_STATES]:
        finished = Job.objects.filter(pk=job_id).first()
        if not finished:
            del last_state[job_id]
            continue
        last_state[job_id] = finished.state
        full_log = finished.log or []
        start = log_cursor.get(job_id, 0)
        if start < len(full_log):
            log_cursor[job_id] = len(full_log)
            put({"channel": "job", "event": "log", "data": _log_payload(finished, full_log[start:])})
        put({"channel": "job", "event": "complete", "data": _job_payload(finished)})


def _cookie_value(scope, name: str) -> str | None:
    from http.cookies import SimpleCookie

    for header, value in scope.get("headers", []):
        if header == b"cookie":
            jar = SimpleCookie()
            jar.load(value.decode("latin1"))
            morsel = jar.get(name)
            return morsel.value if morsel else None
    return None


def _authorized(scope) -> bool:
    """Gate the socket the same way AuthGateMiddleware gates HTTP: open when the
    auth gate is off, otherwise require a logged-in Django session (the session
    cookie carries _auth_user_id). Runs in a thread — it touches the DB."""
    from importlib import import_module

    from django.conf import settings as dj
    from django.db import close_old_connections

    from cinefin.api.services.auth_service import auth_is_active

    try:
        if not auth_is_active():
            return True
        key = _cookie_value(scope, getattr(dj, "SESSION_COOKIE_NAME", "sessionid"))
        if not key:
            return False
        engine = import_module(dj.SESSION_ENGINE)
        return bool(engine.SessionStore(key).get("_auth_user_id"))
    except Exception:  # noqa: BLE001 — any failure = deny
        return False
    finally:
        close_old_connections()


async def events_ws_app(scope, receive, send) -> None:
    """Raw-ASGI WebSocket app for /ws/events (mounted from cinefin.asgi).

    The socket accepts every connection so auth-exempt kiosks can ride it; the
    producer withholds the private "job" channel from unauthenticated ones."""
    ev = await receive()
    if ev.get("type") != "websocket.connect":
        return
    authorized = await asyncio.to_thread(_authorized, scope)
    await send({"type": "websocket.accept"})

    loop = asyncio.get_running_loop()
    outbox: asyncio.Queue = asyncio.Queue(maxsize=2000)
    stop = threading.Event()

    def put(msg: dict) -> None:
        # Hand off to the loop; drop if it's gone (socket closing) or the client
        # is hopelessly backed up (real-time data is better fresh than stalled).
        def offer():
            if not outbox.full():
                outbox.put_nowait(msg)

        try:
            loop.call_soon_threadsafe(offer)
        except RuntimeError:
            pass

    threading.Thread(target=_produce, args=(put, stop, authorized), daemon=True).start()

    async def pump() -> None:
        while True:
            msg = await outbox.get()
            await send({"type": "websocket.send", "text": json.dumps(msg, default=str)})

    pump_task = asyncio.ensure_future(pump())
    try:
        while (await receive()).get("type") != "websocket.disconnect":
            pass
    finally:
        stop.set()
        pump_task.cancel()
