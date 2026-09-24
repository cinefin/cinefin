"""PlaylistService smoke tests: block resolution + save round-trip.

build_playlist_from_programme appends a trailing "system" black-video item,
so tests filter on item type rather than asserting exact totals.
"""

import pytest

from cinefin.api.models import MoviePlayback, Playlist, TrailerRule
from cinefin.api.services.playlist_service import PlaylistService

from .factories import (
    BumperFactory,
    CertificationFactory,
    CommandFactory,
    GenreFactory,
    MovieFactory,
    ProgrammeFactory,
    TrailerFactory,
    TrailerRuleFactory,
    block_for,
)

pytestmark = pytest.mark.django_db


def items_of_type(items, item_type):
    return [i for i in items if i["type"] == item_type]


class TestBlockResolution:
    def test_movie_block(self):
        programme = ProgrammeFactory()
        movie = MovieFactory(title="Feature One")
        block_for(programme, 0, "movie", movie, audio_track_index=1)

        items = PlaylistService.build_playlist_from_programme(programme)
        movies = items_of_type(items, "movie")

        assert len(movies) == 1
        assert movies[0]["title"] == "Feature One"
        assert f"/stream/movie/{movie.id}/" in movies[0]["file_path"]
        assert movies[0]["content_id"] == movie.id
        assert movies[0]["audio_track"] == 1

    def test_command_block_default_is_instant_cue(self):
        programme = ProgrammeFactory()
        command = CommandFactory(name="Dim lights")
        block_for(programme, 0, "command", command)

        items = PlaylistService.build_playlist_from_programme(programme)

        assert items_of_type(items, "command") == []
        cues = items_of_type(items, "command_cue")
        assert len(cues) == 1
        assert cues[0]["content_id"] == command.id
        assert cues[0]["title"] == "Dim lights"

    def test_command_block_hold_black_emits_black_item(self):
        programme = ProgrammeFactory()
        command = CommandFactory(name="Close curtains", duration=8)
        block_for(programme, 0, "command", command, hold_black=True)

        items = PlaylistService.build_playlist_from_programme(programme)
        commands = items_of_type(items, "command")

        assert len(commands) == 1
        assert commands[0]["content_id"] == command.id
        assert commands[0]["duration"] == 8
        assert "/stream/system/black/" in commands[0]["file_path"]

    def test_certification_block(self, tmp_path):
        cert_file = tmp_path / "cert.mp4"
        cert_file.write_bytes(b"cert video")

        programme = ProgrammeFactory()
        movie = MovieFactory(certification="15")
        certification = CertificationFactory(movie=movie, certification="15", file_path=str(cert_file))
        block_for(programme, 0, "certification", movie)

        items = PlaylistService.build_playlist_from_programme(programme)
        certs = items_of_type(items, "certification")

        assert len(certs) == 1
        assert certs[0]["content_id"] == certification.id
        assert f"/stream/certification/{certification.id}/" in certs[0]["file_path"]
        assert certs[0]["metadata"]["certification"] == "15"

    def test_trailer_rule_block(self):
        genre = GenreFactory(name="Action")
        movie = MovieFactory(year=2020, certification="12A", genres=[genre])
        matching = TrailerFactory.create_batch(3, year=2021, content_rating="12A", genres=[genre])
        TrailerFactory(year=1990, content_rating="18", genres=[GenreFactory(name="Horror")])

        rule = TrailerRuleFactory(reference_movie=movie, number_of_trailers=2)
        programme = ProgrammeFactory()
        block_for(programme, 0, "trailer_rule", trailer_rule=rule)

        items = PlaylistService.build_playlist_from_programme(programme)
        trailers = items_of_type(items, "trailer")

        assert len(trailers) == 2
        matching_ids = {t.id for t in matching}
        assert all(t["content_id"] in matching_ids for t in trailers)
        assert all(t["metadata"]["reference_movie"] == movie.title for t in trailers)

    def test_feature_own_trailer_is_never_selected(self):
        genre = GenreFactory(name="Horror")
        movie = MovieFactory(title="The Mummy", year=2026, certification="15", genres=[genre], tmdbid=1304313)
        own = TrailerFactory(title="The Mummy", tmdbid=1304313, year=2026, content_rating="15", genres=[genre])
        TrailerFactory.create_batch(2, year=2026, content_rating="15", genres=[genre])

        rule = TrailerRuleFactory(reference_movie=movie, number_of_trailers=3)
        programme = ProgrammeFactory()
        block_for(programme, 0, "trailer_rule", trailer_rule=rule)

        # Selection is random — repeat to make a lucky pass implausible.
        for _ in range(5):
            items = PlaylistService.build_playlist_from_programme(programme)
            selected = {t["content_id"] for t in items_of_type(items, "trailer")}
            assert own.id not in selected

    def test_bound_trailer_rule_uses_default_count(self):
        # random_count=0 falls back to TrailerRule.DEFAULT_COUNT.
        genre = GenreFactory(name="Action")
        MovieFactory(year=2020, certification="12A", genres=[genre])
        TrailerFactory.create_batch(5, year=2020, content_rating="12A", genres=[genre])

        programme = ProgrammeFactory()
        block_for(programme, 0, "random_movie", random_count=1, random_movie_certification="12A")
        block_for(programme, 1, "trailer_rule", bound_to_block_order=0, random_count=0)

        items = PlaylistService.build_playlist_from_programme(programme)
        assert len(items_of_type(items, "trailer")) == TrailerRule.DEFAULT_COUNT

    def test_random_movie_block(self):
        genre = GenreFactory(name="Comedy")
        candidate = MovieFactory(year=2015, certification="PG", genres=[genre])
        MovieFactory(year=1980, certification="PG", genres=[genre])

        programme = ProgrammeFactory()
        block = block_for(
            programme,
            0,
            "random_movie",
            random_count=1,
            random_movie_certification="PG",
            random_movie_year_from=2010,
            random_movie_year_to=2020,
        )
        block.random_movie_genres.set([genre])

        items = PlaylistService.build_playlist_from_programme(programme)
        movies = items_of_type(items, "movie")

        assert len(movies) == 1
        assert movies[0]["content_id"] == candidate.id
        assert movies[0]["metadata"]["random_selection"] is True

    def test_blocks_resolve_in_order(self):
        programme = ProgrammeFactory()
        bumper = BumperFactory()
        movie = MovieFactory()
        block_for(programme, 0, "bumper", bumper)
        block_for(programme, 1, "movie", movie)

        items = PlaylistService.build_playlist_from_programme(programme)
        real_items = [i for i in items if i["type"] != "system"]

        assert [i["type"] for i in real_items] == ["bumper", "movie"]


