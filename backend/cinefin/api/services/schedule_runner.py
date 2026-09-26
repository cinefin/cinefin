"""Schedule runner — a background thread in the web process that plays due ProgrammeSchedule rows.

Drives playout directly through the in-process MPV service. Tunable via Django settings:
SCHEDULER_TICK_SECONDS (15), SCHEDULER_GRACE_MINUTES (15), SCHEDULER_PREROLL_SECONDS (3)."""

import json
import logging
import os
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from cinefin.api.models import ProgrammeSchedule

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_started = False
_lock = threading.Lock()
_stop = threading.Event()


def start():
    """Start the runner once per process (idempotent). Atomic claims make it safe across processes."""
    global _thread, _started
    with _lock:
        if _started:
            return
        _started = True
        _stop.clear()
        _thread = threading.Thread(target=_run_loop, name="schedule-runner", daemon=True)
        _thread.start()
        logger.info("Schedule runner started (pid %s)", os.getpid())


def stop():
    _stop.set()


def _run_loop():
    tick_seconds = _cfg("SCHEDULER_TICK_SECONDS", 15)
    pid = os.getpid()
    write_heartbeat(pid, tick_seconds)
    while not _stop.is_set():
        try:
            tick()
        except Exception:  # noqa: BLE001 - keep the loop alive
            logger.exception("Scheduler tick error")
        finally:
            close_old_connections()
        write_heartbeat(pid, tick_seconds)
        _stop.wait(tick_seconds)
    clear_heartbeat()


def _cfg(name, default):
    return getattr(settings, name, default)


# Heartbeat file rewritten each tick, so status reads work from any process.
def heartbeat_path():
    default = os.path.join(tempfile.gettempdir(), "cinefin_scheduler.heartbeat")
    return _cfg("SCHEDULER_HEARTBEAT_FILE", default)


def write_heartbeat(pid, tick_seconds):
    try:
        with open(heartbeat_path(), "w") as f:
            json.dump({"pid": pid, "ts": time.time(), "tick": tick_seconds}, f)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not write scheduler heartbeat: %s", e)


def clear_heartbeat():
    try:
        os.remove(heartbeat_path())
    except OSError:
        pass


def runner_status():
    """Whether the runner appears alive (last beat within ~3 ticks), from its heartbeat."""
    try:
        with open(heartbeat_path()) as f:
            data = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return {"running": False, "pid": None, "last_beat": None, "age_seconds": None, "tick_seconds": None}

    ts = data.get("ts")
    tick = data.get("tick") or _cfg("SCHEDULER_TICK_SECONDS", 15)
    age = max(0.0, time.time() - ts) if ts else None
    running = age is not None and age <= max(tick * 3, 45)
    return {
        "running": running,
        "pid": data.get("pid"),
        # datetime.utcfromtimestamp is deprecated in 3.12+; build an aware UTC
        # value and keep the trailing "Z" the previous form emitted.
        "last_beat": (datetime.fromtimestamp(ts, tz=UTC).isoformat().replace("+00:00", "Z") if ts else None),
        "age_seconds": round(age, 1) if age is not None else None,
        "tick_seconds": tick,
    }


def execute_schedule(schedule):
    """Play a scheduled programme (load -> run). Raises on failure so the caller can mark it failed."""
    from cinefin.api.mpv_service import mpv_service

    programme = schedule.programme
    logger.info("Executing schedule %s (programme %s)", schedule.id, programme.id)

    # Load into playout: generate a missing playlist / rebuild a stale one first.
    from cinefin.api.models import Playlist

    if not Playlist.objects.filter(programme=programme).exists() or programme.playlist_stale:
        from cinefin.api.services import ProgrammeService

        if ProgrammeService.refresh_playlist(programme) is None:
            raise RuntimeError("Failed to generate playlist — check the application logs")
    if not mpv_service.load_programme(programme):
        raise RuntimeError("Failed to load programme into playout system")

    # At-start pre-show cues (lead 0) fire inside start_programme with preshow=True — scheduled
    # runs only; lead-time cues already fired earlier in _prefire during the run-up.
    time.sleep(_cfg("SCHEDULER_PREROLL_SECONDS", 3))
    if not mpv_service.start_programme(preshow=True):
        raise RuntimeError("Failed to start playback")

    from cinefin.api.services.playout_service import mark_programme_played

    mark_programme_played(programme.id)
    logger.info("Schedule %s started successfully", schedule.id)


def _claim(schedule_id):
    """Atomically move scheduled -> running. True if this caller claimed it."""
    return ProgrammeSchedule.objects.filter(id=schedule_id, status="scheduled").update(status="running") == 1


