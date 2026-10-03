"""Cueing a programme with a title card: standby stays as entry 0 and the title card starts
at once, then pauses on its first frame, or (title_hold) after its fade-in."""

from unittest.mock import MagicMock

import pytest

from cinefin.api.mpv_service import MPVService, ProgrammeState
from cinefin.api.services import standby

from .factories import PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def _cued(tmp_path, monkeypatch, *, hold=True, fade_in=2.0, title=True):
    kwargs = {}
    if title:
        title_file = tmp_path / "title.mp4"
        title_file.write_bytes(b"x")
        kwargs = {"title_file": str(title_file), "title_hold": hold, "title_fade_in": fade_in}
    programme = ProgrammeFactory(**kwargs)
    PlaylistItemFactory(playlist=PlaylistFactory(programme=programme), order=0, content_type="bumper")
    service = MPVService()
    service.controller = MagicMock()
    # A local mpv already on standby (its path is the standby ident's URL).
    props = {"playlist_pos": 0, "duration": None, "path": standby.resolve_ident()[0]}
    service.controller.get_property.side_effect = props.get
    service.controller.get_playlist.side_effect = lambda: [{}] * (2 if title else 1)
    service._lazy_initialized = True
    monkeypatch.setattr(service, "_configure_tracks_for_file", lambda f: None)
    assert service.load_programme(programme) is True
    return service, props


def _file_starts(service, props, pos):
    props["playlist_pos"] = pos
    service._handle_file_start(f"http://host/file{pos}")


def test_without_hold_the_title_pauses_on_its_first_frame(tmp_path, monkeypatch):
    service, props = _cued(tmp_path, monkeypatch, hold=False)
    service.controller.pause.reset_mock()
    _file_starts(service, props, 0)
    service.controller.pause.assert_not_called()
    _file_starts(service, props, 1)
    service.controller.pause.assert_called_once()


def test_starting_the_programme_drops_the_hold(tmp_path, monkeypatch):
    service, props = _cued(tmp_path, monkeypatch)
    service.controller.pause.reset_mock()
    service.programme_state = ProgrammeState.RUNNING  # started before the title card began
    _file_starts(service, props, 1)
    service._handle_time_pos(2.5)
    service.controller.pause.assert_not_called()
