import pytest

from .factories import CommandFactory, MovieFactory, ProgrammeBlockFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def test_composition_counts_blocks_by_type(client):
    programme = ProgrammeFactory()
    movie = MovieFactory()
    ProgrammeBlockFactory(programme=programme, content_type="movie", movie=movie, order=0)
    ProgrammeBlockFactory(programme=programme, content_type="movie", movie=MovieFactory(), order=1)
    ProgrammeBlockFactory(programme=programme, content_type="trailer_rule", order=2)
    ProgrammeBlockFactory(programme=programme, content_type="command", command=CommandFactory(), order=3)

    res = client.get("/api/v2/programmes/list")
    assert res.status_code == 200
    row = next(p for p in res.json()["data"]["programmes"] if p["id"] == programme.id)

    assert row["composition"] == {"movie": 2, "trailer_rule": 1, "command": 1}
    assert row["total_blocks"] == 4
    assert len(row["movies"]) == 2


def test_composition_is_empty_for_a_programme_with_no_blocks(client):
    programme = ProgrammeFactory()

    res = client.get("/api/v2/programmes/list")
    row = next(p for p in res.json()["data"]["programmes"] if p["id"] == programme.id)

    assert row["composition"] == {}
    assert row["total_blocks"] == 0
