from unittest.mock import MagicMock

import pytest

from cinefin.api.models import Bumper, PlayoutSession, Settings
from cinefin.api.mpv_service import MPVService, ProgrammeState
from cinefin.api.services.playlist_service import PlaylistService

from .factories import MovieFactory, PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def make_service():
    service = MPVService()
    service.controller = MagicMock()
    service._lazy_initialized = True
    return service


class TestPreShowState:
    """Regression: a RUNNING programme on its opening item must report pre_show (the old local-path check never matched a stream URL)."""

    def _running_service(self, offset=1):
        programme = ProgrammeFactory()
        playlist = PlaylistFactory(programme=programme)
        for order, ct in enumerate(["movie", "system"]):
            PlaylistItemFactory(playlist=playlist, order=order, content_type=ct)
        service = make_service()
        service.current_programme = programme
        service.current_playlist = playlist
        service.playlist_offset = offset
        service.programme_state = ProgrammeState.RUNNING
        service._ensure_connected = lambda: True
        service.controller.get_playlist.return_value = []
        return service

    def _status(self, service, playlist_pos, file_path=""):
        service.get_status = lambda: {
            "playback_status": "playing",
            "playlist_pos": playlist_pos,
            "file_path": file_path,
            "time": 2.0,
            "length": 10.0,
        }
        return service.get_enhanced_status()

    def test_opening_item_reports_pre_show(self):
        service = self._running_service()
        status = self._status(service, 0, "http://h/stream/system/ident/?t=abc")
        assert status["programme"]["state"] == "pre_show"

    def test_title_card_also_reports_pre_show(self):
        service = self._running_service()
        status = self._status(service, 0, "http://h/stream/title/7/?t=abc")
        assert status["programme"]["state"] == "pre_show"

    def test_first_programme_item_is_not_pre_show(self):
        service = self._running_service()
        status = self._status(service, 1, "http://h/stream/movie/3/?t=abc")
        assert status["programme"]["state"] == ProgrammeState.RUNNING

    def test_no_offset_means_no_pre_show(self):
        service = self._running_service(offset=0)
        status = self._status(service, 0, "http://h/stream/movie/3/?t=abc")
        assert status["programme"]["state"] == ProgrammeState.RUNNING

    def test_disconnected_mpv_is_not_pre_show(self):
        service = self._running_service()
        service.get_status = lambda: None
        assert service.get_enhanced_status()["programme"]["state"] == ProgrammeState.RUNNING

    def test_transport_controls_stay_available_during_pre_show(self):
        service = self._running_service()
        programme = self._status(service, 0)["programme"]
        assert programme["state"] == "pre_show"
        assert programme["can_pause"] is True
        assert programme["can_stop"] is True


class TestEnhancedStatusWhenDisconnected:
    """Regression: get_enhanced_status must degrade cleanly (not raise UnboundLocalError) when MPV drops mid-poll."""

    def test_no_crash_and_disconnected_state(self):
        programme = ProgrammeFactory()
        playlist = PlaylistFactory(programme=programme)
        for order, ct in enumerate(["movie", "system"]):
            PlaylistItemFactory(playlist=playlist, order=order, content_type=ct)

        service = make_service()
        service.current_programme = programme
        service.current_playlist = playlist
        service.playlist_offset = 1
        service.programme_state = ProgrammeState.RUNNING
        service.controller.get_playlist.return_value = []
        service._ensure_connected = lambda: True
        service.get_status = lambda: None

        status = service.get_enhanced_status()

        assert status["playback"]["state"] == "disconnected"
        assert status["playlist"]["programme_position"] is None
        assert status["playlist"]["current_item"] is None


class TestSessionPersistence:
    def test_state_transitions_are_persisted(self):
        service = make_service()
        programme = ProgrammeFactory()
        service.current_programme = programme
        service.playlist_offset = 2

        service._set_state(ProgrammeState.LOADED)

        session = PlayoutSession.load()
        assert session.state == "loaded"
        assert session.programme_id == programme.id
        assert session.playlist_offset == 2

    def test_not_loaded_clears_programme_reference(self):
        service = make_service()
        service.current_programme = ProgrammeFactory()
        service._set_state(ProgrammeState.LOADED)
        service._set_state(ProgrammeState.NOT_LOADED)

        session = PlayoutSession.load()
        assert session.state == "not_loaded"
        assert session.programme_id is None


