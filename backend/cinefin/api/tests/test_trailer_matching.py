"""Trailer-rule matching (services/trailer_matching.py), TMDB certificates and trailer bulk delete."""

import os

import pytest

from cinefin.api.models import Trailer
from cinefin.api.services.trailer_matching import Criteria, select_trailers
from cinefin.api.services.trailer_service import TrailerService

from .factories import GenreFactory, MovieFactory, TrailerFactory

pytestmark = pytest.mark.django_db


def _ids(selected):
    return [t.id for t in selected]


class TestSelectTrailers:
    def test_hard_filters(self):
        ok = TrailerFactory(content_rating="12", year=2020)
        TrailerFactory(content_rating="18", year=2020)
        TrailerFactory(content_rating="12", year=1990)
        selected, _ = select_trailers(Criteria(certificate_ceiling="15", year_from=2018, year_to=2022), 5)
        assert _ids(selected) == [ok.id]

    def test_genres_match_any_ranked_by_overlap(self):
        action, scifi = GenreFactory(name="Action"), GenreFactory(name="Sci-Fi")
        both = TrailerFactory(content_rating="15", year=2020, genres=[action, scifi])
        one = TrailerFactory(content_rating="15", year=2020, genres=[action])
        TrailerFactory(content_rating="15", year=2020, genres=[GenreFactory(name="Drama")])
        selected, info = select_trailers(Criteria(genre_ids=[action.id, scifi.id]), 5)
        assert _ids(selected) == [both.id, one.id]
        assert info["matched"] == 2

    def test_reference_movie(self):
        horror = GenreFactory(name="Horror")
        feature = MovieFactory(year=2020, genres=[horror], tmdbid=555)
        TrailerFactory(content_rating="15", year=2020, tmdbid=555, genres=[horror])  # its own trailer: never
        near = TrailerFactory(content_rating="15", year=2019, genres=[horror])
        TrailerFactory(content_rating="15", year=2005, genres=[horror])
        for _ in range(5):  # year proximity ranks deterministically across shuffles
            selected, _ = select_trailers(Criteria(reference_movie=feature, genre_ids=[horror.id]), 1)
            assert _ids(selected) == [near.id]

    def test_exclude_ids_and_short_pool(self):
        horror = GenreFactory(name="Horror")
        TrailerFactory(content_rating="15", year=2020, genres=[horror])
        TrailerFactory(content_rating="15", year=2020, genres=[horror])
        crit = Criteria(genre_ids=[horror.id])
        first, _ = select_trailers(crit, 1)
        second, info = select_trailers(crit, 3, exclude_ids={first[0].id})
        assert first[0] not in second
        assert (info["short"], info["matched"], info["selected"]) == (True, 1, 1)


def test_tmdb_certificates_from_dicts_and_asobj():
    """tmdbv3api AsObj wrappers are not dict subclasses."""
    from tmdbv3api.as_obj import AsObj

    details = {
        "release_dates": {
            "results": [
                {
                    "iso_3166_1": "GB",
                    "release_dates": [{"certification": "", "type": 1}, {"certification": "12A", "type": 3}],
                },
                {"iso_3166_1": "US", "release_dates": [{"certification": "PG-13", "type": 3}]},
                {"iso_3166_1": "FR", "release_dates": [{"certification": "TP", "type": 3}]},
            ]
        }
    }
    service = TrailerService.__new__(TrailerService)
    assert service._get_certificates(details) == {"BBFC": "12A", "MPAA": "PG-13"}
    assert service._get_certificates(AsObj(details)) == {"BBFC": "12A", "MPAA": "PG-13"}
    assert service._get_certificates({}) == {}


def test_trailer_bulk_delete(client, tmp_path):
    url = "/api/v2/trailers/library/bulk-delete"

    def mk(title, with_file=True):
        path = tmp_path / f"{title}.mp4"
        if with_file:
            path.write_bytes(b"x")
        return TrailerFactory(title=title, file_path=str(path))

    a, b, keep = mk("A"), mk("B", with_file=False), mk("Keep")
    r = client.post(url, data={"ids": [a.id, b.id, 999999]}, content_type="application/json")
    data = r.json()["data"]
    assert (data["deleted"], data["files_removed"], data["missing"]) == (2, 1, [999999])

    r = client.post(url, data={"ids": [keep.id], "delete_files": False}, content_type="application/json")
    assert r.status_code == 200 and os.path.exists(keep.file_path)
    assert not Trailer.objects.exists()
    assert client.post(url, data={"ids": []}, content_type="application/json").status_code == 400
