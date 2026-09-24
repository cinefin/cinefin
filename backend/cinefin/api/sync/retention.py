"""Job-row retention: a terminal row is deleted only if it is BOTH older than
``days`` AND outside the most-recent ``keep`` of its kind; active rows untouched."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

logger = logging.getLogger("cinefin.sync.retention")

DEFAULT_KEEP_DAYS = 30
DEFAULT_KEEP_COUNT = 200

LAST_PRUNE_SETTINGS_KEY = "maintenance.last_job_prune"
PRUNE_INTERVAL = timedelta(days=1)
# The engine loop ticks every couple of seconds; don't hit the Settings row
# (a DB read) more than once an hour just to discover there's nothing to do.
_SETTINGS_CHECK_SECONDS = 3600
_next_settings_check: float = 0.0


def prune_jobs(days: int = DEFAULT_KEEP_DAYS, keep: int = DEFAULT_KEEP_COUNT, dry_run: bool = False) -> dict[str, int]:
    from cinefin.api.models import Job

    cutoff = timezone.now() - timedelta(days=days)
    deleted: dict[str, int] = {}
    for kind, _label in Job.KINDS:
        terminal = Job.objects.filter(kind=kind, state__in=Job.TERMINAL_STATES)
        # The `keep` most recent terminal rows of this kind are always safe.
        keep_ids = list(terminal.order_by("-created_at").values_list("pk", flat=True)[:keep])
        prunable = terminal.filter(created_at__lt=cutoff).exclude(pk__in=keep_ids)
        if dry_run:
            deleted[kind] = prunable.count()
        else:
            deleted[kind] = prunable.delete()[0]
    return deleted


def maybe_prune_jobs() -> None:
    """Prune at most once per PRUNE_INTERVAL; cheap enough to call every loop tick."""
    global _next_settings_check

    now_mono = time.monotonic()
    if now_mono < _next_settings_check:
        return
    _next_settings_check = now_mono + _SETTINGS_CHECK_SECONDS

    from cinefin.api.models import Settings

    last_raw = Settings.get(LAST_PRUNE_SETTINGS_KEY)
    if last_raw:
        last = parse_datetime(str(last_raw))
        if last and timezone.now() - last < PRUNE_INTERVAL:
            return

    deleted = prune_jobs()
    Settings.set(LAST_PRUNE_SETTINGS_KEY, timezone.now().isoformat())
    total = sum(deleted.values())
    if total:
        logger.info("Job retention pruned %d old job rows (%s)", total, deleted)
