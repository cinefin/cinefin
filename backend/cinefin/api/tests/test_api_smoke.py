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


def test_system_health_recheck(client):
    response = client.post(f"{API}/system/health/db")
    assert response.status_code == 200
    assert_envelope(response.json())
    assert response.json()["data"]["key"] == "db"
    assert client.post(f"{API}/system/health/nope").status_code == 404


def test_installer_status(client):
    response = client.get(f"{API}/installer/status")
    assert response.status_code == 200
    assert response.json()["configured"] is True


def test_settings_get(client):
    response = client.get(f"{API}/settings/")
    assert response.status_code == 200
    assert_envelope(response.json())


def test_settings_ticket_cut_round_trips_and_validates(client):
    assert client.get(f"{API}/settings/").json()["data"]["settings"]["ticket_cut"] == "off"
    response = client.post(f"{API}/settings/", {"ticket_cut": "partial"}, content_type="application/json")
    assert response.status_code == 200
    assert client.get(f"{API}/settings/").json()["data"]["settings"]["ticket_cut"] == "partial"
    response = client.post(f"{API}/settings/", {"ticket_cut": "sideways"}, content_type="application/json")
    assert response.status_code == 400


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


def test_new_designs_start_from_a_starter(client):
    compact = client.post(
        f"{API}/tickets/designs", {"name": "C", "starter": "compact"}, content_type="application/json"
    )
    assert any(el["type"] == "columns" for el in compact.json()["elements"])
    blank = client.post(f"{API}/tickets/designs", {"name": "B", "starter": "blank"}, content_type="application/json")
    assert blank.json()["elements"] == []
    bad = client.post(f"{API}/tickets/designs", {"name": "X", "starter": "fancy"}, content_type="application/json")
    assert bad.status_code == 422


def test_ticket_design_fields_round_trip(client):
    design = client.post(f"{API}/tickets/designs", {"name": "Mine"}, content_type="application/json").json()
    assert [el["type"] for el in design["elements"]][:2] == ["text", "rule"]  # the Standard starter
    assert design["font"] == "courier" and design["date_format"] == "%d/%m/%Y" and design["qr_links"]
    url = f"{API}/tickets/designs/{design['id']}"
    body = {"font": "inter", "time_format": "%I:%M %p", "qr_links": [" https://a.example ", ""]}
    updated = client.put(url, body, content_type="application/json").json()
    assert (updated["font"], updated["time_format"], updated["qr_links"]) == (
        "inter",
        "%I:%M %p",
        ["https://a.example"],
    )
    assert client.put(url, {"font": "comic"}, content_type="application/json").status_code == 400
    assert client.put(url, {"qr_links": ["ftp://x"]}, content_type="application/json").status_code == 400
    copy = client.post(f"{url}/duplicate").json()
    assert copy["font"] == "inter" and copy["qr_links"] == ["https://a.example"]


def test_ticket_preview_of_a_draft_with_columns(client):
    draft = {
        "elements": [
            {"type": "columns", "widths": [1, 2], "cells": [[{"type": "text", "content": "{seat}"}], []]},
        ]
    }
    response = client.post(f"{API}/tickets/preview", {"design": draft}, content_type="application/json")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["url"].startswith("data:image/png;base64,") and data["width"] == 384
    (line,) = data["lines"]
    assert [cell["w"] for cell in line["cells"]] == [124, 248]


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
