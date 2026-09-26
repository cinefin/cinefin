"""Clearing the library: the full-wipe endpoint + the delete-movies option on source removal."""

import pytest

from cinefin.api.models import Movie, SyncSource

from .factories import (
    MovieFactory,
    ProgrammeFactory,
    SyncSourceFactory,
    TrailerRuleFactory,
    block_for,
)

pytestmark = pytest.mark.django_db

API = "/api/v2"


class TestClearLibraryEndpoint:
    def test_preview_reports_total_and_in_use(self, client):
        MovieFactory.create_batch(3)
        used = MovieFactory()
        block_for(ProgrammeFactory(), order=0, content_type="movie", obj=used)
        TrailerRuleFactory(reference_movie=MovieFactory())  # a rule-referenced movie also counts

        data = client.get(f"{API}/movies/clear-library").json()["data"]
        assert data["total"] == 5
        assert data["in_use"] == 2

    def test_post_deletes_every_movie(self, client):
        MovieFactory.create_batch(4)
        resp = client.post(f"{API}/movies/clear-library")
        assert resp.status_code == 200
        assert resp.json()["data"]["deleted"] == 4
        assert Movie.objects.count() == 0

    def test_in_use_movie_is_deleted_but_programme_survives(self, client):
        movie = MovieFactory()
        programme = ProgrammeFactory()
        block = block_for(programme, order=0, content_type="movie", obj=movie)

        client.post(f"{API}/movies/clear-library")

        assert Movie.objects.count() == 0
        block.refresh_from_db()
        assert block.movie_id is None  # SET_NULL — the programme (and its block) survive

    def test_empty_library_reports_zero(self, client):
        resp = client.post(f"{API}/movies/clear-library")
        assert resp.json()["data"]["deleted"] == 0


class TestSourceRemovalDeletesMovies:
    def test_remove_source_keeps_movies_by_default(self, client):
        source = SyncSourceFactory()
        MovieFactory.create_batch(3, sync_source=source)

        resp = client.delete(f"{API}/sync/sources/{source.id}")
        assert resp.status_code == 200
        assert resp.json()["data"]["movies_deleted"] == 0
        assert Movie.objects.count() == 3  # orphaned (sync_source SET_NULL), not deleted
        assert not SyncSource.objects.filter(id=source.id).exists()

    def test_remove_source_with_flag_deletes_its_movies(self, client):
        source = SyncSourceFactory()
        MovieFactory.create_batch(3, sync_source=source)
        MovieFactory()  # a movie from no source stays

        resp = client.delete(f"{API}/sync/sources/{source.id}?delete_movies=true")
        assert resp.status_code == 200
        assert resp.json()["data"]["movies_deleted"] == 3
        assert Movie.objects.count() == 1
        assert not SyncSource.objects.filter(id=source.id).exists()

    def test_source_serialises_movie_count(self, client):
        source = SyncSourceFactory()
        MovieFactory.create_batch(2, sync_source=source)

        sources = client.get(f"{API}/sync/sources").json()["data"]["sources"]
        assert sources[0]["movie_count"] == 2
