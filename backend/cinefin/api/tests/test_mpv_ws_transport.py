"""Contract tests for the WS control transport."""

import time

import pytest

from cinefin.api.mpv_controller import MPVController
from cinefin.api.mpv_ws import WSMPV, build_ws_control_url

from .ws_stub_agent import StubAgent


@pytest.fixture
def stub():
    with StubAgent() as agent:
        yield agent


@pytest.fixture
def ws_settings(db, stub):
    from cinefin.api.models import PlayoutHost

    PlayoutHost.objects.all().delete()
    PlayoutHost.objects.create(
        name="Stub", base_url=f"http://127.0.0.1:{stub.port}", token="sekret-token", is_active=True
    )
    yield stub


def _ws_controller(stub, token="sekret-token"):
    return WSMPV(stub.url, token=token)


class TestBuildWsControlUrl:
    def test_http_becomes_ws(self):
        assert build_ws_control_url("http://127.0.0.1:8089") == "ws://127.0.0.1:8089/ws/control"

    def test_https_becomes_wss(self):
        assert build_ws_control_url("https://booth:8089") == "wss://booth:8089/ws/control"

    def test_trailing_slash_trimmed(self):
        assert build_ws_control_url("http://h:1/") == "ws://h:1/ws/control"

    def test_bare_host_defaults_to_ws(self):
        assert build_ws_control_url("127.0.0.1:8089") == "ws://127.0.0.1:8089/ws/control"


