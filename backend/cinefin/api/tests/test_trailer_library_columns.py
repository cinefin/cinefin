"""The trailer library list reads file size live and sorts by size/duration (list columns).

Trailers don't store a size (only Movie does), so the endpoint stat()s the file — hence
the real temp files here rather than a stored value."""

import pytest

from .factories import MovieFactory, TrailerFactory

pytestmark = pytest.mark.django_db

API = "/api/v2"


def _rows(client, query=""):
    return client.get(f"{API}/trailers/library{query}").json()["data"]["trailers"]


class TestTrailerLibraryColumns:
    def test_file_size_is_read_live_and_sortable(self, client, tmp_path):
        big = tmp_path / "big.mp4"
        big.write_bytes(b"x" * 9000)
        small = tmp_path / "small.mp4"
        small.write_bytes(b"x" * 1000)
        TrailerFactory(title="Big", file_path=str(big))
        TrailerFactory(title="Small", file_path=str(small))

        rows = _rows(client, "?sort=-file_size")
        assert [r["title"] for r in rows] == ["Big", "Small"]
        assert {r["title"]: r["file_size"] for r in rows} == {"Big": 9000, "Small": 1000}

    def test_missing_file_reports_zero_size(self, client):
        TrailerFactory(title="Gone", file_path="/tmp/cinefin-tests/does-not-exist.mp4")
        assert _rows(client)[0]["file_size"] == 0

    def test_sort_by_duration(self, client):
        TrailerFactory(title="Short", duration=60)
        TrailerFactory(title="Long", duration=300)
        assert [r["title"] for r in _rows(client, "?sort=-duration")] == ["Long", "Short"]

    def test_on_disk_count_resolves_relative_paths(self, client, settings, tmp_path):
        """Trailer paths are stored MEDIA_ROOT-relative; the on-disk count must resolve them."""
        settings.MEDIA_ROOT = str(tmp_path)
        (tmp_path / "trailers").mkdir()
        (tmp_path / "trailers" / "here.mp4").write_bytes(b"x")
        TrailerFactory(title="Here", file_path="trailers/here.mp4")
        TrailerFactory(title="Gone", file_path="trailers/gone.mp4")

        stats = client.get(f"{API}/trailers/library").json()["data"]["stats"]
        assert (stats["with_file"], stats["missing"]) == (1, 1)


class TestTrailerLinkedMovie:
    def test_library_film_with_the_same_tmdbid_is_linked(self, client):
        movie = MovieFactory(title="Heat", tmdbid=949)
        t = TrailerFactory(title="Heat", tmdbid=949, associated_movie=None)

        assert _rows(client)[0]["has_movie"] is True
        detail = client.get(f"{API}/trailers/library/{t.id}").json()["data"]["trailer"]
        assert detail["associated_movie"]["id"] == movie.id

    def test_stored_link_wins_and_unmatched_stays_unlinked(self, client):
        linked = MovieFactory(title="Linked", tmdbid=1)
        MovieFactory(title="Same id", tmdbid=2)
        t = TrailerFactory(title="Trailer", tmdbid=2, associated_movie=linked)
        lone = TrailerFactory(title="Lone", tmdbid=3)

        assert t.linked_movie() == linked
        assert lone.linked_movie() is None
