from datetime import timedelta

import pytest
from django.utils import timezone

from cinefin.api.services import schedule_runner

from .factories import ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db


def _due_schedule():
    s = ProgrammeScheduleFactory(start_time=timezone.now() - timedelta(minutes=1))
    s.status = "scheduled"
    s.save(update_fields=["status"])
    return s


def test_due_schedule_deferred_while_player_busy(monkeypatch):
    monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: True)
    monkeypatch.setattr(schedule_runner, "execute_schedule", lambda s: pytest.fail("should not run while busy"))
    s = _due_schedule()

    result = schedule_runner.tick()

    s.refresh_from_db()
    assert s.status == "scheduled"
    assert result["fired"] == 0


def test_due_schedule_fires_when_player_free(monkeypatch):
    monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: False)
    ran = []
    monkeypatch.setattr(schedule_runner, "execute_schedule", lambda s: ran.append(s.id))
    s = _due_schedule()

    result = schedule_runner.tick()

    assert ran == [s.id]
    assert result["fired"] == 1
