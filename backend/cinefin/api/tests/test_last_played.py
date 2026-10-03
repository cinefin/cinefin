"""Every route that starts a programme stamps last_played_at, and only on success."""

import pytest

import cinefin.api.mpv_service as mpv_module
from cinefin.api.mpv_service import ProgrammeState
from cinefin.api.services import ProgrammeService, schedule_runner
from cinefin.api.services.playout_agent_service import playout_agent_service

from .factories import (
    MovieFactory,
    PlaylistFactory,
    PlaylistItemFactory,
    ProgrammeFactory,
    ProgrammeScheduleFactory,
    block_for,
)

pytestmark = pytest.mark.django_db

svc = mpv_module.mpv_service


def played(programme):
    programme.refresh_from_db()
    return programme.last_played_at is not None


@pytest.mark.parametrize("load_ok", [True, False])
def test_run(client, monkeypatch, load_ok):
    programme = ProgrammeFactory()
    block_for(programme, 0, "movie", MovieFactory())
    PlaylistFactory(programme=programme)
    monkeypatch.setattr(svc, "load_programme", lambda prog: load_ok)
    monkeypatch.setattr(svc, "start_programme", lambda preshow=False: True)
    monkeypatch.setattr(playout_agent_service, "ensure_mpv_running", lambda: True)
    if load_ok:
        ProgrammeService.run_programme(programme.id)
    else:
        assert client.post(f"/api/v2/programmes/{programme.id}/run").status_code == 422
    assert played(programme) is load_ok


@pytest.mark.parametrize(("start_ok", "status"), [(True, 200), (False, 422)])
def test_playout_start(client, monkeypatch, start_ok, status):
    programme = ProgrammeFactory()
    monkeypatch.setattr(svc, "current_programme", programme)
    monkeypatch.setattr(svc, "programme_state", ProgrammeState.LOADED)
    monkeypatch.setattr(svc, "manual_items", [])
    monkeypatch.setattr(svc, "snapshot", lambda: {"pause": True, "time": 0.0, "duration": 0.0, "pos": 0, "path": ""})
    monkeypatch.setattr(svc, "start_programme", lambda: start_ok)
    response = client.post("/api/v2/playout/control", {"action": "start"}, content_type="application/json")
    assert response.status_code == status
    assert played(programme) is start_ok


def test_schedule_runner(monkeypatch):
    programme = ProgrammeFactory()
    PlaylistItemFactory(playlist=PlaylistFactory(programme=programme), order=0)
    schedule = ProgrammeScheduleFactory(programme=programme, status="running")  # as claimed by tick()
    monkeypatch.setattr(svc, "load_programme", lambda prog: True)
    monkeypatch.setattr(svc, "start_programme", lambda: True)
    monkeypatch.setattr(schedule_runner.time, "sleep", lambda seconds: None)
    schedule_runner.execute_schedule(schedule)
    assert played(programme)
