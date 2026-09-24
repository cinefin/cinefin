"""DB-backed sync engine: one worker thread per process draining sync-kind Job rows."""

from __future__ import annotations

import logging
import os
import threading
import traceback
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone

from . import retention

logger = logging.getLogger("cinefin.sync.engine")

_worker_thread: threading.Thread | None = None
_started = False
_lock = threading.Lock()
_stop = threading.Event()

POLL_INTERVAL = 2.0  # seconds between queue scans when idle


def worker_id() -> str:
    return f"{os.getpid()}:{threading.get_ident()}"


def start() -> None:
    """Start the background worker once per process (idempotent)."""
    global _worker_thread, _started
    with _lock:
        if _started:
            return
        _started = True
        _stop.clear()
        _worker_thread = threading.Thread(target=_run_loop, name="sync-engine", daemon=True)
        _worker_thread.start()
        logger.info("Sync engine started (%s)", worker_id())


def stop() -> None:
    _stop.set()


def _run_loop() -> None:
    try:
        _recover_orphans()
    except Exception:  # noqa: BLE001
        logger.exception("Sync engine recovery failed")

    while not _stop.is_set():
        ran = False
        try:
            retention.maybe_prune_jobs()  # self-throttles to once per day
            ran = _claim_and_run_one()
        except Exception:  # noqa: BLE001
            logger.exception("Sync engine loop error")
        finally:
            close_old_connections()
        if not ran:
            _stop.wait(POLL_INTERVAL)


def _recover_orphans() -> None:
    from cinefin.api.models import Job

    stuck = Job.sync.filter(state__in=(Job.STATE_RUNNING, Job.STATE_CANCELLING))
    for job in stuck:
        if job.attempts < job.max_attempts:
            job.state = Job.STATE_QUEUED
            job.phase = "Re-queued after restart"
            job.worker = ""
            job.save(update_fields=["state", "phase", "worker"])
            logger.warning("Re-queued orphaned job #%s after restart", job.pk)
        else:
            _finish(job, Job.STATE_FAILED, error="Worker died before completion")


def _claim_and_run_one() -> bool:
    from cinefin.api.models import Job

    now = timezone.now()
    candidate = (
        Job.sync.filter(state=Job.STATE_QUEUED, scheduled_for__lte=now).order_by("-priority", "created_at").first()
    )
    if candidate is None:
        return False

    # Atomic claim: only succeeds for the worker that flips queued -> running.
    claimed = Job.objects.filter(pk=candidate.pk, state=Job.STATE_QUEUED).update(
        state=Job.STATE_RUNNING,
        worker=worker_id(),
        started_at=now,
        attempts=candidate.attempts + 1,
    )
    if not claimed:
        return False  # someone else grabbed it

    job = Job.objects.get(pk=candidate.pk)
    _run_job(job)
    return True


def _run_job(job) -> None:
    from cinefin.api.models import Job, SyncSource

    from . import registry
    from .base import SyncCancelled, SyncContext

    source = job.source

    ctx = SyncContext(job)
    ctx.info(f"Starting '{job.operation}' for {source.name}")

    plugin = registry.get_plugin(source)
    if plugin is None:
        ctx.error(f"No plugin registered for source type '{source.sync_type}'")
        ctx.flush()
        _finish(job, Job.STATE_FAILED, error=f"Unknown source type: {source.sync_type}")
        return

    try:
        counts = plugin.apply(ctx, job.operation, job.params or {}) or {}
        ctx.flush()
        Job.objects.filter(pk=job.pk).update(counts=counts)
        failed = int(counts.get("failed", 0) or 0)
        state = Job.STATE_PARTIAL if failed else Job.STATE_SUCCESS
        _finish(job, state)
        SyncSource.objects.filter(pk=source.pk).update(last_sync=timezone.now())
        ctx.info("Done.")
        ctx.flush()

    except SyncCancelled:
        ctx.warn("Cancelled by user.")
        ctx.flush()
        _finish(job, Job.STATE_CANCELLED)

    except Exception as e:  # noqa: BLE001
        logger.exception("Job #%s failed", job.pk)
        ctx.error(f"Job failed: {e}")
        ctx.flush()
        # Retry with backoff if attempts remain, else mark failed.
        job.refresh_from_db(fields=["attempts", "max_attempts"])
        if job.attempts < job.max_attempts:
            backoff = min(300, 10 * (2 ** (job.attempts - 1)))
            Job.objects.filter(pk=job.pk).update(
                state=Job.STATE_QUEUED,
                scheduled_for=timezone.now() + timedelta(seconds=backoff),
                phase=f"Retry in {backoff}s",
                worker="",
            )
            ctx.warn(f"Will retry in {backoff}s (attempt {job.attempts}/{job.max_attempts}).")
            ctx.flush()
        else:
            _finish(job, Job.STATE_FAILED, error=f"{e}\n{traceback.format_exc(limit=4)}")


def _finish(job, state: str, error: str = "") -> None:
    from cinefin.api.models import Job

    fields = {
        "state": state,
        "finished_at": timezone.now(),
        "phase": dict(Job.STATES).get(state, state),
    }
    if error:
        fields["error"] = error
    Job.objects.filter(pk=job.pk).update(**fields)
