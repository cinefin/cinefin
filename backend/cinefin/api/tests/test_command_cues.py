from unittest.mock import MagicMock, call

import pytest

from cinefin.api.models import PlaylistCue, PlayoutSession
from cinefin.api.mpv_service import MPVService, ProgrammeState
from cinefin.api.services import command_runner

from .factories import CommandFactory, PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db


def make_service():
    service = MPVService()
    service.controller = MagicMock()
    service._lazy_initialized = True
    return service


def running_service(item_types, offset=1):
    programme = ProgrammeFactory()
    playlist = PlaylistFactory(programme=programme)
    for order, content_type in enumerate(item_types):
        PlaylistItemFactory(playlist=playlist, order=order, content_type=content_type)
    service = make_service()
    service.current_programme = programme
    service.current_playlist = playlist
    service.playlist_offset = offset
    service.programme_state = ProgrammeState.RUNNING
    return service, playlist


class TestIdentStreams:
    def test_reset_loads_the_ident_stream_url(self):
        from cinefin.api.models import Bumper, Settings

        ident = Bumper.objects.create(title="Ident", file_path="/media/ident.mp4")
        Settings.set("cinema.default_ident_id", ident.id)
        service = make_service()

        assert service.reset() is True
        (loaded,), kwargs = service.controller.load_file.call_args
        assert loaded == ident.get_stream_url()["stream_url"]
        assert "/stream/bumper/" in loaded and loaded.startswith("http")
        assert kwargs.get("replace") is True

    def test_reset_falls_back_to_the_bundled_system_ident(self):
        from cinefin.api.models import Settings

        Settings.set("cinema.default_ident_id", None)
        service = make_service()

        assert service.reset() is True
        (loaded,), kwargs = service.controller.load_file.call_args
        assert "/stream/system/ident/?t=" in loaded and loaded.startswith("http")
        assert kwargs.get("replace") is True
        service.controller.playlist_clear.assert_not_called()

    def test_a_deleted_ident_bumper_falls_back_to_the_system_ident(self):
        from cinefin.api.models import Settings

        Settings.set("cinema.default_ident_id", 999999)
        service = make_service()

        assert service.reset() is True
        (loaded,), _ = service.controller.load_file.call_args
        assert "/stream/system/ident/?t=" in loaded

    def test_load_programme_streams_the_title(self, tmp_path):
        title = tmp_path / "title.mp4"
        title.write_bytes(b"x")
        programme = ProgrammeFactory(title_file=str(title))
        PlaylistItemFactory(playlist=PlaylistFactory(programme=programme), order=0, content_type="bumper")
        service = make_service()

        assert service.load_programme(programme) is True
        loaded = service.controller.load_file.call_args_list[0][0][0]
        assert loaded == programme.get_title_stream_url()
        assert f"/stream/title/{programme.id}/" in loaded