class TestSavePlaylist:
    def test_round_trip(self):
        programme = ProgrammeFactory()
        bumper = BumperFactory()
        movie = MovieFactory()
        block_for(programme, 0, "bumper", bumper)
        block_for(programme, 1, "movie", movie, audio_track_index=0)

        items = PlaylistService.build_playlist_from_programme(programme)
        playlist = PlaylistService.save_playlist_to_database(programme, items)

        assert Playlist.objects.filter(programme=programme).count() == 1
        saved = list(playlist.items.order_by("order"))
        assert len(saved) == len(items)
        assert saved[0].content_type == "bumper"
        assert saved[0].content_object == bumper
        assert f"/stream/bumper/{bumper.id}/" in saved[0].file

        movie_item = next(i for i in saved if i.content_type == "movie")
        assert isinstance(movie_item.content_object, MoviePlayback)
        assert movie_item.content_object.movie == movie

    def test_instant_cue_attaches_to_next_item_and_orders_stay_dense(self):
        programme = ProgrammeFactory()
        command = CommandFactory(name="Dim lights")
        bumper = BumperFactory()
        block_for(programme, 0, "command", command)
        block_for(programme, 1, "bumper", bumper)

        items = PlaylistService.build_playlist_from_programme(programme)
        playlist = PlaylistService.save_playlist_to_database(programme, items)

        saved = list(playlist.items.order_by("order"))
        assert [i.content_type for i in saved] == ["bumper", "system"]
        assert [i.order for i in saved] == [0, 1]

        cue = playlist.cues.get()
        assert cue.command == command
        assert cue.fires_before_order == 0

    def test_trailing_instant_cue_attaches_to_end_sentinel(self):
        programme = ProgrammeFactory()
        bumper = BumperFactory()
        command = CommandFactory(name="Lights up")
        block_for(programme, 0, "bumper", bumper)
        block_for(programme, 1, "command", command)

        items = PlaylistService.build_playlist_from_programme(programme)
        playlist = PlaylistService.save_playlist_to_database(programme, items)

        sentinel = playlist.items.get(content_type="system")
        cue = playlist.cues.get()
        assert cue.fires_before_order == sentinel.order


class TestAudioBumperBlock:
    """Audio-format intros: explicit override > bound feature > next feature."""

    @staticmethod
    def _movie_with_track(codec, channels=6, **kw):
        from cinefin.api.models import AudioTrack

        movie = MovieFactory(**kw)
        AudioTrack.objects.create(movie=movie, language="en", codec=codec, channels=channels, index=0)
        return movie

    def test_bound_feature_beats_next_feature(self):
        programme = ProgrammeFactory()
        dd_movie = self._movie_with_track("ac3", title="DD Feature")
        atmos_movie = self._movie_with_track("truehd", channels=8, title="Atmos Feature")
        BumperFactory(title="DD intro", audio_format="dolby_digital")
        BumperFactory(title="Atmos intro", audio_format="dolby_atmos")
        # Intro bound to the DD feature though the Atmos feature comes first.
        block_for(programme, 0, "audio_bumper", None, movie=dd_movie)
        block_for(programme, 1, "movie", atmos_movie)
        block_for(programme, 2, "movie", dd_movie)

        items = PlaylistService.build_playlist_from_programme(programme)
        bumps = items_of_type(items, "bumper")
        assert [b["title"] for b in bumps] == ["DD intro"]
        assert bumps[0]["metadata"]["feature"] == "DD Feature"