class TestSessionRestore:
    def _persisted_running_session(self):
        programme = ProgrammeFactory()
        playlist = PlaylistFactory(programme=programme)
        PlaylistItemFactory(playlist=playlist, order=0)
        session = PlayoutSession.load()
        session.programme = programme
        session.state = ProgrammeState.RUNNING
        session.playlist_offset = 1
        session.credits_executed = [42]
        session.save()
        return programme, playlist

    def test_reattaches_when_mpv_still_has_playlist(self):
        programme, playlist = self._persisted_running_session()
        service = make_service()
        service.controller.get_playlist.return_value = [{"filename": "a"}, {"filename": "b"}]

        service._restore_session()

        assert service.programme_state == ProgrammeState.RUNNING
        assert service.current_programme == programme
        assert service.current_playlist == playlist
        assert service.playlist_offset == 1
        assert service.credits_executed == {42: True}

    def test_clears_stale_session_when_mpv_is_empty(self):
        self._persisted_running_session()
        service = make_service()
        service.controller.get_playlist.return_value = []

        service._restore_session()

        assert service.programme_state == ProgrammeState.NOT_LOADED
        assert service.current_programme is None
        session = PlayoutSession.load()
        assert session.state == "not_loaded"
        assert session.programme_id is None

    def test_restore_runs_only_once(self):
        programme, _ = self._persisted_running_session()
        service = make_service()
        service.controller.get_playlist.return_value = [{"filename": "a"}, {"filename": "b"}]

        service._restore_session()
        service.current_programme = None
        service._restore_session()

        assert service.current_programme is None

    def test_no_session_is_a_noop(self):
        service = make_service()
        service._restore_session()
        assert service.programme_state == ProgrammeState.NOT_LOADED


class TestPreflight:
    def test_reports_missing_local_file_and_skips_commands(self, tmp_path):
        movie = MovieFactory()
        programme = ProgrammeFactory()
        playlist = PlaylistFactory(programme=programme)

        present = tmp_path / "present.mp4"
        present.write_bytes(b"x")
        PlaylistItemFactory(playlist=playlist, order=0, file=str(present))
        PlaylistItemFactory(playlist=playlist, order=1, file="/tmp/definitely-missing-cinefin.mp4")
        PlaylistItemFactory(playlist=playlist, order=2, content_type="command", file="/media/system/black.mp4")

        warnings = PlaylistService.verify_playlist_availability(playlist)

        assert len(warnings) == 1
        assert "file missing on disk" in warnings[0]
        del movie

    def test_reports_http_errors(self, monkeypatch):
        programme = ProgrammeFactory()
        playlist = PlaylistFactory(programme=programme)
        PlaylistItemFactory(playlist=playlist, order=0, file="http://media.invalid/stream/bumper/1/")

        class FakeResponse:
            status_code = 404

        class FakeSession:
            def head(self, *a, **kw):
                return FakeResponse()

        monkeypatch.setattr("cinefin.api.services.playlist_service.requests.Session", FakeSession)

        warnings = PlaylistService.verify_playlist_availability(playlist)
        assert len(warnings) == 1
        assert "HTTP 404" in warnings[0]

    def test_all_reachable_returns_empty(self, tmp_path):
        programme = ProgrammeFactory()
        playlist = PlaylistFactory(programme=programme)
        f = tmp_path / "ok.mp4"
        f.write_bytes(b"x")
        PlaylistItemFactory(playlist=playlist, order=0, file=str(f))

        assert PlaylistService.verify_playlist_availability(playlist) == []


class TestBlackSentinelDisambiguation:
    """Regression: only the trailing system item ends the programme, not a command item that also plays black.mp4."""

    def _service_with_playlist(self, items):
        programme = ProgrammeFactory()
        playlist = PlaylistFactory(programme=programme)
        for order, content_type in enumerate(items):
            PlaylistItemFactory(playlist=playlist, order=order, content_type=content_type)
        service = make_service()
        service.current_programme = programme
        service.current_playlist = playlist
        service.playlist_offset = 1
        service.programme_state = ProgrammeState.RUNNING
        return service

    def test_command_item_is_not_the_end(self):
        service = self._service_with_playlist(["command", "movie", "system"])
        service.controller.get_property.return_value = 1
        assert service._is_end_sentinel_position() is False

    def test_trailing_system_item_is_the_end(self):
        service = self._service_with_playlist(["command", "movie", "system"])
        service.controller.get_property.return_value = 3
        assert service._is_end_sentinel_position() is True

    def test_pre_show_position_is_not_the_end(self):
        service = self._service_with_playlist(["movie", "system"])
        service.controller.get_property.return_value = 0
        assert service._is_end_sentinel_position() is False

    def test_command_start_keeps_programme_running(self):
        service = self._service_with_playlist(["command", "movie", "system"])
        service.controller.get_property.return_value = 1
        service._handle_file_start("/media/system/black.mp4")
        assert service.programme_state == ProgrammeState.RUNNING
        assert service.current_programme is not None

    def test_programme_end_resets_to_streamed_ident_not_local_path(self):
        """Regression: at programme end the ident must be loaded by its stream URL, not its local file_path."""
        ident = Bumper.objects.create(title="Ident", file_path="/media/ident.mp4")
        Settings.set("cinema.default_ident_id", ident.id)

        service = self._service_with_playlist(["movie", "system"])
        service.controller.get_property.return_value = 2

        service._handle_file_start("http://host/stream/system/black/")

        service.controller.load_file.assert_called_once()
        loaded_url = service.controller.load_file.call_args.args[0]
        assert f"/stream/bumper/{ident.id}/" in loaded_url
        assert loaded_url != "/media/ident.mp4"
        assert service.controller.pause.called
        assert service.programme_state == ProgrammeState.COMPLETED

    def test_end_black_completes_programme(self):
        service = self._service_with_playlist(["movie", "system"])
        service.controller.get_property.return_value = 2
        service._handle_file_start("/media/system/black.mp4")
        assert service.programme_state == ProgrammeState.COMPLETED
        assert service.current_programme is None
