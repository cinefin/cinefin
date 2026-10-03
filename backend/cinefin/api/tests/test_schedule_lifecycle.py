from datetime import timedelta

import pytest
from django.utils import timezone

from cinefin.api.models import ProgrammeSchedule
from cinefin.api.services import schedule_runner

from .factories import ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db


def _schedule(status, minutes_ago, runtime=120):
    s = ProgrammeScheduleFactory(start_time=timezone.now() - timedelta(minutes=minutes_ago), runtime=runtime)
    ProgrammeSchedule.objects.filter(id=s.id).update(status=status)
    return s


def _status(s):
    s.refresh_from_db()
    return s.status


@pytest.mark.parametrize(("busy", "fired"), [(True, 0), (False, 1)])
def test_due_schedule_waits_for_a_free_player(monkeypatch, busy, fired):
    monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: busy)
    monkeypatch.setattr(schedule_runner, "_spawn", schedule_runner._execute)  # inline, not on a thread
    ran = []
    monkeypatch.setattr(schedule_runner, "execute_schedule", lambda s: ran.append(s.id))
    s = _schedule("scheduled", 1)
    assert schedule_runner.tick()["fired"] == fired
    assert ran == ([s.id] if fired else [])
    if busy:
        assert _status(s) == "scheduled"


def test_completion_guard():
    finished = _schedule("running", 60, runtime=30)
    # Regression: runtime=0 (end_time == start_time) must not complete a just-started row.
    zero = _schedule("running", 1, runtime=0)
    schedule_runner.tick()
    assert (_status(finished), _status(zero)) == ("completed", "running")


def test_running_orphan_reconciled_to_missed():
    orphan = _schedule("running", 5)
    upcoming = ProgrammeScheduleFactory()
    schedule_runner.recover_orphans()
    assert _status(orphan) == "missed" and orphan.last_error
    assert _status(upcoming) == "scheduled"
