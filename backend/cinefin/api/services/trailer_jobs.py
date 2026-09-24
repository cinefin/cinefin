"""Background runner for trailer-library operations. Only one trailer job runs at a time."""

from __future__ import annotations

import logging
import os
import threading
import time

from django.db import close_old_connections
from django.utils import timezone

from cinefin.api.models import Job
from cinefin.api.services.trailer_service import TrailerCancelled, TrailerService

logger = logging.getLogger(__name__)

# operation -> human label, used in the initial log line / phase
OPERATIONS = {
    "discover": "Discover trailers",
    "upcoming": "Discover trailers",  # legacy job rows keep a label
    "single": "Fetch trailer",
    "library": "Fetch library trailers",
    "verify": "Verify trailer directory",
    "ratings": "Update certificate ratings",
    "rename": "Rename trailers",
}

_FLUSH_INTERVAL = 1.0  # seconds between DB writes while running
_LOG_CAP = 2000  # keep the most recent N log lines on the row


class JobCancelled(TrailerCancelled):
    pass


class JobContext:
    """Buffers a job's log/progress and throttle-flushes them to the DB row."""

    def __init__(self, job: Job):
        self.job_id = job.id
        self._log = list(job.log or [])
        self._phase = job.phase or ""
        self._current = job.current
        self._total = job.total
        self._item = job.current_item or ""
        self._dirty = False
        self._last_flush = 0.0
        self._cancelled = False
        # Most recent error line, surfaced as the job's failure reason for the client toast.
        self.last_error = ""

    def log(self, level: str, message: str):
        if (level or "").lower() == "error":
            self.last_error = str(message)
        self._log.append(
            {
                "ts": timezone.now().isoformat(),
                "level": (level or "info").upper(),
                "message": str(message),
            }
        )
        if len(self._log) > _LOG_CAP:
            self._log = self._log[-_LOG_CAP:]
        getattr(logger, (level or "info").lower(), logger.info)(message)
        self._dirty = True
        self._maybe_flush()

    def update_progress(self, current: int, total: int, message: str = ""):
        self._current = int(current or 0)
        self._total = int(total or 0)
        if message:
            self._item = str(message)[:300]
            self._phase = str(message)[:160]
        self._dirty = True
        self._maybe_flush()

    def check_cancelled(self):
        if self._cancelled:
            raise JobCancelled("Cancelled by user")
        if Job.trailer.filter(pk=self.job_id, cancel_requested=True).exists():
            self._cancelled = True
            raise JobCancelled("Cancelled by user")

    def _maybe_flush(self):
        now = time.monotonic()
        if self._dirty and (now - self._last_flush) >= _FLUSH_INTERVAL:
            self.flush()

    def flush(self):
        Job.objects.filter(pk=self.job_id).update(
            phase=self._phase,
            current=self._current,
            total=self._total,
            current_item=self._item[:300],
            log=self._log,
        )
        self._dirty = False
        self._last_flush = time.monotonic()


def _worker_id() -> str:
    return f"{os.getpid()}:{threading.get_ident()}"


def start_job(operation: str, params: dict | None = None) -> Job:
    """Create a trailer Job and run it on a background thread. Raises if unknown op or one is active."""
    if operation not in OPERATIONS:
        raise ValueError(f"Unknown trailer operation: {operation}")

    if Job.trailer.filter(state__in=Job.ACTIVE_STATES).exists():
        raise RuntimeError("A trailer job is already running")

    job = Job.trailer.create(
        operation=operation,
        params=params or {},
        state=Job.STATE_RUNNING,
        worker=_worker_id(),
        phase=OPERATIONS[operation],
        started_at=timezone.now(),
    )

    thread = threading.Thread(target=_run, args=(job.id,), name=f"trailer-job-{job.id}", daemon=True)
    thread.start()
    return job


def _run(job_id: int) -> None:
    ctx = None
    try:
        job = Job.trailer.get(pk=job_id)
        ctx = JobContext(job)

        service = TrailerService(
            log=ctx.log,
            progress=ctx.update_progress,
            check_cancelled=ctx.check_cancelled,
        )

        ctx.log("info", f"Starting: {OPERATIONS.get(job.operation, job.operation)}")
        ok = service.run_operation(job.operation, job.params or {})

        counts = dict(service.sync_counts or {})
        failed = int(counts.get("failed") or 0)
        if not ok and not counts:
            state = Job.STATE_FAILED
        elif failed or not ok:
            state = Job.STATE_PARTIAL
        else:
            state = Job.STATE_SUCCESS

        error = ctx.last_error if state == Job.STATE_FAILED else ""
        _finish(ctx, job_id, state, counts=counts, error=error)

    except JobCancelled:
        if ctx:
            ctx.log("warning", "Cancelled")
        _finish(ctx, job_id, Job.STATE_CANCELLED)
    except Exception as e:  # noqa: BLE001
        logger.exception("Trailer job #%s crashed", job_id)
        if ctx:
            ctx.log("error", f"Job failed: {e}")
        _finish(ctx, job_id, Job.STATE_FAILED, error=str(e))
    finally:
        close_old_connections()


def _finish(ctx, job_id, state, counts=None, error=""):
    if ctx:
        ctx.flush()
    fields = {"state": state, "finished_at": timezone.now()}
    if counts is not None:
        fields["counts"] = counts
    if error:
        fields["error"] = error
    Job.objects.filter(pk=job_id).update(**fields)


def recover_orphans() -> None:
    """Mark trailer jobs left mid-run by a crash/restart as failed (no worker resumes them)."""
    stale = Job.trailer.filter(state__in=Job.ACTIVE_STATES)
    n = stale.update(
        state=Job.STATE_FAILED,
        error="Interrupted by a server restart",
        finished_at=timezone.now(),
    )
    if n:
        logger.warning("Marked %s orphaned trailer job(s) as failed after restart", n)
