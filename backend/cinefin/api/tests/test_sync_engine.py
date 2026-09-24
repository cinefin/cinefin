"""Sync engine smoke tests using a fake plugin."""

import pytest

from cinefin.api.exceptions import ConflictError, NotFoundError, ValidationError
from cinefin.api.models import Job, SyncSource
from cinefin.api.sync import engine, registry
from cinefin.api.sync.base import SyncSourcePlugin
from cinefin.api.sync.service import SyncManager

pytestmark = pytest.mark.django_db

FAKE_TYPE = "faketest"


class FakePlugin(SyncSourcePlugin):
    type_id = FAKE_TYPE
    label = "Fake Test Source"
    operations = ["sync", "boom"]
    needs_connection = True

    def test_connection(self):
        return True, "ok"

    def get_libraries(self):
        return ["Films"]

    def apply(self, ctx, operation, params):
        if operation == "boom":
            raise RuntimeError("kaboom")
        ctx.progress(1, 2, phase="Working", item="Fake Movie")
        ctx.check_cancelled()
        if params.get("cancel_midway"):
            Job.objects.filter(pk=ctx.job_id).update(state=Job.STATE_CANCELLING)
            ctx._cancel_checked_at = 0.0
            ctx.check_cancelled()
        ctx.progress(2, 2, phase="Working", item="Fake Movie 2")
        ctx.info("fake sync finished")
        return {"added": 2, "updated": 0, "removed": 0, "skipped": 0, "failed": 0}


@pytest.fixture
def fake_plugin():
    registry._ensure_loaded()
    registry.register(FakePlugin)
    yield FakePlugin
    registry._REGISTRY.pop(FAKE_TYPE, None)


@pytest.fixture
def fake_source(fake_plugin):
    return SyncSource.objects.create(
        name="Fake Source",
        sync_type=FAKE_TYPE,
        url="http://fake.invalid",
        token="fake-token",
        libraries="Films",
    )


def run_pending_job():
    assert engine._claim_and_run_one() is True


class TestJobLifecycle:
    def test_enqueue_creates_queued_job(self, fake_source):
        job = SyncManager.enqueue(fake_source.id)
        assert job.state == Job.STATE_QUEUED
        assert job.operation == "sync"
        assert job.is_active

    def test_job_runs_to_success(self, fake_source):
        job = SyncManager.enqueue(fake_source.id)
        run_pending_job()

        job.refresh_from_db()
        assert job.state == Job.STATE_SUCCESS
        assert job.counts["added"] == 2
        assert job.started_at is not None
        assert job.finished_at is not None
        assert any("fake sync finished" in entry["message"] for entry in job.log)

        fake_source.refresh_from_db()
        assert fake_source.last_sync is not None

    def test_progress_is_persisted(self, fake_source):
        job = SyncManager.enqueue(fake_source.id)
        run_pending_job()
        job.refresh_from_db()
        assert job.current == 2
        assert job.total == 2

    def test_failure_marks_job_failed(self, fake_source):
        job = SyncManager.enqueue(fake_source.id, operation="boom")
        run_pending_job()
        job.refresh_from_db()
        assert job.state == Job.STATE_FAILED
        assert "kaboom" in job.error

    def test_no_queued_job_returns_false(self, fake_source):
        assert engine._claim_and_run_one() is False


class TestCancellation:
    def test_cancel_queued_job(self, fake_source):
        job = SyncManager.enqueue(fake_source.id)
        cancelled = SyncManager.cancel_active(fake_source.id)
        assert cancelled.pk == job.pk
        assert cancelled.state == Job.STATE_CANCELLED
        assert engine._claim_and_run_one() is False

    def test_cancel_running_job(self, fake_source):
        job = SyncManager.enqueue(fake_source.id, params={"cancel_midway": True})
        run_pending_job()
        job.refresh_from_db()
        assert job.state == Job.STATE_CANCELLED

    def test_cancel_with_nothing_active_raises(self, fake_source):
        with pytest.raises(ValidationError):
            SyncManager.cancel_active(fake_source.id)


class TestSyncManagerGuards:
    def test_enqueue_rejects_second_active_job(self, fake_source):
        SyncManager.enqueue(fake_source.id)
        with pytest.raises(ValidationError):
            SyncManager.enqueue(fake_source.id)

    def test_enqueue_rejects_disabled_source(self, fake_source):
        fake_source.enabled = False
        fake_source.save()
        with pytest.raises(ValidationError):
            SyncManager.enqueue(fake_source.id)

    def test_enqueue_rejects_unknown_operation(self, fake_source):
        with pytest.raises(ValidationError):
            SyncManager.enqueue(fake_source.id, operation="does-not-exist")

    def test_unknown_source_raises(self):
        with pytest.raises(NotFoundError):
            SyncManager.get_source(999999)

    def test_list_types_includes_fake(self, fake_plugin):
        type_ids = [t["type_id"] for t in registry.list_types()]
        assert FAKE_TYPE in type_ids
        assert {"plex", "jellyfin"} <= set(type_ids)


