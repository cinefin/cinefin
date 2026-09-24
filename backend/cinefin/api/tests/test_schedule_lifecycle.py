from datetime import timedelta

import pytest
from django.utils import timezone

from cinefin.api.models import ProgrammeSchedule
from cinefin.api.services import schedule_runner

from .factories import ProgrammeFactory, ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db


def _running(runtime, minutes_ago):
    s = ProgrammeScheduleFactory(
        programme=ProgrammeFactory(),
        start_time=timezone.now() - timedelta(minutes=minutes_ago),
        runtime=runtime,
    )
    ProgrammeSchedule.objects.filter(id=s.id).update(status="running")
    return s


class TestCompletionGuard:
    def test_finished_positive_runtime_completes(self):
        s = _running(runtime=30, minutes_ago=60)
        schedule_runner.tick()
        s.refresh_from_db()
        assert s.status == "completed"

    def test_zero_runtime_is_not_completed_while_playing(self):
        """Regression: runtime=0 (end_time == start_time) must not flip a just-started row to completed."""
        s = _running(runtime=0, minutes_ago=1)
        schedule_runner.tick()
        s.refresh_from_db()
        assert s.status == "running"


class TestOrphanRecovery:
    def test_running_orphan_reconciled_to_missed(self):
        s = _running(runtime=120, minutes_ago=5)
        schedule_runner.recover_orphans()
        s.refresh_from_db()
        assert s.status == "missed"
        assert s.last_error

    def test_recover_orphans_noop_without_running_rows(self):
        s = ProgrammeScheduleFactory(programme=ProgrammeFactory())
        schedule_runner.recover_orphans()
        s.refresh_from_db()
        assert s.status == "scheduled"
