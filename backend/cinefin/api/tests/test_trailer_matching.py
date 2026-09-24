"""Trailer-rule matching (services/trailer_matching.py)."""

import pytest

from cinefin.api.services.trailer_matching import (
    Criteria,
    match_stats,
    ratings_at_or_below,
    select_trailers,
)

from .factories import GenreFactory, MovieFactory, TrailerFactory

pytestmark = pytest.mark.django_db


class TestRatingsAtOrBelow:
    def test_bbfc_fifteen_admits_everything_up_to_fifteen(self):
        assert ratings_at_or_below("15", "BBFC") == ["U", "PG", "12", "12A", "15"]

    def test_lowest_rating_admits_only_itself(self):
        assert ratings_at_or_below("U", "BBFC") == ["U"]

    def test_unknown_rating_falls_back_to_exact_match(self):
        assert ratings_at_or_below("AA", "BBFC") == ["AA"]

    def test_mpaa_order(self):
        assert ratings_at_or_below("PG-13", "MPAA") == ["G", "PG", "PG-13"]


class TestSelectTrailers:
    def test_certificate_ceiling_is_hard(self):
        horror = GenreFactory(name="Horror")
        ok = TrailerFactory(content_rating="12", year=2020, genres=[horror])
        TrailerFactory(content_rating="18", year=2020, genres=[horror])
        selected, _ = select_trailers(Criteria(certificate_ceiling="15"), 5)
        ids = {t.id for t in selected}
        assert ok.id in ids
        assert all(t.content_rating in ("U", "PG", "12", "12A", "15") for t in selected)

    def test_genres_best_effort_match_any_ranked_by_overlap(self):
        action = GenreFactory(name="Action")
        scifi = GenreFactory(name="Sci-Fi")
        drama = GenreFactory(name="Drama")
        both = TrailerFactory(content_rating="15", year=2020, genres=[action, scifi])
        one = TrailerFactory(content_rating="15", year=2020, genres=[action])
        TrailerFactory(content_rating="15", year=2020, genres=[drama])
        selected, info = select_trailers(Criteria(genre_ids=[action.id, scifi.id]), 5)
        ids = [t.id for t in selected]
        assert set(ids) == {both.id, one.id}
        assert ids[0] == both.id  # sharing MORE genres ranks first
        assert info["matched"] == 2

    def test_criteria_only_rule_needs_no_reference(self):
        horror = GenreFactory(name="Horror")
        keep = TrailerFactory(content_rating="15", year=2021, genres=[horror])
        TrailerFactory(content_rating="15", year=2021, genres=[GenreFactory(name="Comedy")])
        selected, info = select_trailers(Criteria(genre_ids=[horror.id]), 5)
        assert [t.id for t in selected] == [keep.id]
        assert info["matched"] == 1

    def test_year_window_is_hard(self):
        recent = TrailerFactory(content_rating="15", year=2020)
        TrailerFactory(content_rating="15", year=1990)
        selected, _ = select_trailers(Criteria(year_from=2018, year_to=2022), 5)
        assert [t.id for t in selected] == [recent.id]

    def test_own_trailer_never_selected(self):
        feature = MovieFactory(certification="15", year=2020, tmdbid=555)
        TrailerFactory(content_rating="15", year=2020, tmdbid=555)
        selected, info = select_trailers(Criteria(reference_movie=feature), 5)
        assert selected == []
        assert info["matched"] == 0

    def test_reference_ranks_by_year_proximity(self):
        horror = GenreFactory(name="Horror")
        feature = MovieFactory(year=2020, genres=[horror])
        near = TrailerFactory(content_rating="15", year=2019, genres=[horror])
        TrailerFactory(content_rating="15", year=2005, genres=[horror])
        for _ in range(5):  # deterministic across shuffles
            selected, _ = select_trailers(Criteria(reference_movie=feature, genre_ids=[horror.id]), 1)
            assert selected[0].id == near.id

    def test_exclude_ids_dedupes_across_blocks(self):
        horror = GenreFactory(name="Horror")
        TrailerFactory(content_rating="15", year=2020, genres=[horror])
        TrailerFactory(content_rating="15", year=2020, genres=[horror])
        crit = Criteria(genre_ids=[horror.id])
        first, _ = select_trailers(crit, 1)
        used = {first[0].id}
        second, _ = select_trailers(crit, 1, exclude_ids=used)
        assert second[0].id not in used

    def test_short_flag_when_pool_undershoots(self):
        horror = GenreFactory(name="Horror")
        TrailerFactory(content_rating="15", year=2020, genres=[horror])
        _, info = select_trailers(Criteria(genre_ids=[horror.id]), 3)
        assert info["short"] is True
        assert info["matched"] == 1
        assert info["selected"] == 1


