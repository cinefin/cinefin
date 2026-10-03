from importlib import import_module
from types import SimpleNamespace

import pytest
from django.conf import settings

from cinefin.api.models import Job
from cinefin.api.services import auth_service
from cinefin.api.views import ws_events

from .factories import JobFactory, ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db


def test_position_patch_moves_both_clocks_except_during_a_hold():
    payload = {
        "playback": {"position": 20.0, "duration": 0.0, "remaining": 0.0, "percentage": 0.0},
        "playlist": {
            "current_position": 2,
            "programme_elapsed_time": 500.0,
            "programme_total_duration": 1000.0,
            "programme_remaining_time": 500.0,
        },
    }
    ws_events._patch_position(payload, SimpleNamespace(_hold_progress=None, _live={"time": 30.0, "duration": 120.0}))
    assert (payload["playback"]["position"], payload["playback"]["remaining"], payload["playback"]["percentage"]) == (
        30.0,
        90.0,
        25.0,
    )
    assert (payload["playlist"]["programme_elapsed_time"], payload["playlist"]["programme_remaining_time"]) == (
        510.0,
        490.0,
    )
    held = {"playback": {"position": 2.0, "remaining": 8.0}}
    ws_events._patch_position(held, SimpleNamespace(_hold_progress={"duration": 10}, _live={"time": 999.0}))
    assert held["playback"]["position"] == 2.0


def test_job_poll_emits_state_log_progress_then_complete():
    job = JobFactory(state=Job.STATE_RUNNING, current=2, total=10, log=["hello"])
    cursor, last = {}, {}
    sent = []
    ws_events._poll_jobs(sent.append, cursor, last)
    assert {m["event"] for m in sent if m["data"]["job_id"] == job.id} >= {"state", "log"}
    sent.clear()
    ws_events._poll_jobs(sent.append, cursor, last)
    assert any(m["event"] == "progress" for m in sent)
    job.state = Job.STATE_SUCCESS
    job.save(update_fields=["state"])
    sent.clear()
    ws_events._poll_jobs(sent.append, cursor, last)
    assert any(m["event"] == "complete" and m["data"]["job_id"] == job.id for m in sent)


def test_invalidations_seed_silently_then_emit_on_change_and_cadence():
    sent = []
    sig, cadence, _ = ws_events._poll_invalidations(sent.append, None, {}, 0.0)
    assert sent == [] and {"movies", "programmes", "schedules", "sync"} <= set(sig)
    ProgrammeScheduleFactory()
    sig, cadence, keys = ws_events._poll_invalidations(sent.append, sig, cadence, 1.0)
    assert "schedules" in keys  # the producer rebuilds the status (its next screening) on it
    assert sent[-1]["channel"] == "invalidate" and "schedules" in sent[-1]["keys"]
    ws_events._poll_invalidations(sent.append, sig, cadence, ws_events.CADENCE_INVALIDATIONS["health"] + 2)
    assert "health" in sent[-1]["keys"]


def test_the_socket_needs_a_session_only_when_auth_is_on(monkeypatch):
    assert ws_events._authorized({"headers": []}) is True
    monkeypatch.setattr(auth_service, "auth_is_active", lambda *a: True)
    assert ws_events._authorized({"headers": []}) is False
    store = import_module(settings.SESSION_ENGINE).SessionStore()
    store["_auth_user_id"] = "1"
    store.create()
    cookie = f"{settings.SESSION_COOKIE_NAME}={store.session_key}".encode()
    assert ws_events._authorized({"headers": [(b"cookie", cookie)]}) is True
