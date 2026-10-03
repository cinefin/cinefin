import pytest

from .factories import CommandFactory, MovieFactory, ProgrammeBlockFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def test_programme_list_composition(client):
    programme, empty = ProgrammeFactory(), ProgrammeFactory()
    ProgrammeBlockFactory(programme=programme, content_type="movie", movie=MovieFactory(), order=0)
    ProgrammeBlockFactory(programme=programme, content_type="movie", movie=MovieFactory(), order=1)
    ProgrammeBlockFactory(programme=programme, content_type="trailer_rule", order=2)
    ProgrammeBlockFactory(programme=programme, content_type="command", command=CommandFactory(), order=3)

    rows = {p["id"]: p for p in client.get("/api/v2/programmes/list").json()["data"]["programmes"]}
    row = rows[programme.id]
    assert row["composition"] == {"movie": 2, "trailer_rule": 1, "command": 1}
    assert (row["total_blocks"], len(row["movies"])) == (4, 2)
    assert (rows[empty.id]["composition"], rows[empty.id]["total_blocks"]) == ({}, 0)
