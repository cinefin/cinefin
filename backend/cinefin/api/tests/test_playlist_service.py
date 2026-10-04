"""PlaylistService: block resolution and the save round-trip (a trailing "system" black item ends every playlist)."""

import importlib

import pytest

from cinefin.api.models import AudioTrack, MoviePlayback, TrailerRule
from cinefin.api.services.playlist_service import PlaylistService

from .factories import (
    BumperFactory,
    CommandFactory,
    GenreFactory,
    MovieFactory,
    ProgrammeFactory,
    TrailerFactory,
    TrailerRuleFactory,
    block_for,
)

pytestmark = pytest.mark.django_db


def build(programme, kind=None):
    items = PlaylistService.build_playlist_from_programme(programme)
    return items if kind is None else [i for i in items if i["type"] == kind]


def test_rundown_blocks_resolve_in_order():
    programme = ProgrammeFactory()
    bumper, movie = BumperFactory(), MovieFactory(title="Feature One")
    cue, held = CommandFactory(name="Dim lights"), CommandFactory(name="Close curtains", duration=8)
    block_for(programme, 0, "command", cue)
    block_for(programme, 1, "bumper", bumper)
    block_for(programme, 2, "command", held, hold_black=True)
    block_for(programme, 3, "movie", movie, audio_track_index=1)

    items = build(programme)
    assert [i["type"] for i in items] == ["command_cue", "bumper", "command", "movie", "system"]
    assert (items[0]["content_id"], items[0]["title"]) == (cue.id, "Dim lights")
    assert items[2]["duration"] == 8 and "/stream/system/black/" in items[2]["file_path"]
    assert f"/stream/movie/{movie.id}/" in items[3]["file_path"]
    assert (items[3]["title"], items[3]["audio_track"]) == ("Feature One", 1)


def test_feature_own_trailer_is_never_selected():
    genre = GenreFactory(name="Horror")
    movie = MovieFactory(title="The Mummy", year=2026, certification="15", genres=[genre], tmdbid=1304313)
    own = TrailerFactory(title="The Mummy", tmdbid=1304313, year=2026, content_rating="15", genres=[genre])
    TrailerFactory.create_batch(2, year=2026, content_rating="15", genres=[genre])
    programme = ProgrammeFactory()
    block_for(
        programme, 0, "trailer_rule", trailer_rule=TrailerRuleFactory(reference_movie=movie, number_of_trailers=3)
    )

    for _ in range(5):  # selection is random
        assert own.id not in {t["content_id"] for t in build(programme, "trailer")}


def test_random_movie_and_bound_trailer_rule_default_count():
    genre = GenreFactory(name="Comedy")
    candidate = MovieFactory(year=2015, certification="PG", genres=[genre])
    MovieFactory(year=1980, certification="PG", genres=[genre])
    TrailerFactory.create_batch(5, year=2015, content_rating="PG", genres=[genre])
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
    block_for(programme, 1, "trailer_rule", bound_to_block_order=0, random_count=0)

    items = build(programme)
    (movie,) = [i for i in items if i["type"] == "movie"]
    assert movie["content_id"] == candidate.id and movie["metadata"]["random_selection"] is True
    assert len([i for i in items if i["type"] == "trailer"]) == TrailerRule.DEFAULT_COUNT


def test_audio_bumper_follows_its_bound_feature():
    def movie_with(codec, channels, title):
        movie = MovieFactory(title=title)
        AudioTrack.objects.create(movie=movie, language="en", codec=codec, channels=channels, index=0)
        return movie

    programme = ProgrammeFactory()
    dd_movie, atmos_movie = movie_with("ac3", 6, "DD Feature"), movie_with("truehd", 8, "Atmos Feature")
    BumperFactory(title="DD intro", audio_format="dolby_digital")
    BumperFactory(title="Atmos intro", audio_format="dolby_atmos")
    block_for(programme, 0, "audio_bumper", None, movie=dd_movie)
    block_for(programme, 1, "movie", atmos_movie)
    block_for(programme, 2, "movie", dd_movie)

    (bump,) = build(programme, "bumper")
    assert (bump["title"], bump["metadata"]["feature"]) == ("DD intro", "DD Feature")


def test_unbound_audio_bumper_plays_nothing():
    programme = ProgrammeFactory()
    movie = MovieFactory()
    AudioTrack.objects.create(movie=movie, language="en", codec="ac3", channels=6, index=0)
    BumperFactory(audio_format="dolby_digital")
    block_for(programme, 0, "audio_bumper", None)
    block_for(programme, 1, "movie", movie)

    assert build(programme, "bumper") == []


def test_backfill_binds_unbound_audio_bumpers_to_the_next_feature():
    from django.apps import apps

    backfill = importlib.import_module("cinefin.api.migrations.0057_backfill_audio_bumper_feature").forwards
    programme = ProgrammeFactory()
    first, second = MovieFactory(), MovieFactory()
    bound = block_for(programme, 0, "audio_bumper", None, movie=second)
    unbound = block_for(programme, 1, "audio_bumper", None)
    block_for(programme, 2, "movie", first)
    trailing = block_for(programme, 3, "audio_bumper", None)

    backfill(apps, None)
    assert [b.movie for b in (bound, unbound, trailing) if not b.refresh_from_db()] == [second, first, None]


class TestSavePlaylist:
    def _save(self, programme):
        return PlaylistService.save_playlist_to_database(programme, build(programme))

    def test_round_trip_with_a_cue_on_the_next_item(self):
        programme = ProgrammeFactory()
        command, bumper, movie = CommandFactory(), BumperFactory(), MovieFactory()
        block_for(programme, 0, "command", command)
        block_for(programme, 1, "bumper", bumper)
        block_for(programme, 2, "movie", movie, audio_track_index=0)

        playlist = self._save(programme)
        saved = list(playlist.items.order_by("order"))
        assert [(i.order, i.content_type) for i in saved] == [(0, "bumper"), (1, "movie"), (2, "system")]
        assert saved[0].content_object == bumper and f"/stream/bumper/{bumper.id}/" in saved[0].file
        assert isinstance(saved[1].content_object, MoviePlayback) and saved[1].content_object.movie == movie
        cue = playlist.cues.get()
        assert (cue.command, cue.fires_before_order) == (command, 0)

    def test_trailing_cue_attaches_to_end_sentinel(self):
        programme = ProgrammeFactory()
        block_for(programme, 0, "bumper", BumperFactory())
        block_for(programme, 1, "command", CommandFactory())
        playlist = self._save(programme)
        assert playlist.cues.get().fires_before_order == playlist.items.get(content_type="system").order