class TestWSMPVSurface:
    def test_command_round_trips(self, stub):
        player = _ws_controller(stub)
        try:
            assert player.command("loadfile", "/tmp/x.mp4", "replace") == [
                "loadfile",
                "/tmp/x.mp4",
                "replace",
            ]
        finally:
            player.terminate()

    def test_get_property_via_command(self, stub):
        stub.property_values["time-pos"] = 12.5
        player = _ws_controller(stub)
        try:
            assert player.command("get_property", "time-pos") == 12.5
        finally:
            player.terminate()

    def test_property_attribute_get(self, stub):
        stub.property_values["pause"] = True
        player = _ws_controller(stub)
        try:
            assert player.pause is True
        finally:
            player.terminate()

    def test_property_attribute_set(self, stub):
        player = _ws_controller(stub)
        try:
            player.pause = False
            assert ["set_property", "pause", False] in stub.received_commands
        finally:
            player.terminate()

    def test_dashed_property_name_normalised(self, stub):
        player = _ws_controller(stub)
        try:
            player.command("set_property", "sub-visibility", True)
            player.loop_file = "inf"
            assert ["set_property", "loop-file", "inf"] in stub.received_commands
        finally:
            player.terminate()

    def test_error_reply_raises(self, stub):
        from cinefin.api.mpv_ws import MPVError

        orig = stub._on_command

        def failing(conn, frame):
            if frame.get("command", [None])[0] == "bad":
                import json as _json

                from .ws_stub_agent import _send_frame

                _send_frame(conn, _json.dumps({"request_id": frame["request_id"], "error": "boom"}))
                return
            orig(conn, frame)

        stub._on_command = failing
        player = _ws_controller(stub)
        try:
            with pytest.raises(MPVError):
                player.command("bad")
        finally:
            player.terminate()

    def test_property_unavailable_returns_none(self, stub):
        orig = stub._on_command

        def unavail(conn, frame):
            if frame.get("command", [None])[0] == "get_property":
                import json as _json

                from .ws_stub_agent import _send_frame

                _send_frame(
                    conn,
                    _json.dumps({"request_id": frame["request_id"], "error": "property unavailable"}),
                )
                return
            orig(conn, frame)

        stub._on_command = unavail
        player = _ws_controller(stub)
        try:
            assert player.command("get_property", "duration") is None
        finally:
            player.terminate()

    def test_read_timeout_drops_connection(self, stub):
        """A never-arriving reply must fail fast and tear the link down."""
        orig = stub._on_command

        def swallow(conn, frame):
            if frame.get("command", [None])[0] == "get_property":
                stub.received_commands.append(frame.get("command"))
                return
            orig(conn, frame)

        stub._on_command = swallow
        player = _ws_controller(stub)
        try:
            with pytest.raises(TimeoutError):
                player.command("get_property", "pause", timeout=0.3)
            _wait(lambda: player._ws is None, timeout=2.0)
            assert player._ws is None
        finally:
            player.terminate()

    def test_bind_property_observer_fires(self, stub):
        stub.property_values["time-pos"] = 3.0
        player = _ws_controller(stub)
        received = []
        try:
            player.bind_property_observer("time-pos", lambda name, data: received.append((name, data)))
            _wait(lambda: received)
            assert received == [("time-pos", 3.0)]
        finally:
            player.terminate()

    def test_bind_property_observer_unobserves_first(self, stub):
        """The agent's mpv outlives Cinefin and ids restart at 1 each session, so
        a dead session leaves a twin observer under the same id. Subscribing must
        unobserve that id before observing, or every change dispatches N times."""
        player = _ws_controller(stub)
        try:
            oid = player.bind_property_observer("time-pos", lambda name, data: None)
            _wait(lambda: ["observe_property", oid, "time-pos"] in stub.received_commands)
            assert ["unobserve_property", oid] in stub.received_commands
            # Unobserve must come BEFORE the observe for the same id.
            assert stub.received_commands.index(["unobserve_property", oid]) < stub.received_commands.index(
                ["observe_property", oid, "time-pos"]
            )
        finally:
            player.terminate()

    def test_callback_may_issue_command_without_deadlock(self, stub):
        """A callback that issues a reentrant command must not deadlock the reader."""
        stub.property_values["time-pos"] = 1.0
        stub.property_values["playlist-count"] = 3
        player = _ws_controller(stub)
        inner = []
        try:

            def on_change(name, data):
                inner.append(player.command("get_property", "playlist-count"))

            player.bind_property_observer("time-pos", on_change)
            _wait(lambda: inner, timeout=5.0)
            assert inner == [3]
        finally:
            player.terminate()

    def test_bind_event_fires(self, stub):
        player = _ws_controller(stub)
        got = []
        try:
            player.bind_event("end-file", lambda data: got.append(data))
            stub.wait_for_client()
            stub.push_event({"event": "end-file", "reason": "eof"})
            _wait(lambda: got)
            assert got[0]["reason"] == "eof"
        finally:
            player.terminate()

    def test_auth_header_sent(self, stub):
        player = _ws_controller(stub, token="my-token")
        try:
            stub.wait_for_client()
            assert stub.auth_header == "Bearer my-token"
        finally:
            player.terminate()

    def test_no_auth_header_when_no_token(self, stub):
        player = _ws_controller(stub, token=None)
        try:
            stub.wait_for_client()
            assert stub.auth_header is None
        finally:
            player.terminate()

    def test_terminate_closes_without_stopping_agent(self, stub):
        player = _ws_controller(stub)
        stub.wait_for_client()
        player.terminate()
        player2 = _ws_controller(stub)
        try:
            assert player2.command("get_property", "pause") is None
        finally:
            player2.terminate()

    def test_reconnect_resubscribes_observers(self, stub):
        stub.property_values["pause"] = False
        player = _ws_controller(stub)
        events = []
        try:
            player.bind_property_observer("pause", lambda name, data: events.append((name, data)))
            _wait(lambda: len(events) >= 1)
            first = stub.connection_count

            stub.drop_client()
            _wait(lambda: stub.connection_count > first, timeout=8.0)
            stub.wait_for_client()

            _wait(lambda: len(events) >= 2, timeout=8.0)
            assert len(events) >= 2
            observes = [c for c in stub.received_commands if c[:1] == ["observe_property"] and c[2] == "pause"]
            assert len(observes) >= 2
        finally:
            player.terminate()


