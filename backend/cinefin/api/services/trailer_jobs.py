"""Background runner for trailer-library operations. Only one trailer job runs at a time."""

import logging
import os
import threading

from django.db import close_old_connections
from django.utils import timezone

from cinefin.api.models import Job
from cinefin.api.services.trailer_service import TrailerCancelled, TrailerService
from cinefin.api.sync.base import SyncContext

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


class JobCancelled(TrailerCancelled):
    pass


class JobContext(SyncContext):
    """A trailer job's SyncContext, shaped for TrailerService's log/progress/check_cancelled hooks."""

    log_cap = 2000
    logger = logger

    def __init__(self, job: Job):
        super().__init__(job)
        # Most recent error line, surfaced as the job's failure reason for the client toast.
        self.last_error = ""

    def log(self, level: str, message: str):
        level = level or "info"
        if level.lower() == "error":
            self.last_error = str(message)
        super().log(level, str(message))

    def update_progress(self, current: int, total: int, message: str = ""):
        message = str(message or "")
        self.progress(int(current or 0), int(total or 0), phase=message[:160], item=message[:300])

    def check_cancelled(self):
        if self._cancel_requested or Job.trailer.filter(pk=self.job_id, cancel_requested=True).exists():
            self._cancel_requested = True
            raise JobCancelled("Cancelled by user")


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
        worker=f"{os.getpid()}:{threading.get_ident()}",
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

        service = TrailerService(log=ctx.log, progress=ctx.update_progress, check_cancelled=ctx.check_cancelled)
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
    n = stale.update(state=Job.STATE_FAILED, error="Interrupted by a server restart", finished_at=timezone.now())
    if n:
        logger.warning("Marked %s orphaned trailer job(s) as failed after restart", n)