def _mpv_busy() -> bool:
    """True while a programme is RUNNING or PAUSED, so a due schedule doesn't seize the player."""
    try:
        from cinefin.api.mpv_service import ProgrammeState, mpv_service

        return mpv_service.programme_state in (ProgrammeState.RUNNING, ProgrammeState.PAUSED)
    except Exception:  # noqa: BLE001 - never let a status read break the tick
        return False


def recover_orphans():
    """Boot-time: mark schedules a prior process stranded 'running' as 'missed'.

    _claim() flips a row to 'running' before the several-second load+start, so a
    crash in that window strands it and the completion loop would later mark it
    falsely 'completed' — unless the player is still playing it (leave to finish)."""
    running = list(ProgrammeSchedule.objects.filter(status="running"))
    if not running:
        return

    playing_programme_id = None
    try:
        from cinefin.api.mpv_service import ProgrammeState, mpv_service

        if (
            mpv_service.programme_state in (ProgrammeState.RUNNING, ProgrammeState.PAUSED)
            and mpv_service.current_programme
        ):
            playing_programme_id = mpv_service.current_programme.id
    except Exception:  # noqa: BLE001 - a status read must never block recovery
        pass

    for s in running:
        if s.programme_id == playing_programme_id:
            continue  # still on air — let it finish
        if (
            ProgrammeSchedule.objects.filter(id=s.id, status="running").update(
                status="missed", last_error="Interrupted by a restart before it finished"
            )
            == 1
        ):
            logger.warning("Reconciled orphaned 'running' schedule %s -> missed", s.id)


# Advance pre-show cues fired this run-up, per schedule: {schedule_id: {command_id, …}}.
# In-memory (single process); a restart mid-run-up may refire or skip a cue — acceptable.
_prefired: dict[int, set[int]] = {}


def _prefire(now):
    """Fire lead-time pre-show cues at start_time − lead, ahead of the show.

    Cues with lead 0 fire at programme start (in start_programme); only lead > 0
    cues are staged here during the run-up to an upcoming scheduled screening."""
    from cinefin.api.services import preshow

    advance = preshow.advance_cues()
    if not advance:
        _prefired.clear()
        return

    window = timedelta(seconds=max(lead for _, lead in advance))
    upcoming = ProgrammeSchedule.objects.filter(status="scheduled", start_time__gt=now, start_time__lte=now + window)
    live: set[int] = set()
    for s in upcoming:
        live.add(s.id)
        done = _prefired.setdefault(s.id, set())
        due = [cid for cid, lead in advance if cid not in done and s.start_time - timedelta(seconds=lead) <= now]
        if due:
            preshow.fire(due)
            done.update(due)
            logger.info("Fired %d pre-show cue(s) for schedule %s", len(due), s.id)

    # Drop tracking for schedules that have started, been cancelled, or aged out.
    for sid in [sid for sid in _prefired if sid not in live]:
        del _prefired[sid]


def tick():
    """Run one scheduler pass. Returns a summary dict."""
    now = timezone.now()
    grace = timedelta(minutes=_cfg("SCHEDULER_GRACE_MINUTES", 15))
    fired = missed = completed = 0

    try:
        _prefire(now)
    except Exception:  # noqa: BLE001 - a cue error must never block schedule execution
        logger.exception("Pre-show pre-fire pass failed")

    # running -> completed once end passed. Guard on positive runtime: a zero/unknown
    # runtime makes end_time() == start_time, marking a just-claimed row 'completed' next tick.
    for s in ProgrammeSchedule.objects.filter(status="running"):
        if s.runtime and s.runtime > 0 and s.end_time() < now:
            ProgrammeSchedule.objects.filter(id=s.id, status="running").update(status="completed")
            completed += 1

    due = (
        ProgrammeSchedule.objects.filter(status="scheduled", start_time__lte=now)
        .select_related("programme")
        .order_by("start_time")
    )

    for s in due:
        # Too late to play sensibly (e.g. the box was off) -> missed
        if s.start_time < now - grace:
            if ProgrammeSchedule.objects.filter(id=s.id, status="scheduled").update(status="missed") == 1:
                missed += 1
                logger.warning("Schedule %s missed (was due %s)", s.id, s.start_time.isoformat())
            continue

        # A screening is on air — don't interrupt it. Leave the row 'scheduled'
        # so it fires once the player is free, or ages to 'missed' above.
        if _mpv_busy():
            logger.info("Schedule %s deferred: player busy with an active programme", s.id)
            continue

        if not _claim(s.id):
            continue  # claimed elsewhere

        try:
            execute_schedule(s)
            fired += 1
        except Exception as e:  # noqa: BLE001
            logger.error("Schedule %s failed: %s", s.id, e)
            ProgrammeSchedule.objects.filter(id=s.id).update(status="failed", last_error=str(e)[:2000])

    return {"fired": fired, "missed": missed, "completed": completed}