class TestMPVControllerWSMode:
    def test_controller_builds_wsmpv_and_registers_observers(self, ws_settings):
        stub = ws_settings
        controller = MPVController()
        try:
            assert controller._connected is True
            assert isinstance(controller.player, WSMPV)
            stub.wait_for_client()
            observed = {c[2] for c in stub.received_commands if c[:1] == ["observe_property"]}
            assert {"chapter", "pause", "path", "idle-active", "playlist-pos", "time-pos"} <= observed
            stub.push_event({"event": "end-file", "reason": "eof"})
            time.sleep(0.1)
        finally:
            controller.terminate()

    def test_controller_command_methods_send_right_frames(self, ws_settings):
        stub = ws_settings
        controller = MPVController()
        try:
            controller.load_file("/tmp/movie.mp4")
            controller.set_audio_track(2)
            controller.set_subtitle_track(1)
            controller.set_property("speed", 1.5)
            controller.playlist_jump(4)
            time.sleep(0.1)
            cmds = stub.received_commands
            assert ["loadfile", "/tmp/movie.mp4", "replace"] in cmds
            assert ["set_property", "aid", 2] in cmds
            assert ["set_property", "sid", 1] in cmds
            assert ["set_property", "speed", 1.5] in cmds
            assert ["set_property", "playlist-pos", 4] in cmds
        finally:
            controller.terminate()

    def test_controller_get_property_round_trips(self, ws_settings):
        stub = ws_settings
        stub.property_values["volume"] = 55.0
        controller = MPVController()
        try:
            assert controller.get_property("volume") == 55.0
        finally:
            controller.terminate()

    def test_controller_observer_event_reaches_service_handler(self, ws_settings):
        stub = ws_settings
        controller = MPVController()
        got = []
        try:
            controller.add_event_handler("file_end", lambda data: got.append(data))
            stub.wait_for_client()
            stub.push_event({"event": "end-file", "reason": "eof"})
            _wait(lambda: got)
            assert got[0]["reason"] == "eof"
        finally:
            controller.terminate()

    def test_auth_header_reaches_agent(self, ws_settings):
        stub = ws_settings
        controller = MPVController()
        try:
            stub.wait_for_client()
            assert stub.auth_header == "Bearer sekret-token"
        finally:
            controller.terminate()


class TestNoHostDegradesGracefully:
    def test_ws_config_none_without_a_host(self, db):
        from cinefin.api.mpv_controller import _transport_config

        assert _transport_config() is None

    def test_controller_disconnected_without_a_host(self, db):
        controller = MPVController()
        assert controller._connected is False
        assert controller.player is None


class TestConcurrentSends:
    """Regression: every WS write must be serialized behind _send_lock."""

    def test_sends_are_serialized_and_none_dropped(self, stub):
        import threading

        wsmpv = _ws_controller(stub)
        try:
            active = 0
            max_concurrent = 0
            probe_lock = threading.Lock()
            orig_send = wsmpv._ws.send

            def probe_send(payload):
                nonlocal active, max_concurrent
                with probe_lock:
                    active += 1
                    max_concurrent = max(max_concurrent, active)
                try:
                    time.sleep(0.003)
                    return orig_send(payload)
                finally:
                    with probe_lock:
                        active -= 1

            wsmpv._ws.send = probe_send

            n = 24
            errors = []

            def worker():
                try:
                    wsmpv.command("get_property", "pause")
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

            threads = [threading.Thread(target=worker) for _ in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)

            assert not errors, f"concurrent commands failed (dropped/interleaved frames): {errors}"
            assert max_concurrent == 1, f"WS sends overlapped (max {max_concurrent}) — not serialized"
            got = [c for c in stub.received_commands if c and c[0] == "get_property"]
            assert len(got) == n, f"agent received {len(got)}/{n} frames intact"
        finally:
            wsmpv.terminate()


def _wait(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