class TestSingleSource:
    """A library has ONE source — see sync/service.py for why."""

    def _payload(self, name="Second", sync_type=FAKE_TYPE):
        return {
            "name": name,
            "sync_type": sync_type,
            "url": "http://other.invalid",
            "token": "another-token",
            "libraries": "Films",
        }

    def test_first_source_is_allowed(self, fake_plugin):
        source = SyncManager.create_source(self._payload(name="First"))
        assert SyncSource.objects.count() == 1
        assert SyncManager.the_source() == source

    def test_second_source_is_refused(self, fake_source):
        with pytest.raises(ConflictError):
            SyncManager.create_source(self._payload())
        assert SyncSource.objects.count() == 1

    def test_refusal_names_the_source_in_the_way(self, fake_source):
        with pytest.raises(ConflictError) as excinfo:
            SyncManager.create_source(self._payload())
        assert fake_source.name in str(excinfo.value)

    def test_a_second_source_is_allowed_once_the_first_is_removed(self, fake_source):
        SyncManager.delete_source(fake_source.id)
        replacement = SyncManager.create_source(self._payload(name="Replacement"))
        assert SyncManager.the_source() == replacement

    def test_the_source_is_none_before_one_is_configured(self, fake_plugin):
        assert SyncManager.the_source() is None


class TestSingleSourceEndpoint:
    def test_returns_the_source(self, client, fake_source):
        response = client.get("/api/v2/sync/source")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["source"]["name"] == fake_source.name
        assert data["types"]

    def test_returns_null_when_unconfigured(self, client, fake_plugin):
        response = client.get("/api/v2/sync/source")
        assert response.status_code == 200
        assert response.json()["data"]["source"] is None

    def test_api_refuses_a_second_source(self, client, fake_source):
        response = client.post(
            "/api/v2/sync/sources",
            data={
                "name": "Second",
                "sync_type": FAKE_TYPE,
                "url": "http://other.invalid",
                "token": "tok",
                "libraries": "Films",
            },
            content_type="application/json",
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "SYNC_SOURCE_EXISTS"


class TestRecovery:
    def test_orphaned_running_job_is_failed_when_out_of_attempts(self, fake_source):
        job = Job.sync.create(source=fake_source, operation="sync", state=Job.STATE_RUNNING, attempts=1, max_attempts=1)

        engine._recover_orphans()

        job.refresh_from_db()
        assert job.state == Job.STATE_FAILED

    def test_orphaned_job_with_attempts_left_is_requeued(self, fake_source):
        job = Job.sync.create(source=fake_source, operation="sync", state=Job.STATE_RUNNING, attempts=0, max_attempts=1)
        engine._recover_orphans()
        job.refresh_from_db()
        assert job.state == Job.STATE_QUEUED


class TestKindIsolation:
    """Sync and trailer jobs share one table but must never cross drivers."""

    def test_engine_never_claims_trailer_jobs(self):
        trailer_job = Job.trailer.create(operation="verify")
        assert engine._claim_and_run_one() is False
        trailer_job.refresh_from_db()
        assert trailer_job.state == Job.STATE_QUEUED

    def test_engine_recovery_ignores_trailer_jobs(self):
        trailer_job = Job.trailer.create(operation="verify", state=Job.STATE_RUNNING)
        engine._recover_orphans()
        trailer_job.refresh_from_db()
        assert trailer_job.state == Job.STATE_RUNNING

    def test_trailer_recovery_ignores_sync_jobs(self, fake_source):
        from cinefin.api.services import trailer_jobs

        sync_job = Job.sync.create(source=fake_source, operation="sync", state=Job.STATE_RUNNING)
        trailer_job = Job.trailer.create(operation="verify", state=Job.STATE_RUNNING)
        trailer_jobs.recover_orphans()
        sync_job.refresh_from_db()
        trailer_job.refresh_from_db()
        assert sync_job.state == Job.STATE_RUNNING
        assert trailer_job.state == Job.STATE_FAILED

    def test_active_trailer_job_blocks_only_trailer_starts(self, fake_source):
        from cinefin.api.services import trailer_jobs

        Job.trailer.create(operation="verify", state=Job.STATE_RUNNING)
        with pytest.raises(RuntimeError):
            trailer_jobs.start_job("verify")
        job = SyncManager.enqueue(fake_source.id)
        assert job.kind == Job.KIND_SYNC
        assert job.state == Job.STATE_QUEUED
