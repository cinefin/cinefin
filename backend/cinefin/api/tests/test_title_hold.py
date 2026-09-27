"""Cueing a programme with a title card: the ident plays through, then the title card pauses —
on its first frame, or (title_hold) after its fade-in."""

from unittest.mock import MagicMock

import pytest

from cinefin.api.mpv_service import MPVService, ProgrammeState

from .factories import PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def _cued(tmp_path, monkeypatch, *, hold=True, fade_in=2.0, ident=True):
    title = tmp_path / "title.mp4"
    title.write_bytes(b"x")
    programme = ProgrammeFactory(title_file=str(title), title_hold=hold, title_fade_in=fade_in)
    PlaylistItemFactory(playlist=PlaylistFactory(programme=programme), order=0, content_type="bumper")
    service = MPVService()
    service.controller = MagicMock()
    props = {"playlist_pos": 0, "duration": None}
    service.controller.get_property.side_effect = props.get
    service.controller.get_playlist.side_effect = lambda: [{}] * (2 if ident else 1)
    service._lazy_initialized = True
    monkeypatch.setattr(service, "_configure_tracks_for_file", lambda f: None)
    if not ident:
        monkeypatch.setattr(service, "_resolve_ident_stream", lambda: (None, None))
    assert service.load_programme(programme) is True
    return service, props


def _file_starts(service, props, pos):
    props["playlist_pos"] = pos
    service._handle_file_start(f"http://host/file{pos}")


def test_ident_plays_then_the_title_card(tmp_path, monkeypatch):
    service, props = _cued(tmp_path, monkeypatch)
    first, second = (
        service.controller.load_file.call_args[0][0],
        service.controller.enqueue_file.call_args_list[0][0][0],
    )
    assert "/stream/system/ident/" in first or "/stream/bumper/" in first
    assert "/stream/title/" in second
    assert service.playlist_offset == 2
    service.controller.play.assert_called()
    service.controller.pause.assert_not_called()


def test_hold_fades_in_after_the_ident(tmp_path, monkeypatch):
    service, props = _cued(tmp_path, monkeypatch)
    _file_starts(service, props, 0)  # the ident
    service._handle_time_pos(5.0)  # its clock must not trip the hold
    service.controller.pause.assert_not_called()

    _file_starts(service, props, 1)  # the title card
    service._handle_time_pos(1.0)  # mid-fade
    service.controller.pause.assert_not_called()
    service._handle_time_pos(2.05)  # faded in: hold
    service.controller.pause.assert_called_once()


def test_without_hold_the_title_pauses_on_its_first_frame(tmp_path, monkeypatch):
    service, props = _cued(tmp_path, monkeypatch, hold=False)
    _file_starts(service, props, 0)
    service.controller.pause.assert_not_called()
    _file_starts(service, props, 1)
    service.controller.pause.assert_called_once()


def test_never_plays_past_the_title(tmp_path, monkeypatch):
    service, props = _cued(tmp_path, monkeypatch, fade_in=9.0)
    _file_starts(service, props, 1)
    service._live["duration"] = 5.0
    service._handle_time_pos(4.6)
    service.controller.pause.assert_called_once()


def test_starting_the_programme_drops_the_hold(tmp_path, monkeypatch):
    service, props = _cued(tmp_path, monkeypatch)
    service.programme_state = ProgrammeState.RUNNING  # started while the ident plays
    _file_starts(service, props, 1)
    service._handle_time_pos(2.5)
    service.controller.pause.assert_not_called()


def test_without_an_ident_the_title_is_first(tmp_path, monkeypatch):
    service, props = _cued(tmp_path, monkeypatch, hold=False, ident=False)
    service.controller.enqueue_file.assert_called_once()  # only the programme item, no title enqueue
    service.controller.pause.assert_called_once()  # paused on the first frame, as before
    assert service.playlist_offset == 1
