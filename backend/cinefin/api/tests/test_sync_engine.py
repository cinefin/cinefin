"""Sync engine and SyncManager tests using a fake plugin."""

import pytest

from cinefin.api.exceptions import ConflictError, ValidationError
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


SOURCE = {"sync_type": FAKE_TYPE, "url": "http://fake.invalid", "token": "fake-token", "libraries": "Films"}


@pytest.fixture
def fake_source(fake_plugin):
    return SyncSource.objects.create(name="Fake Source", **SOURCE)


def run(job):
    assert engine._claim_and_run_one() is True
    job.refresh_from_db()
    return job


class TestJobLifecycle:
    def test_job_runs_to_success(self, fake_source):
        job = SyncManager.enqueue(fake_source.id)
        assert (job.state, job.operation) == (Job.STATE_QUEUED, "sync")
        job = run(job)
        assert job.state == Job.STATE_SUCCESS
        assert (job.counts["added"], job.current, job.total) == (2, 2, 2)
        assert job.finished_at is not None
        assert any("fake sync finished" in entry["message"] for entry in job.log)
        fake_source.refresh_from_db()
        assert fake_source.last_sync is not None
        assert engine._claim_and_run_one() is False

    def test_failure_marks_job_failed(self, fake_source):
        job = run(SyncManager.enqueue(fake_source.id, operation="boom"))
        assert job.state == Job.STATE_FAILED and "kaboom" in job.error

    def test_cancel_queued_and_running(self, fake_source):
        job = SyncManager.enqueue(fake_source.id)
        assert SyncManager.cancel_active(fake_source.id).pk == job.pk
        assert engine._claim_and_run_one() is False
        with pytest.raises(ValidationError):
            SyncManager.cancel_active(fake_source.id)

        job = run(SyncManager.enqueue(fake_source.id, params={"cancel_midway": True}))
        assert job.state == Job.STATE_CANCELLED

    @pytest.mark.parametrize("case", ["second_active", "disabled", "unknown_operation"])
    def test_enqueue_guards(self, fake_source, case):
        operation = "sync"
        if case == "second_active":
            SyncManager.enqueue(fake_source.id)
        elif case == "disabled":
            fake_source.enabled = False
            fake_source.save()
        else:
            operation = "does-not-exist"
        with pytest.raises(ValidationError):
            SyncManager.enqueue(fake_source.id, operation=operation)

    @pytest.mark.parametrize(("attempts", "state"), [(1, Job.STATE_FAILED), (0, Job.STATE_QUEUED)])
    def test_orphaned_running_job_recovery(self, fake_source, attempts, state):
        job = Job.sync.create(
            source=fake_source, operation="sync", state=Job.STATE_RUNNING, attempts=attempts, max_attempts=1
        )
        engine._recover_orphans()
        job.refresh_from_db()
        assert job.state == state


class TestSingleSource:
    """A library has ONE source; see sync/service.py for why."""

    def test_second_source_is_refused_until_the_first_is_removed(self, fake_source):
        with pytest.raises(ConflictError) as excinfo:
            SyncManager.create_source({"name": "Second", **SOURCE})
        assert fake_source.name in str(excinfo.value)
        SyncManager.delete_source(fake_source.id)
        replacement = SyncManager.create_source({"name": "Replacement", **SOURCE})
        assert SyncManager.the_source() == replacement


class TestKindIsolation:
    """Sync and trailer jobs share one table but must never cross drivers."""

    def test_engine_ignores_trailer_jobs(self):
        queued = Job.trailer.create(operation="verify")
        running = Job.trailer.create(operation="verify", state=Job.STATE_RUNNING)
        assert engine._claim_and_run_one() is False
        engine._recover_orphans()
        queued.refresh_from_db()
        running.refresh_from_db()
        assert (queued.state, running.state) == (Job.STATE_QUEUED, Job.STATE_RUNNING)
