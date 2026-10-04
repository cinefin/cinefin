"""has_trailer means a covering trailer with a file."""

import pytest

from cinefin.api.tests.factories import MovieFactory, TrailerFactory

pytestmark = pytest.mark.django_db


def _listed(client, query=""):
    items = client.get(f"/api/v2/movies/list?per_page=50{query}").json()["data"]["items"]
    return {m["title"]: m["has_trailer"] for m in items}


def test_list_and_filter_need_a_file(client):
    MovieFactory(title="Filed", tmdbid=1)
    MovieFactory(title="Empty", tmdbid=2)
    linked = MovieFactory(title="Linked", tmdbid=3)
    TrailerFactory(tmdbid=1)
    TrailerFactory(tmdbid=2, file_path="")
    TrailerFactory(tmdbid=0, associated_movie=linked)

    assert _listed(client) == {"Filed": True, "Empty": False, "Linked": True}
    assert set(_listed(client, "&has_trailer=true")) == {"Filed", "Linked"}
    assert set(_listed(client, "&has_trailer=false")) == {"Empty"}


def test_detail_needs_the_file_on_disk(client, tmp_path):
    on_disk = tmp_path / "t.mp4"
    on_disk.write_bytes(b"x")
    missing = MovieFactory(tmdbid=1)
    present = MovieFactory(tmdbid=2)
    TrailerFactory(tmdbid=1, file_path=str(tmp_path / "gone.mp4"))
    trailer = TrailerFactory(tmdbid=2, file_path=str(on_disk))

    data = client.get(f"/api/v2/movies/{missing.id}").json()["data"]
    assert (data["has_trailer"], data["trailer_id"]) == (False, None)
    data = client.get(f"/api/v2/movies/{present.id}").json()["data"]
    assert (data["has_trailer"], data["trailer_id"]) == (True, trailer.id)
