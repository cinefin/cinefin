"""Manual mode API: play or queue a film, trailer, media item or URL outside any programme."""

import pytest

from .factories import MovieFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


class TestManualApi:
    def test_url_must_be_http(self, client):
        r = client.post(
            "/api/v2/playout/manual", {"kind": "url", "url": "file:///etc/passwd"}, content_type="application/json"
        )
        assert r.status_code == 400

    def test_a_loaded_programme_blocks_unless_asked_to_end_it(self, client, monkeypatch):
        from cinefin.api.ninja_views import playout_ninja

        movie = MovieFactory()
        calls = []
        monkeypatch.setattr(playout_ninja, "resolve_media_path", lambda obj: "http://d/film")
        monkeypatch.setattr(playout_ninja.mpv_service, "current_programme", ProgrammeFactory())
        monkeypatch.setattr(playout_ninja.mpv_service, "reset", lambda: calls.append("reset") or True)
        monkeypatch.setattr(playout_ninja.mpv_service, "manual_add", lambda *a, **k: calls.append(a) or True)

        body = {"kind": "movie", "id": movie.id}
        assert client.post("/api/v2/playout/manual", body, content_type="application/json").status_code == 409
        body["end_programme"] = True
        assert client.post("/api/v2/playout/manual", body, content_type="application/json").status_code == 200
        assert calls[0] == "reset" and calls[1][1:] == ("movie", "http://d/film")