class TestCueFiring:
    def _capture_sequential(self, monkeypatch):
        fired = []
        monkeypatch.setattr(
            command_runner, "execute_many_sequential", lambda commands, trigger: fired.append((list(commands), trigger))
        )
        return fired

    def test_cue_fires_when_its_item_starts(self, monkeypatch):
        fired = self._capture_sequential(monkeypatch)
        service, playlist = running_service(["bumper", "movie", "system"])
        command = CommandFactory(name="Dim lights")
        PlaylistCue.objects.create(playlist=playlist, command=command, command_name=command.name, fires_before_order=1)

        service._handle_playlist_change(1)
        assert fired == []

        service._handle_playlist_change(2)
        assert len(fired) == 1
        commands, trigger = fired[0]
        assert commands == [command]
        assert trigger == "block"

    def test_forward_jump_fires_every_passed_cue_in_order(self, monkeypatch):
        fired = self._capture_sequential(monkeypatch)
        service, playlist = running_service(["bumper", "movie", "bumper", "system"])
        first = CommandFactory(name="First")
        second = CommandFactory(name="Second")
        PlaylistCue.objects.create(playlist=playlist, command=first, command_name=first.name, fires_before_order=1)
        PlaylistCue.objects.create(playlist=playlist, command=second, command_name=second.name, fires_before_order=2)

        service._handle_playlist_change(1)
        service._handle_playlist_change(3)

        assert len(fired) == 1
        assert fired[0][0] == [first, second]

    def test_backward_jump_fires_nothing_then_refires_on_replay(self, monkeypatch):
        fired = self._capture_sequential(monkeypatch)
        service, playlist = running_service(["bumper", "movie", "system"])
        command = CommandFactory(name="Dim lights")
        PlaylistCue.objects.create(playlist=playlist, command=command, command_name=command.name, fires_before_order=1)

        service._handle_playlist_change(2)
        service._handle_playlist_change(1)
        assert len(fired) == 1

        service._handle_playlist_change(2)
        assert len(fired) == 2

    def test_cue_for_deleted_command_is_skipped(self, monkeypatch):
        fired = self._capture_sequential(monkeypatch)
        service, playlist = running_service(["bumper", "system"])
        PlaylistCue.objects.create(playlist=playlist, command=None, command_name="Gone", fires_before_order=0)

        service._handle_playlist_change(1)
        assert fired == []

    def test_cursor_survives_in_session(self, monkeypatch):
        self._capture_sequential(monkeypatch)
        service, _ = running_service(["bumper", "movie", "system"])
        service._handle_playlist_change(2)

        assert PlayoutSession.load().programme_cursor == 1


class TestHoldItems:
    def test_hold_item_fires_loops_and_advances(self, monkeypatch):
        executed = []
        monkeypatch.setattr(
            command_runner, "execute", lambda command, trigger, **kw: executed.append((command, trigger))
        )

        service, playlist = running_service(["command", "system"])
        command = CommandFactory(name="Close curtains", duration=0.5)
        item = playlist.items.get(order=0)
        item.command = command
        item.save()

        service.controller.get_property.side_effect = lambda name: {"playlist_pos": 1, "pause": False}[name]
        service.controller.set_property.return_value = True

        service._run_hold_item(item, 1)

        assert executed == [(command, "block")]
        assert call("loop-file", "inf") in service.controller.set_property.call_args_list
        assert call("loop-file", "no") in service.controller.set_property.call_args_list
        service.controller.next.assert_called_once()

    def test_hold_aborts_without_advancing_when_operator_skips(self, monkeypatch):
        monkeypatch.setattr(command_runner, "execute", lambda *a, **kw: None)

        service, playlist = running_service(["command", "system"])
        command = CommandFactory(name="Close curtains", duration=5)
        item = playlist.items.get(order=0)
        item.command = command
        item.save()

        service.controller.get_property.side_effect = lambda name: {"playlist_pos": 2, "pause": False}[name]
        service.controller.set_property.return_value = True

        service._run_hold_item(item, 1)

        service.controller.next.assert_not_called()
        assert call("loop-file", "no") in service.controller.set_property.call_args_list

    def test_hold_outlasts_command_slower_than_duration(self, monkeypatch):
        import time as time_module

        executed = []

        def slow_execute(command, trigger, **kw):
            time_module.sleep(1.0)
            executed.append("finished")

        monkeypatch.setattr(command_runner, "execute", slow_execute)

        service, playlist = running_service(["command", "system"])
        command = CommandFactory(name="Slow scene", duration=0.25)
        item = playlist.items.get(order=0)
        item.command = command
        item.save()

        service.controller.get_property.side_effect = lambda name: {"playlist_pos": 1, "pause": False}[name]
        service.controller.set_property.return_value = True

        service._run_hold_item(item, 1)

        assert executed == ["finished"]
        service.controller.next.assert_called_once()

    def test_zero_duration_holds_until_command_completes(self, monkeypatch):
        import time as time_module

        executed = []

        def slow_execute(command, trigger, **kw):
            time_module.sleep(0.5)
            executed.append("finished")

        monkeypatch.setattr(command_runner, "execute", slow_execute)

        service, playlist = running_service(["command", "system"])
        command = CommandFactory(name="Instant-ish", duration=0)
        item = playlist.items.get(order=0)
        item.command = command
        item.save()

        service.controller.get_property.side_effect = lambda name: {"playlist_pos": 1, "pause": False}[name]
        service.controller.set_property.return_value = True

        service._run_hold_item(item, 1)

        assert executed == ["finished"]
        assert call("loop-file", "inf") in service.controller.set_property.call_args_list
        assert call("loop-file", "no") in service.controller.set_property.call_args_list
        service.controller.next.assert_called_once()

    def test_deleted_command_without_duration_plays_black_once(self, monkeypatch):
        service, playlist = running_service(["command", "system"])
        item = playlist.items.get(order=0)
        item.command = None
        item.save()

        service._run_hold_item(item, 1)

        service.controller.set_property.assert_not_called()
        service.controller.next.assert_not_called()


