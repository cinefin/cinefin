"""title_hold: a cued title card plays its fade-in, then holds until the programme starts."""

from unittest.mock import MagicMock

import pytest

from cinefin.api.mpv_service import MPVService, ProgrammeState

from .factories import PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def _cued(tmp_path, *, hold=True, fade_in=2.0):
    title = tmp_path / "title.mp4"
    title.write_bytes(b"x")
    programme = ProgrammeFactory(title_file=str(title), title_hold=hold, title_fade_in=fade_in)
    PlaylistItemFactory(playlist=PlaylistFactory(programme=programme), order=0, content_type="bumper")
    service = MPVService()
    service.controller = MagicMock()
    service.controller.get_property.return_value = 0  # playlist_pos: the title card
    service._lazy_initialized = True
    assert service.load_programme(programme) is True
    return service


def test_fades_in_then_holds(tmp_path):
    service = _cued(tmp_path)
    service.controller.play.assert_called_once()
    service.controller.pause.assert_not_called()

    service._handle_time_pos(1.0)  # mid-fade: keep playing
    service.controller.pause.assert_not_called()
    service._handle_time_pos(2.05)  # fade done: hold
    service.controller.pause.assert_called_once()
    service._handle_time_pos(2.3)  # held once only
    service.controller.pause.assert_called_once()


def test_never_plays_past_the_title(tmp_path):
    service = _cued(tmp_path, fade_in=9.0)
    service._live["duration"] = 5.0
    service._handle_time_pos(4.6)
    service.controller.pause.assert_called_once()


def test_starting_the_programme_drops_the_hold(tmp_path):
    service = _cued(tmp_path)
    service.programme_state = ProgrammeState.RUNNING
    service._handle_time_pos(2.5)
    service.controller.pause.assert_not_called()
    assert service._title_hold_at is None


@pytest.mark.parametrize("hold, fade_in", [(False, 2.0), (True, 0.0)])
def test_otherwise_pauses_on_the_first_frame(tmp_path, hold, fade_in):
    service = _cued(tmp_path, hold=hold, fade_in=fade_in)
    service.controller.pause.assert_called_once()
    service.controller.play.assert_not_called()
    assert service._title_hold_at is None
