import time
from unittest.mock import MagicMock, call

import pytest

from cinefin.api.models import PlaylistCue, PlayoutSession
from cinefin.api.mpv_service import MPVService, ProgrammeState
from cinefin.api.services import command_runner

from .factories import CommandFactory, PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def running_service(item_types, offset=1):
    programme = ProgrammeFactory()
    playlist = PlaylistFactory(programme=programme)
    for order, content_type in enumerate(item_types):
        PlaylistItemFactory(playlist=playlist, order=order, content_type=content_type)
    service = MPVService()
    service.controller = MagicMock()
    service._lazy_initialized = True
    service.current_programme, service.current_playlist = programme, playlist
    service.playlist_offset, service.programme_state = offset, ProgrammeState.RUNNING
    return service, playlist


def test_cues_refire_on_replay_skip_deleted_commands_and_persist_the_cursor(monkeypatch):
    # Forward and backward jumps run end to end in test_playout_simulation.
    fired = []
    monkeypatch.setattr(
        command_runner, "execute_many_sequential", lambda commands, trigger: fired.append(list(commands))
    )
    service, playlist = running_service(["bumper", "movie", "system"])
    command = CommandFactory(name="Dim lights")
    PlaylistCue.objects.create(playlist=playlist, command=command, command_name=command.name, fires_before_order=1)
    PlaylistCue.objects.create(playlist=playlist, command=None, command_name="Gone", fires_before_order=0)

    service._handle_playlist_change(1)
    assert fired == []  # the deleted command's cue is skipped
    service._handle_playlist_change(2)
    service._handle_playlist_change(1)
    service._handle_playlist_change(2)
    assert fired == [[command], [command]]
    assert PlayoutSession.load().programme_cursor == 1


def _hold(monkeypatch, duration, run_for=0.0, playlist_pos=1, command=True):
    executed = []

    def execute(cmd, trigger, **kw):
        time.sleep(run_for)
        executed.append((cmd.name, trigger))

    monkeypatch.setattr(command_runner, "execute", execute)
    service, playlist = running_service(["command", "system"])
    item = playlist.items.get(order=0)
    item.command = CommandFactory(name="Curtains", duration=duration) if command else None
    item.save()
    c = service.controller
    c.get_property.side_effect = lambda name, quiet=False: {"playlist_pos": playlist_pos, "pause": False}[name]
    c.set_property.return_value = True
    service._run_hold_item(item, 1)
    return c, executed


@pytest.mark.parametrize(
    ("duration", "run_for"),
    [(0.5, 0.0), (0.25, 1.0), (0, 0.5)],
    ids=["waits-out-its-duration", "outlasts-a-slow-command", "zero-duration-waits-for-the-command"],
)
def test_a_hold_item_fires_loops_and_advances(monkeypatch, duration, run_for):
    c, executed = _hold(monkeypatch, duration, run_for)
    assert executed == [("Curtains", "block")]
    assert call("loop-file", "inf") in c.set_property.call_args_list
    assert call("loop-file", "no") in c.set_property.call_args_list
    c.next.assert_called_once()


def test_a_hold_the_operator_skipped_does_not_advance(monkeypatch):
    c, _ = _hold(monkeypatch, 5, playlist_pos=2)
    c.next.assert_not_called()
    assert call("loop-file", "no") in c.set_property.call_args_list


def test_a_stale_hold_does_not_advance_past_its_successor():
    service, _ = running_service(["bumper", "system"])
    item = MagicMock(command=CommandFactory(duration=1), id=1)
    reads = {"n": 0}

    def get_property(name, quiet=False):
        if name == "playlist_pos":
            reads["n"] += 1
            return 1 if reads["n"] <= 3 else 2
        return False if name == "pause" else None

    service.controller.get_property.side_effect = get_property
    service.controller.set_property.return_value = True
    service._run_hold_item(item, 1)
    service.controller.next.assert_not_called()
