"""Clearing the library: the full-wipe endpoint and the delete-movies option on source removal."""

import pytest

from cinefin.api.models import Movie, SyncSource

from .factories import MovieFactory, ProgrammeFactory, SyncSourceFactory, TrailerRuleFactory, block_for

pytestmark = pytest.mark.django_db

API = "/api/v2"


def test_clear_library(client):
    MovieFactory.create_batch(3)
    block = block_for(ProgrammeFactory(), order=0, content_type="movie", obj=MovieFactory())
    TrailerRuleFactory(reference_movie=MovieFactory())  # a rule-referenced movie also counts as in use

    data = client.get(f"{API}/movies/clear-library").json()["data"]
    assert (data["total"], data["in_use"]) == (5, 2)

    assert client.post(f"{API}/movies/clear-library").json()["data"]["deleted"] == 5
    assert Movie.objects.count() == 0
    block.refresh_from_db()
    assert block.movie_id is None  # SET_NULL: the programme and its block survive


@pytest.mark.parametrize(("query", "deleted", "left"), [("", 0, 4), ("?delete_movies=true", 3, 1)])
def test_remove_source(client, query, deleted, left):
    source = SyncSourceFactory()
    MovieFactory.create_batch(3, sync_source=source)
    MovieFactory()
    assert client.get(f"{API}/sync/sources").json()["data"]["sources"][0]["movie_count"] == 3

    r = client.delete(f"{API}/sync/sources/{source.id}{query}")
    assert r.json()["data"]["movies_deleted"] == deleted
    assert Movie.objects.count() == left
    assert not SyncSource.objects.filter(id=source.id).exists()
