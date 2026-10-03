"""The trailer library list: live file size (trailers store none), sorting, on-disk counts, linked films."""

import pytest

from .factories import MovieFactory, TrailerFactory

pytestmark = pytest.mark.django_db

API = "/api/v2/trailers/library"


def _rows(client, query=""):
    return client.get(f"{API}{query}").json()["data"]["trailers"]


def test_file_size_is_read_live_and_sortable(client, tmp_path):
    for title, size in (("Big", 9000), ("Small", 1000)):
        (tmp_path / f"{title}.mp4").write_bytes(b"x" * size)
        TrailerFactory(title=title, file_path=str(tmp_path / f"{title}.mp4"), duration=size)
    TrailerFactory(title="Gone", file_path="/tmp/cinefin-tests/does-not-exist.mp4", duration=1)

    rows = _rows(client, "?sort=-file_size")
    assert [(r["title"], r["file_size"]) for r in rows] == [("Big", 9000), ("Small", 1000), ("Gone", 0)]
    assert [r["title"] for r in _rows(client, "?sort=-duration")] == ["Big", "Small", "Gone"]


def test_linked_movie(client):
    movie = MovieFactory(title="Heat", tmdbid=949)
    t = TrailerFactory(title="Heat", tmdbid=949, associated_movie=None)
    assert _rows(client)[0]["has_movie"] is True
    assert client.get(f"{API}/{t.id}").json()["data"]["trailer"]["associated_movie"]["id"] == movie.id

    linked = MovieFactory(title="Linked", tmdbid=1)
    MovieFactory(title="Same id", tmdbid=2)
    assert TrailerFactory(tmdbid=2, associated_movie=linked).linked_movie() == linked  # the stored link wins
    assert TrailerFactory(tmdbid=3).linked_movie() is None
