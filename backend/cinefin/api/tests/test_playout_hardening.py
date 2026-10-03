from unittest.mock import MagicMock

import pytest

from cinefin.api.mpv_service import MPVService, ProgrammeState, mpv_service

from .factories import PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def make_service(n_items):
    programme = ProgrammeFactory()
    playlist = PlaylistFactory(programme=programme)
    for order in range(n_items):
        PlaylistItemFactory(playlist=playlist, order=order, content_type="bumper", file=f"/tmp/item-{order}.mp4")
    service = MPVService()
    service.controller = MagicMock()
    service.controller.get_playlist.return_value = [{"filename": "standby"}]
    service._lazy_initialized = True
    service._on_standby = lambda: True
    return service, programme, playlist


@pytest.mark.parametrize("append_ok", [True, False])
def test_load_enqueues_every_item_or_aborts(append_ok):
    service, programme, playlist = make_service(3)
    service.controller.enqueue_file.return_value = append_ok
    assert service.load_programme(programme) is append_ok
    if append_ok:
        assert service.programme_state == ProgrammeState.LOADED and service.current_programme == programme
        assert service.controller.enqueue_file.call_count == playlist.items.count()
    else:
        assert service.programme_state == ProgrammeState.NOT_LOADED and service.current_programme is None


@pytest.mark.parametrize(
    ("state", "reason", "warned"),
    [
        (ProgrammeState.RUNNING, "error", True),
        (ProgrammeState.RUNNING, "eof", False),
        (ProgrammeState.LOADED, "error", False),
    ],
)
def test_a_stream_error_warns_against_the_item(caplog, state, reason, warned):
    service, programme, playlist = make_service(2)
    service.current_programme, service.current_playlist = programme, playlist
    service.playlist_offset, service.programme_state = 1, state
    service.controller.get_property.return_value = 1
    with caplog.at_level("WARNING"):
        service._handle_file_end({"reason": reason})
    errors = [r.message for r in caplog.records if "playback error" in r.message.lower()]
    assert bool(errors) is warned
    if warned:
        assert "/tmp/item-0.mp4" in errors[0] and service.current_programme is not None


def test_titles_never_show_the_stream_token():
    assert mpv_service.getFileName("http://h:8000/stream/movie/3/?t=98432fh043fnb09") == "3"
    assert mpv_service.getFileName("/media/movies/Alien (1979).mkv") == "Alien (1979).mkv"
    assert mpv_service.getFileName("") == ""
    assert mpv_service._preshow_title("http://h/stream/title/5/?t=abc") == "Title card"
    assert mpv_service._preshow_title("http://h/stream/system/black/?t=abc") == "Black"
    assert mpv_service._preshow_title("http://h/stream/bumper/9/?t=abc") == "Standby"
    assert mpv_service._preshow_title("/var/lib/cinefin-playout/idents/ab12.mp4") == "Standby"
