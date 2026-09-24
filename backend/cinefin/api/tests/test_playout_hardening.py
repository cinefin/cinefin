from unittest.mock import MagicMock

import pytest

from cinefin.api.models import Settings
from cinefin.api.mpv_service import MPVService, ProgrammeState

from .factories import PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def make_service():
    service = MPVService()
    service.controller = MagicMock()
    service.controller.get_playlist.return_value = [{"filename": "ident"}]
    service._lazy_initialized = True
    return service


def _programme_with_items(n):
    programme = ProgrammeFactory()
    playlist = PlaylistFactory(programme=programme)
    for order in range(n):
        PlaylistItemFactory(playlist=playlist, order=order, content_type="bumper", file=f"/tmp/item-{order}.mp4")
    return programme, playlist


class TestLoadGuards:
    def test_load_refuses_empty_playlist(self):
        programme, _ = _programme_with_items(0)
        service = make_service()

        assert service.load_programme(programme) is False
        assert service.programme_state == ProgrammeState.NOT_LOADED
        assert service.current_programme is None

    def test_load_aborts_when_an_append_fails(self):
        programme, _ = _programme_with_items(3)
        service = make_service()
        service.controller.enqueue_file.return_value = False

        assert service.load_programme(programme) is False
        assert service.programme_state == ProgrammeState.NOT_LOADED
        assert service.current_programme is None

    def test_load_enqueues_every_item_on_success(self):
        programme, playlist = _programme_with_items(3)
        service = make_service()
        service.controller.enqueue_file.return_value = True

        assert service.load_programme(programme) is True
        assert service.programme_state == ProgrammeState.LOADED
        assert service.current_programme == programme
        assert service.controller.enqueue_file.call_count == playlist.items.count()


class TestStreamErrorHandling:
    def _running_service(self):
        programme, playlist = _programme_with_items(2)
        service = make_service()
        service.current_programme = programme
        service.current_playlist = playlist
        service.playlist_offset = 1
        service.programme_state = ProgrammeState.RUNNING
        service._handle_playlist_item_end = MagicMock()
        return service

    def test_error_reason_advances_and_warns(self, caplog):
        service = self._running_service()
        service.controller.get_property.return_value = 1

        with caplog.at_level("WARNING"):
            service._handle_file_end({"reason": "error"})

        service._handle_playlist_item_end.assert_called_once()
        assert service.current_programme is not None
        assert any("playback error" in r.message.lower() for r in caplog.records)

    def test_eof_still_advances(self):
        service = self._running_service()
        service.controller.get_property.return_value = 1
        service._handle_file_end({"reason": "eof"})
        service._handle_playlist_item_end.assert_called_once()

    def test_ignores_events_when_not_running(self):
        service = self._running_service()
        service.programme_state = ProgrammeState.LOADED
        service._handle_file_end({"reason": "error"})
        service._handle_playlist_item_end.assert_not_called()


class TestPreshowCommandFailure:
    def test_failing_preshow_command_never_raises(self, monkeypatch):
        from cinefin.api.services import command_runner

        Settings.set("scheduler.preshow_commands", [999])

        def boom(*a, **kw):
            raise RuntimeError("projector offline")

        monkeypatch.setattr(command_runner, "execute_many_sequential", boom)

        service = make_service()
        service._run_preshow_commands()


class TestPlayoutLock:
    def test_playout_lock_is_reentrant(self):
        service = make_service()
        with service._playout_lock:
            assert service._playout_lock.acquire(blocking=False)
            service._playout_lock.release()


class TestPlaylistItemTitles:
    """Stream URLs must never surface their ?t= token as a display title."""

    def test_getfilename_strips_token_and_slash(self):
        from cinefin.api.mpv_service import mpv_service

        assert mpv_service.getFileName("http://h:8000/stream/movie/3/?t=98432fh043fnb09") == "3"
        assert mpv_service.getFileName("/media/movies/Alien (1979).mkv") == "Alien (1979).mkv"
        assert mpv_service.getFileName("") == ""

    def test_preshow_labels(self):
        from cinefin.api.mpv_service import mpv_service

        assert mpv_service._preshow_title("http://h/stream/title/5/?t=abc") == "Title card"
        assert mpv_service._preshow_title("http://h/stream/system/black/?t=abc") == "Black"
        assert mpv_service._preshow_title("http://h/stream/bumper/9/?t=abc") == "System Ident"
        assert mpv_service._preshow_title("http://h/stream/system/ident/?t=abc") == "System Ident"
