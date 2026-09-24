"""API smoke tests: one or two representative calls per Ninja router."""

import pytest

from .factories import (
    BumperFactory,
    CommandFactory,
    MovieFactory,
    ProgrammeFactory,
    ProgrammeScheduleFactory,
    ProgrammeTemplateFactory,
    ProgrammeTemplateItemFactory,
    SyncSourceFactory,
    TrailerFactory,
    block_for,
)

pytestmark = pytest.mark.django_db

API = "/api/v2"


def assert_envelope(payload, success=True):
    assert payload["success"] is success
    assert "data" in payload


def test_health(client):
    response = client.get(f"{API}/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_installer_status(client):
    response = client.get(f"{API}/installer/status")
    assert response.status_code == 200
    assert response.json()["configured"] is True


def test_settings_get(client):
    response = client.get(f"{API}/settings/")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_movies_list(client):
    MovieFactory.create_batch(2)
    response = client.get(f"{API}/movies/list")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_movie_detail(client):
    movie = MovieFactory()
    response = client.get(f"{API}/movies/{movie.id}")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_movie_detail_404(client):
    response = client.get(f"{API}/movies/999999")
    assert response.status_code == 404
    assert response.json()["success"] is False


def test_commands_list(client):
    CommandFactory()
    response = client.get(f"{API}/commands/list")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_command_create(client):
    response = client.post(
        f"{API}/commands/create",
        data={"name": "Lights up", "provider": "rest", "config": {"url": "http://lights.invalid/on"}},
        content_type="application/json",
    )
    assert response.status_code == 201
    assert_envelope(response.json())


def test_templates_list(client):
    template = ProgrammeTemplateFactory()
    ProgrammeTemplateItemFactory(template=template)
    response = client.get(f"{API}/templates/list")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_programmes_list(client):
    ProgrammeFactory()
    response = client.get(f"{API}/programmes/list")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_programme_detail(client):
    programme = ProgrammeFactory()
    movie = MovieFactory()
    block_for(programme, 0, "movie", movie)
    response = client.get(f"{API}/programmes/{programme.id}")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_programme_create(client):
    movie = MovieFactory()
    bumper = BumperFactory()
    response = client.post(
        f"{API}/programmes/create",
        data={
            "name": "Smoke Test Programme",
            "description": "Created by the API smoke suite",
            "items": [
                {"type": "bumper", "bumper_id": bumper.id},
                {"type": "movie", "movie_id": movie.id},
            ],
            "preview": False,
        },
        content_type="application/json",
    )
    assert response.status_code == 201
    payload = response.json()
    assert_envelope(payload)
    assert payload["data"]["name"] == "Smoke Test Programme"


def test_programme_playlist(client):
    programme = ProgrammeFactory()
    movie = MovieFactory()
    block_for(programme, 0, "movie", movie)
    regen = client.post(f"{API}/programmes/{programme.id}/regenerate-playlist")
    assert regen.status_code == 200
    response = client.get(f"{API}/programmes/{programme.id}/playlist")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_media_list(client):
    BumperFactory()
    response = client.get(f"{API}/media/list")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_schedules_list(client):
    ProgrammeScheduleFactory()
    response = client.get(f"{API}/schedules/list")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_sync_sources(client):
    SyncSourceFactory()
    response = client.get(f"{API}/sync/sources")
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_trailers_list(client):
    TrailerFactory()
    response = client.get(f"{API}/trailers/list")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_tickets_settings(client):
    response = client.get(f"{API}/tickets/settings")
    assert response.status_code == 200
    assert_envelope(response.json())


# Resets the process-wide mpv_service singleton so lazy-init state can't leak
# into other tests or the atexit cleanup handler.
@pytest.fixture
def reset_mpv_service():
    yield
    from cinefin.api.mpv_service import mpv_service

    mpv_service.terminate()


def test_playout_status_degrades_without_mpv(client, reset_mpv_service):
    response = client.get(f"{API}/playout/status")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_mpv_status_degrades_without_mpv(client, reset_mpv_service):
    response = client.get(f"{API}/mpv/status")
    assert response.status_code == 200