class TestPreshowOnStart:
    def test_start_programme_fires_configured_preshow_list(self, monkeypatch):
        from cinefin.api.models import Settings

        fired = []
        monkeypatch.setattr(
            command_runner, "execute_many_sequential", lambda commands, trigger: fired.append((list(commands), trigger))
        )

        first = CommandFactory(name="Lights")
        second = CommandFactory(name="Curtains")
        Settings.set("scheduler.preshow_commands", [first.id, 9999, second.id])

        service, _ = running_service(["bumper", "system"])
        service.controller.get_property.return_value = 0
        service.controller.get_playlist.return_value = [{"filename": "a"}]
        service.controller.play.return_value = True

        assert service.start_programme(preshow=True) is True

        assert len(fired) == 1
        commands, trigger = fired[0]
        assert commands == [first, second]
        assert trigger == "preshow"

    def test_manual_start_skips_preshow(self, monkeypatch):
        from cinefin.api.models import Settings

        fired = []
        monkeypatch.setattr(
            command_runner, "execute_many_sequential", lambda commands, trigger: fired.append((list(commands), trigger))
        )
        Settings.set("scheduler.preshow_commands", [CommandFactory(name="Lights").id])

        service, _ = running_service(["bumper", "system"])
        service.controller.get_property.return_value = 0
        service.controller.get_playlist.return_value = [{"filename": "a"}]
        service.controller.play.return_value = True

        assert service.start_programme() is True
        assert fired == []


class TestHoldClockInStatus:
    def test_status_reports_hold_progress_not_black_clip(self):
        service, _ = running_service(["bumper", "system"])
        service.controller.get_status.return_value = {"time": 2.0, "length": 5.0, "playlist_pos": 1}
        service._hold_progress = {"duration": 40.0, "elapsed": 12.5}
        playback = service.get_enhanced_status()["playback"]
        assert playback["duration"] == 40.0
        assert playback["position"] == 12.5
        assert playback["remaining"] == 27.5


class TestHoldAdvanceGuard:
    def test_stale_hold_does_not_advance_past_successor(self):
        """Regression: a stale hold thread's final next() must not fire and cut the next hold short."""
        from unittest.mock import MagicMock

        service, _ = running_service(["bumper", "system"])
        command = CommandFactory(name="Guarded", duration=1)
        item = MagicMock()
        item.command = command
        item.id = 1

        calls = {"n": 0}

        def get_property(name):
            if name == "pause":
                return False
            if name == "playlist_pos":
                calls["n"] += 1
                return 1 if calls["n"] <= 3 else 2
            return None

        service.controller.get_property.side_effect = get_property
        service.controller.set_property.return_value = True

        service._run_hold_item(item, 1)
        service.controller.next.assert_not_called()
