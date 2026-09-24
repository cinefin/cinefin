from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cinefin.api.mpv_controller import MPVController


class TestNumCoercion:
    def test_none_string_becomes_none(self):
        assert MPVController._num("none") is None

    def test_none_passthrough(self):
        assert MPVController._num(None) is None

    def test_numeric_string_parses(self):
        assert MPVController._num("3.5") == 3.5

    def test_numbers_pass_through(self):
        assert MPVController._num(42) == 42.0
        assert MPVController._num(1.25) == 1.25

    def test_bool_is_not_a_number(self):
        assert MPVController._num(True) is None


class TestSingleSelfHealingConnection:
    """One WSMPV per controller: never spin up a second connection (dup observers = skipped-items bug)."""

    def _connected_controller(self):
        c = MPVController()
        c.player = MagicMock()
        c._connected = True
        return c

    def test_transient_command_error_does_not_reconnect(self):
        c = self._connected_controller()
        player = c.player
        player.command.side_effect = Exception("boom")
        with patch("cinefin.api.mpv_controller.WSMPV") as ws_cls:
            assert c._mpv_command("set_property", "pause", True) is False
        assert c._connected is True
        assert c.player is player
        ws_cls.assert_not_called()

    def test_ensure_connected_reuses_existing_player(self):
        c = self._connected_controller()
        with patch("cinefin.api.mpv_controller.WSMPV") as ws_cls:
            assert c._ensure_connected() is True
        ws_cls.assert_not_called()

    def test_on_quit_keeps_connection_for_self_heal(self):
        c = self._connected_controller()
        c._on_quit()
        assert c._connected is True


def _fake_player_with_none_strings():
    return SimpleNamespace(
        pause=False,
        time_pos="none",
        playback_time=None,
        duration="none",
        length="none",
        stream_open_filename="http://example/stream/bumper/1",
        path=None,
        filename=None,
        volume="none",
        video_params=None,
        audio_params=None,
        playlist_pos=3,
        mute=False,
        speed="none",
        fullscreen=False,
        container_fps="none",
        estimated_vf_fps=None,
        video_codec=None,
        video_bitrate="none",
        audio_codec=None,
        audio_bitrate="none",
        width="none",
        height="none",
        hwdec_current="no",
    )


def test_get_status_coerces_mpv_none_strings(monkeypatch):
    controller = MPVController.__new__(MPVController)
    controller.player = _fake_player_with_none_strings()
    monkeypatch.setattr(MPVController, "_ensure_connected", lambda self: True)

    status = controller.get_status()

    assert status["time"] is None
    assert status["length"] is None
    assert status["volume"] is None
    assert status["speed"] == 1.0
    assert status["video"]["width"] is None
    assert status["video"]["fps"] is None
    assert status["video"]["bitrate"] is None
    assert status["audio"]["bitrate"] is None
    numeric_slots = [status["time"], status["length"], status["volume"], status["speed"]]
    assert all(not isinstance(v, str) for v in numeric_slots)


class FakeJsonIpcPlayer:
    """Mimics python-mpv-jsonipc: only underscore-form names in `properties` reach IPC; others become plain attrs."""

    def __init__(self):
        object.__setattr__(self, "properties", {"loop_file", "playlist_pos"})
        object.__setattr__(self, "ipc", {})

    def __setattr__(self, name, value):
        if name in self.properties:
            self.ipc[name] = value
        else:
            object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name in self.properties:
            return self.ipc.get(name)
        raise AttributeError(name)


class TestPropertyNameNormalisation:
    def _controller(self):
        controller = MPVController.__new__(MPVController)
        controller.player = FakeJsonIpcPlayer()
        return controller

    def test_dashed_set_reaches_the_player(self):
        controller = self._controller()
        assert controller.set_property("loop-file", "inf") is True
        assert controller.player.ipc == {"loop_file": "inf"}
        assert "loop-file" not in vars(controller.player)

    def test_dashed_get_reads_the_player_property(self):
        controller = self._controller()
        controller.player.ipc["loop_file"] = "inf"
        assert controller.get_property("loop-file") == "inf"

    def test_underscore_names_still_work(self):
        controller = self._controller()
        controller.set_property("playlist_pos", 3)
        assert controller.get_property("playlist_pos") == 3


class TestUnreachableLoggingIsQuiet:
    """A disconnected episode must log at most one WARNING, never ERROR per attempt (issue #133)."""

    def _reset(self):
        import cinefin.api.mpv_ws as ws

        ws._reachable_state.clear()

    def test_unreachable_logs_one_warning_then_recovers_once(self, caplog):
        import logging

        import cinefin.api.mpv_ws as ws

        self._reset()
        url = "ws://127.0.0.1:9/ws/control"
        with caplog.at_level(logging.DEBUG, logger="cinefin.api.mpv_ws"):
            for _ in range(20):
                ws._note_unreachable(url, "connection refused")
            ws._note_reachable(url)
            ws._note_reachable(url)
        recs = [r for r in caplog.records if r.name == "cinefin.api.mpv_ws"]
        assert [r for r in recs if r.levelno >= logging.ERROR] == []
        assert len([r for r in recs if r.levelno == logging.WARNING]) == 1
        assert len([r for r in recs if r.levelno == logging.INFO and "reachable again" in r.message]) == 1