class TestPoolCountAndStats:
    def test_match_stats_reports_pool_and_duration(self):
        horror = GenreFactory(name="Horror")
        TrailerFactory(content_rating="12", year=2020, genres=[horror], duration=120)
        TrailerFactory(content_rating="18", year=2020, genres=[GenreFactory(name="Comedy")])
        stats = match_stats(Criteria(genre_ids=[horror.id]))
        assert stats["matched"] == 1
        assert stats["avg_duration"] == 120


class TestTmdbCertificateExtraction:
    """regression: _get_certificates must handle tmdbv3api AsObj wrappers (not dict subclasses)."""

    DETAILS = {
        "release_dates": {
            "results": [
                {
                    "iso_3166_1": "GB",
                    "release_dates": [
                        {"certification": "", "type": 1},
                        {"certification": "12A", "type": 3},
                    ],
                },
                {"iso_3166_1": "US", "release_dates": [{"certification": "PG-13", "type": 3}]},
                {"iso_3166_1": "FR", "release_dates": [{"certification": "TP", "type": 3}]},
            ]
        }
    }

    def _service(self):
        from cinefin.api.services.trailer_service import TrailerService

        return TrailerService.__new__(TrailerService)

    def test_extracts_from_plain_dicts(self):
        certs = self._service()._get_certificates(self.DETAILS)
        assert certs == {"BBFC": "12A", "MPAA": "PG-13"}

    def test_extracts_from_asobj_payload(self):
        from tmdbv3api.as_obj import AsObj

        certs = self._service()._get_certificates(AsObj(self.DETAILS))
        assert certs == {"BBFC": "12A", "MPAA": "PG-13"}

    def test_missing_release_dates_yields_empty(self):
        assert self._service()._get_certificates({}) == {}


class TestTrailerBulkDelete:
    URL = "/api/v2/trailers/library/bulk-delete"

    def _mk(self, tmp_path, title, with_file=True):
        from cinefin.api.models import Trailer

        path = tmp_path / f"{title}.mp4"
        if with_file:
            path.write_bytes(b"x")
        return Trailer.objects.create(
            title=title, year=2024, file_path=str(path), content_rating="12A", month=1, duration=10
        )

    def test_bulk_delete_removes_records_and_files(self, client, tmp_path):
        import json

        from cinefin.api.models import Trailer

        a = self._mk(tmp_path, "A")
        b = self._mk(tmp_path, "B", with_file=False)
        resp = client.post(self.URL, data=json.dumps({"ids": [a.id, b.id, 999999]}), content_type="application/json")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["deleted"] == 2
        assert data["files_removed"] == 1
        assert data["missing"] == [999999]
        assert Trailer.objects.count() == 0

    def test_bulk_delete_keeps_files_when_asked(self, client, tmp_path):
        import json
        import os

        t = self._mk(tmp_path, "Keep")
        resp = client.post(
            self.URL, data=json.dumps({"ids": [t.id], "delete_files": False}), content_type="application/json"
        )
        assert resp.status_code == 200
        assert os.path.exists(t.file_path)

    def test_bulk_delete_empty_ids_rejected(self, client):
        import json

        resp = client.post(self.URL, data=json.dumps({"ids": []}), content_type="application/json")
        assert resp.status_code == 400
