"""API smoke tests: one or two representative calls per Ninja router."""

import pytest

from .factories import (
    BumperFactory,
    CommandFactory,
    MovieFactory,
    ProgrammeFactory,
    ProgrammeScheduleFactory,
    ProgrammeTemplateItemFactory,
    SyncSourceFactory,
    TrailerFactory,
    block_for,
)

pytestmark = pytest.mark.django_db

API = "/api/v2"


@pytest.fixture
def reset_mpv_service():
    yield
    from cinefin.api.mpv_service import mpv_service

    mpv_service.terminate()


@pytest.mark.parametrize(
    ("url", "seed"),
    [
        ("/settings/", None),
        ("/movies/list", lambda: MovieFactory.create_batch(2)),
        ("/commands/list", CommandFactory),
        ("/templates/list", ProgrammeTemplateItemFactory),
        ("/programmes/list", ProgrammeFactory),
        ("/media/list", BumperFactory),
        ("/schedules/list", ProgrammeScheduleFactory),
        ("/sync/sources", SyncSourceFactory),
        ("/trailers/library", TrailerFactory),
        ("/playout/status", None),
        ("/mpv/status", None),
    ],
)
def test_list_endpoints_answer_an_envelope(client, reset_mpv_service, url, seed):
    if seed:
        seed()
    response = client.get(f"{API}{url}")
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_health_and_installer(client):
    assert client.get(f"{API}/health").json()["status"] == "healthy"
    assert client.get(f"{API}/installer/status").json()["configured"] is True
    assert client.post(f"{API}/system/health/db").json()["data"]["key"] == "db"
    assert client.post(f"{API}/system/health/nope").status_code == 404


def test_ticket_test_print_of_a_draft_design(client, monkeypatch):
    from cinefin.api.services import ticket_service

    printed = []
    monkeypatch.setattr(ticket_service, "print_ticket", lambda design, ctx: printed.append((design, ctx)))
    draft = {
        "elements": [{"type": "barcode", "content": "{ticket_no}", "symbology": "ean8"}],
        "time_format": "%I:%M %p",
    }
    response = client.post(f"{API}/tickets/test", {"design": draft}, content_type="application/json")
    assert response.status_code == 200
    design, ctx = printed[0]
    assert design["time_format"] == "%I:%M %p"
    assert design["elements"][0]["symbology"] == "ean8" and design["elements"][0]["align"] == "center"
    assert ctx["ticket_no"] == "142" and ctx["seat"] == response.json()["data"]["seat"]
    # The schema refuses an element it doesn't know.
    draft["elements"].append({"type": "bogus"})
    assert client.post(f"{API}/tickets/test", {"design": draft}, content_type="application/json").status_code == 422


def test_programme_create_detail_and_playlist(client):
    movie, bumper = MovieFactory(), BumperFactory()
    body = {
        "name": "Smoke",
        "items": [{"type": "bumper", "bumper_id": bumper.id}, {"type": "movie", "movie_id": movie.id}],
    }
    response = client.post(f"{API}/programmes/create", data=body, content_type="application/json")
    assert response.status_code == 201 and response.json()["data"]["name"] == "Smoke"

    programme = ProgrammeFactory()
    block_for(programme, 0, "movie", movie)
    assert client.get(f"{API}/programmes/{programme.id}").json()["success"] is True
    assert client.post(f"{API}/programmes/{programme.id}/regenerate-playlist").status_code == 200
    assert client.get(f"{API}/programmes/{programme.id}/playlist").json()["success"] is True
