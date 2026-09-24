from __future__ import annotations

import logging
import time
from typing import Any

from django.utils import timezone

logger = logging.getLogger("cinefin.sync")


class SyncCancelled(Exception):
    pass


class SyncContext:
    """Throttled progress/log/cancellation channel persisted to the Job row."""

    def __init__(self, job, flush_interval: float = 1.0, log_cap: int = 1000):
        self.job_id = job.pk
        self.flush_interval = flush_interval
        self.log_cap = log_cap

        self._log: list[dict[str, Any]] = list(job.log or [])
        self._phase = job.phase
        self._current = job.current
        self._total = job.total
        self._item = job.current_item

        self._dirty = False
        self._last_flush = 0.0
        self._cancel_checked_at = 0.0
        self._cancel_requested = False

    def log(self, level: str, message: str) -> None:
        entry = {
            "ts": timezone.now().isoformat(),
            "level": level.upper(),
            "message": message,
        }
        self._log.append(entry)
        if len(self._log) > self.log_cap:
            self._log = self._log[-self.log_cap :]
        getattr(logger, level.lower(), logger.info)("[job %s] %s", self.job_id, message)
        self._dirty = True
        self._maybe_flush()

    def info(self, msg: str) -> None:
        self.log("info", msg)

    def warn(self, msg: str) -> None:
        self.log("warning", msg)

    def error(self, msg: str) -> None:
        self.log("error", msg)

    def progress(self, current: int, total: int, phase: str = "", item: str = "") -> None:
        self._current = current
        self._total = total
        if phase:
            self._phase = phase
        self._item = item or self._item
        self._dirty = True
        self._maybe_flush()

    def is_cancelled(self) -> bool:
        if self._cancel_requested:
            return True
        now = time.monotonic()
        if now - self._cancel_checked_at < self.flush_interval:
            return False
        self._cancel_checked_at = now
        from cinefin.api.models import Job

        state = Job.objects.filter(pk=self.job_id).values_list("state", flat=True).first()
        if state == Job.STATE_CANCELLING:
            self._cancel_requested = True
        return self._cancel_requested

    def check_cancelled(self) -> None:
        if self.is_cancelled():
            raise SyncCancelled("Sync cancelled by user")

    def _maybe_flush(self) -> None:
        now = time.monotonic()
        if self._dirty and (now - self._last_flush) >= self.flush_interval:
            self.flush()

    def flush(self) -> None:
        if not self._dirty:
            return
        from cinefin.api.models import Job

        Job.objects.filter(pk=self.job_id).update(
            phase=self._phase,
            current=self._current,
            total=self._total,
            current_item=self._item[:300],
            log=self._log,
        )
        self._dirty = False
        self._last_flush = time.monotonic()


class SyncSourcePlugin:
    """Base class every source plugin extends; registered via ``@register``."""

    type_id: str = ""
    label: str = ""
    operations: list[str] = ["sync"]
    needs_connection: bool = True

    def __init__(self, source):
        self.source = source

    def test_connection(self) -> tuple[bool, str]:
        raise NotImplementedError

    def get_libraries(self) -> list[str]:
        return []

    def apply(self, ctx: SyncContext, operation: str, params: dict[str, Any]) -> dict[str, int]:
        raise NotImplementedError
