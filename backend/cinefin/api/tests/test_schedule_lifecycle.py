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


def test_missed_screenings_say_why(monkeypatch):
    monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: True)
    deferred = _schedule("scheduled", 1)
    schedule_runner.tick()
    deferred.refresh_from_db()
    assert (deferred.status, deferred.last_error) == ("scheduled", schedule_runner.BUSY)

    ProgrammeSchedule.objects.filter(id=deferred.id).update(start_time=timezone.now() - timedelta(minutes=60))
    unseen = _schedule("scheduled", 60)
    schedule_runner.tick()
    for s, reason in ((deferred, schedule_runner.BUSY), (unseen, schedule_runner.NOT_RUNNING)):
        s.refresh_from_db()
        assert (s.status, s.last_error) == ("missed", reason)


def test_failed_screening_says_why(monkeypatch):
    from cinefin.api.services import preshow

    monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: False)
    monkeypatch.setattr(schedule_runner, "_spawn", schedule_runner._execute)
    monkeypatch.setattr(preshow, "CUE_WAIT_SECONDS", 0)
    monkeypatch.setattr(preshow, "_load", lambda programme: False)
    monkeypatch.setattr(preshow, "_connected", lambda: False)
    monkeypatch.setattr("cinefin.api.services.ProgrammeService.refresh_playlist", lambda programme: object())
    s = _schedule("scheduled", 1)
    schedule_runner.tick()
    s.refresh_from_db()
    assert (s.status, s.last_error) == ("failed", "The player wasn't connected")
