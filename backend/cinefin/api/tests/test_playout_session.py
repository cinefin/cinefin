from unittest.mock import MagicMock

import pytest

from cinefin.api.models import PlayoutSession
from cinefin.api.mpv_service import MPVService, ProgrammeState
from cinefin.api.services.playlist_service import PlaylistService

from .factories import PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def make_service(items=None):
    service = MPVService()
    service.controller = MagicMock()
    service._lazy_initialized = True
    if items:
        playlist = PlaylistFactory(programme=ProgrammeFactory())
        for order, content_type in enumerate(items):
            PlaylistItemFactory(playlist=playlist, order=order, content_type=content_type)
        service.current_programme, service.current_playlist = playlist.programme, playlist
        service.playlist_offset, service.programme_state = 1, ProgrammeState.RUNNING
    return service


def test_state_transitions_are_persisted():
    service = make_service()
    programme = ProgrammeFactory()
    service.current_programme, service.playlist_offset = programme, 2
    service._set_state(ProgrammeState.LOADED)
    session = PlayoutSession.load()
    assert (session.state, session.programme_id, session.playlist_offset) == ("loaded", programme.id, 2)
    service._set_state(ProgrammeState.NOT_LOADED)
    session = PlayoutSession.load()
    assert (session.state, session.programme_id) == ("not_loaded", None)


class TestSessionRestore:
    def _persisted(self):
        playlist = PlaylistFactory(programme=ProgrammeFactory())
        PlaylistItemFactory(playlist=playlist, order=0)
        session = PlayoutSession.load()
        session.programme, session.state, session.playlist_offset = playlist.programme, ProgrammeState.RUNNING, 1
        session.credits_executed = [42]
        session.save()
        return playlist

    def test_clears_a_stale_session_when_mpv_is_empty(self):
        self._persisted()
        service = make_service()
        service.controller.get_playlist.return_value = []
        service._restore_session()
        assert service.programme_state == ProgrammeState.NOT_LOADED and service.current_programme is None
        session = PlayoutSession.load()
        assert (session.state, session.programme_id) == ("not_loaded", None)


class TestPreflight:
    def test_reports_a_missing_local_file_and_skips_commands(self, tmp_path):
        playlist = PlaylistFactory(programme=ProgrammeFactory())
        present = tmp_path / "present.mp4"
        present.write_bytes(b"x")
        PlaylistItemFactory(playlist=playlist, order=0, file=str(present))
        assert PlaylistService.verify_playlist_availability(playlist) == []
        PlaylistItemFactory(playlist=playlist, order=1, file="/tmp/definitely-missing-cinefin.mp4")
        PlaylistItemFactory(playlist=playlist, order=2, content_type="command", file="/media/system/black.mp4")
        warnings = PlaylistService.verify_playlist_availability(playlist)
        assert len(warnings) == 1 and "file missing on disk" in warnings[0]


class TestEndSentinel:
    """Only the trailing system item ends the programme, not a command item that also plays black."""

    def test_a_command_item_keeps_the_programme_running(self):
        service = make_service(["command", "movie", "system"])
        service.controller.get_property.return_value = 1
        service._handle_file_start("/media/system/black.mp4")
        assert service.programme_state == ProgrammeState.RUNNING and service.current_programme is not None

    @pytest.mark.parametrize("path", ["http://host/stream/system/black/", "/media/system/black.mp4"])
    def test_the_end_sentinel_goes_to_standby(self, path):
        service = make_service(["movie", "system"])
        service.controller.get_property.return_value = 2
        service.standby = MagicMock(return_value=True)
        service._handle_file_start(path)
        service.standby.assert_called_once_with()
