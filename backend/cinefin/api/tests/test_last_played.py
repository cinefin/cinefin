import pytest

from cinefin.api.services.playout_service import mark_programme_played

from .factories import (
    MovieFactory,
    PlaylistFactory,
    PlaylistItemFactory,
    ProgrammeFactory,
    ProgrammeScheduleFactory,
    block_for,
)

pytestmark = pytest.mark.django_db

API = "/api/v2"


class TestMarkProgrammePlayed:
    def test_sets_timestamp(self):
        programme = ProgrammeFactory()
        assert programme.last_played_at is None

        mark_programme_played(programme.id)

        programme.refresh_from_db()
        assert programme.last_played_at is not None

    def test_unknown_id_is_a_noop(self):
        mark_programme_played(999999)


class TestProgrammeRunPath:
    def _ready_programme(self):
        programme = ProgrammeFactory()
        block_for(programme, 0, "movie", MovieFactory())
        PlaylistFactory(programme=programme)
        return programme

    def _patch_mpv(self, monkeypatch, *, load_ok=True, start_ok=True):
        import cinefin.api.mpv_service as mpv_module
        from cinefin.api.services.playout_agent_service import playout_agent_service

        monkeypatch.setattr(mpv_module.mpv_service, "load_programme", lambda prog: load_ok, raising=False)
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda preshow=False: start_ok, raising=False)
        monkeypatch.setattr(playout_agent_service, "ensure_mpv_running", lambda: True, raising=False)

    def test_run_marks_played(self, client, monkeypatch):
        from cinefin.api.services import ProgrammeService

        programme = self._ready_programme()
        self._patch_mpv(monkeypatch)

        ProgrammeService.run_programme(programme.id)

        programme.refresh_from_db()
        assert programme.last_played_at is not None

    def test_failed_load_raises_and_does_not_mark(self, client, monkeypatch):
        """Regression: a load failure must surface as 422 and not stamp last_played_at."""
        programme = self._ready_programme()
        self._patch_mpv(monkeypatch, load_ok=False)

        response = client.post(f"{API}/programmes/{programme.id}/run")

        assert response.status_code == 422
        programme.refresh_from_db()
        assert programme.last_played_at is None


class TestPlayoutRunEndpoint:
    def _prime_mpv(self, monkeypatch, programme, start_ok=True):
        from cinefin.api.ninja_views import playout_ninja

        monkeypatch.setattr(playout_ninja.mpv_service, "current_programme", programme, raising=False)
        monkeypatch.setattr(playout_ninja.mpv_service, "start_programme", lambda: start_ok, raising=False)
        monkeypatch.setattr(playout_ninja.mpv_service, "get_status", lambda: {}, raising=False)

    def test_run_marks_played(self, client, monkeypatch):
        programme = ProgrammeFactory()
        self._prime_mpv(monkeypatch, programme)

        response = client.post(f"{API}/playout/run")

        assert response.status_code == 200
        programme.refresh_from_db()
        assert programme.last_played_at is not None

    def test_failed_start_does_not_mark(self, client, monkeypatch):
        programme = ProgrammeFactory()
        self._prime_mpv(monkeypatch, programme, start_ok=False)

        response = client.post(f"{API}/playout/run")

        assert response.status_code == 422
        programme.refresh_from_db()
        assert programme.last_played_at is None


class TestScheduleRunnerPath:
    def test_execute_schedule_marks_played(self, monkeypatch):
        import cinefin.api.mpv_service as mpv_module
        from cinefin.api.services import schedule_runner

        programme = ProgrammeFactory()
        PlaylistItemFactory(playlist=PlaylistFactory(programme=programme), order=0)
        schedule = ProgrammeScheduleFactory(programme=programme)

        monkeypatch.setattr(mpv_module.mpv_service, "load_programme", lambda prog: True, raising=False)
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda preshow=False: True, raising=False)
        monkeypatch.setattr(schedule_runner.time, "sleep", lambda seconds: None)

        schedule_runner.execute_schedule(schedule)

        programme.refresh_from_db()
        assert programme.last_played_at is not None
