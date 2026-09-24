from unittest.mock import MagicMock

import pytest

from cinefin.api.models import MoviePlayback
from cinefin.api.services.programme_service import ProgrammeService

from .factories import (
    BumperFactory,
    CertificationFactory,
    MovieFactory,
    PlaylistItemFactory,
    ProgrammeBlockFactory,
    ProgrammeFactory,
    block_for,
)

pytestmark = pytest.mark.django_db


class TestProgrammeBlockContentObject:
    def test_movie_block(self):
        movie = MovieFactory()
        block = block_for(ProgrammeFactory(), 0, "movie", movie)
        assert block.content_object == movie

    def test_certification_block_returns_reference_movie(self):
        movie = MovieFactory()
        block = block_for(ProgrammeFactory(), 0, "certification", movie)
        assert block.movie == movie
        assert block.content_object == movie

    def test_content_type_gates_which_fk_is_read(self):
        block = ProgrammeBlockFactory(content_type="bumper", movie=MovieFactory())
        assert block.content_object is None


class TestProgrammeBlockOnDelete:
    def test_block_survives_movie_deletion_with_snapshot(self):
        movie = MovieFactory(title="Gone Girl", year=2014)
        block = block_for(ProgrammeFactory(), 0, "movie", movie)

        movie.delete()
        block.refresh_from_db()

        assert block.movie is None
        assert block.content_object is None
        assert block.cached_title == "Gone Girl"
        assert block.cached_year == 2014

    def test_deleting_programme_cascades_to_blocks(self):
        movie = MovieFactory()
        programme = ProgrammeFactory()
        block = block_for(programme, 0, "movie", movie)

        programme.delete()

        assert not type(block).objects.filter(pk=block.pk).exists()
        assert type(movie).objects.filter(pk=movie.pk).exists()


class TestPlaylistItemContentObject:
    def test_movie_item_returns_movie_playback(self):
        playback = MoviePlayback.objects.create(movie=MovieFactory(), audio_track_index=1)
        item = PlaylistItemFactory(content_type="movie", movie_playback=playback)
        assert item.content_object == playback

    def test_certification_item(self):
        cert = CertificationFactory()
        item = PlaylistItemFactory(content_type="certification", certification=cert)
        assert item.content_object == cert

    def test_item_survives_movie_deletion_via_playback_cascade(self):
        movie = MovieFactory()
        playback = MoviePlayback.objects.create(movie=movie)
        item = PlaylistItemFactory(content_type="movie", movie_playback=playback)

        movie.delete()
        item.refresh_from_db()

        assert not MoviePlayback.objects.filter(pk=playback.pk).exists()
        assert item.movie_playback is None
        assert item.content_object is None


class TestMPVServiceLoadProgramme:
    def _service_with_mock_controller(self):
        from cinefin.api.mpv_service import MPVService

        service = MPVService()
        controller = MagicMock()
        controller.get_playlist.return_value = []
        service.controller = controller
        service._lazy_initialized = True
        return service, controller

    def _programme_with_playlist(self):
        movie = MovieFactory()
        bumper = BumperFactory()
        programme, _ = ProgrammeService.create_programme(
            name="MPV load test",
            items=[
                {"type": "bumper", "bumper_id": bumper.id},
                {"type": "movie", "movie_id": movie.id, "audio_track_index": 1},
            ],
        )
        return programme, movie

    def test_load_programme_enqueues_items_and_tracks_playbacks(self):
        programme, movie = self._programme_with_playlist()
        service, controller = self._service_with_mock_controller()

        assert service.load_programme(programme) is True
        assert service.programme_state == "loaded"
        assert service.current_playlist == programme.playlist

        enqueued = [call.args[0] for call in controller.enqueue_file.call_args_list]
        expected = [item.file for item in programme.playlist.items.order_by("order")]
        assert enqueued == expected

        movie_item = programme.playlist.items.get(content_type="movie")
        playback = movie_item.content_object
        assert isinstance(playback, MoviePlayback)
        assert playback.movie == movie
        assert service.audio_set == {playback.id: False}
        assert service.subtitle_set == {playback.id: False}

    def test_load_programme_without_playlist_fails(self):
        programme = ProgrammeFactory()
        service, _ = self._service_with_mock_controller()
        assert service.load_programme(programme) is False
