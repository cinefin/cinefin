import pytest

from cinefin.api.services.playout_events import PlayoutEventBus

pytestmark = pytest.mark.django_db


class TestEventBus:
    def test_publish_wakes_subscribers(self):
        bus = PlayoutEventBus()
        q = bus.subscribe()
        bus.publish()
        assert q.get_nowait() == 1
        bus.publish()
        assert q.qsize() == 1
        bus.unsubscribe(q)


class TestPositionPatch:
    def test_patches_position_from_live_cache(self):
        from cinefin.api.views.ws_events import _patch_position

        class FakeSvc:
            _hold_progress = None
            _live = {"time": 30.0, "duration": 120.0}

        payload = {
            "playback": {"position": 20.0, "duration": 0.0, "remaining": 0.0, "percentage": 0.0},
            "playlist": {
                "current_position": 2,
                "programme_elapsed_time": 500.0,
                "programme_total_duration": 1000.0,
                "programme_remaining_time": 500.0,
            },
        }
        _patch_position(payload, FakeSvc())
        assert payload["playback"]["position"] == 30.0
        assert payload["playback"]["remaining"] == 90.0
        assert payload["playback"]["percentage"] == 25.0
        # The programme clock moves by the same ten seconds.
        assert payload["playlist"]["programme_elapsed_time"] == 510.0
        assert payload["playlist"]["programme_remaining_time"] == 490.0

    def test_skips_during_hold(self):
        from cinefin.api.views.ws_events import _patch_position

        class FakeSvc:
            _hold_progress = {"duration": 10, "elapsed": 2}
            _live = {"time": 999.0, "duration": 5.0}

        payload = {"playback": {"position": 2.0, "remaining": 8.0}}
        _patch_position(payload, FakeSvc())
        assert payload["playback"]["position"] == 2.0


class TestJobPayload:
    def test_job_payload_and_log_shape(self):
        from types import SimpleNamespace

        from cinefin.api.views.ws_events import _job_payload, _log_payload

        job = SimpleNamespace(
            id=7,
            kind="sync",
            source_id=3,
            operation="sync",
            state="running",
            phase="crawl",
            current=2,
            total=10,
            percentage=20,
            current_item="Alien",
            counts={"added": 1},
            error="",
            log=["a", "b"],
        )
        p = _job_payload(job)
        assert p["job_id"] == 7 and p["kind"] == "sync" and p["percentage"] == 20
        lp = _log_payload(job, job.log[1:])
        assert lp["job_id"] == 7 and lp["entries"] == ["b"]


class TestJobPollFlow:
    def test_active_job_emits_state_then_progress(self):
        from cinefin.api.models import Job
        from cinefin.api.views.ws_events import _poll_jobs

        from .factories import JobFactory

        job = JobFactory(state=Job.STATE_RUNNING, current=2, total=10, log=["hello"])

        sent: list = []
        log_cursor: dict[int, int] = {}
        last_state: dict[int, str] = {}

        _poll_jobs(sent.append, log_cursor, last_state)

        job_msgs = [m for m in sent if m["channel"] == "job"]
        assert any(m["event"] == "state" and m["data"]["job_id"] == job.id for m in job_msgs)
        assert any(m["event"] == "log" and m["data"]["job_id"] == job.id for m in job_msgs)

        sent.clear()
        _poll_jobs(sent.append, log_cursor, last_state)
        assert any(m["event"] == "progress" and m["data"]["job_id"] == job.id for m in sent)

    def test_finished_job_emits_complete(self):
        from cinefin.api.models import Job
        from cinefin.api.views.ws_events import _poll_jobs

        from .factories import JobFactory

        job = JobFactory(state=Job.STATE_RUNNING)
        log_cursor: dict[int, int] = {}
        last_state: dict[int, str] = {}
        _poll_jobs(lambda m: None, log_cursor, last_state)

        job.state = Job.STATE_SUCCESS
        job.save(update_fields=["state"])

        sent: list = []
        _poll_jobs(sent.append, log_cursor, last_state)
        assert any(m["event"] == "complete" and m["data"]["job_id"] == job.id for m in sent)


class TestResourceInvalidation:
    def test_signatures_cover_expected_resources(self):
        from cinefin.api.views.ws_events import _resource_signatures

        sig = _resource_signatures()
        assert {"movies", "programmes", "trailers", "schedules", "sync", "runner"} <= set(sig)

    def test_first_poll_seeds_without_emitting(self):
        from cinefin.api.views.ws_events import _poll_invalidations

        sent: list = []
        last_sig, cadence, _keys = _poll_invalidations(sent.append, None, {}, 0.0)
        assert sent == []
        assert last_sig is not None

    def test_new_schedule_emits_schedules_key(self):
        from cinefin.api.views.ws_events import _poll_invalidations

        from .factories import ProgrammeScheduleFactory

        sent: list = []
        last_sig, cadence, _keys = _poll_invalidations(sent.append, None, {}, 0.0)

        ProgrammeScheduleFactory()
        _sig, _cadence, keys = _poll_invalidations(sent.append, last_sig, cadence, 1.0)

        assert "schedules" in keys  # the producer rebuilds the status (its next screening) on it
        assert sent, "a new schedule should emit an invalidation"
        msg = sent[-1]
        assert msg["channel"] == "invalidate"
        assert "schedules" in msg["keys"]

    def test_cadence_key_emitted_after_its_interval(self):
        from cinefin.api.views.ws_events import CADENCE_INVALIDATIONS, _poll_invalidations

        sent: list = []
        last_sig, cadence, _keys = _poll_invalidations(sent.append, None, {}, 0.0)
        _poll_invalidations(sent.append, last_sig, cadence, CADENCE_INVALIDATIONS["health"] + 1)

        assert sent, "the health cadence should emit on its interval"
        assert "health" in sent[-1]["keys"]


class TestWebSocketAuthGate:
    def test_open_when_auth_off(self):
        from cinefin.api.views.ws_events import _authorized

        assert _authorized({"headers": []}) is True

    def test_denies_without_session_when_auth_on(self, monkeypatch):
        from cinefin.api.services import auth_service
        from cinefin.api.views import ws_events

        monkeypatch.setattr(auth_service, "auth_is_active", lambda *a: True)
        assert ws_events._authorized({"headers": []}) is False

    def test_allows_a_logged_in_session_when_auth_on(self, monkeypatch):
        from importlib import import_module

        from django.conf import settings

        from cinefin.api.services import auth_service
        from cinefin.api.views import ws_events

        monkeypatch.setattr(auth_service, "auth_is_active", lambda *a: True)
        store = import_module(settings.SESSION_ENGINE).SessionStore()
        store["_auth_user_id"] = "1"
        store.create()
        cookie = f"{settings.SESSION_COOKIE_NAME}={store.session_key}".encode()
        assert ws_events._authorized({"headers": [(b"cookie", cookie)]}) is True
