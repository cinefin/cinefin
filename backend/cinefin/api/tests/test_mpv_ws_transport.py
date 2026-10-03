"""Contract tests for the WS control transport."""

import threading
import time

import pytest

from cinefin.api.mpv_controller import MPVController
from cinefin.api.mpv_ws import WSMPV, MPVError, build_ws_control_url

from .ws_stub_agent import StubAgent


def _wait(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not predicate():
        time.sleep(interval)
    return predicate()


@pytest.fixture
def stub():
    with StubAgent() as agent:
        yield agent


@pytest.fixture
def player(stub):
    p = WSMPV(stub.url, token="sekret-token")
    yield p
    p.terminate()


@pytest.fixture
def controller(db, stub):
    from cinefin.api.models import PlayoutHost

    PlayoutHost.objects.all().delete()
    PlayoutHost.objects.create(
        name="Stub", base_url=f"http://127.0.0.1:{stub.port}", token="sekret-token", is_active=True
    )
    c = MPVController()
    yield c
    c.terminate()


@pytest.mark.parametrize(
    "base,url",
    [
        ("http://127.0.0.1:8089", "ws://127.0.0.1:8089/ws/control"),
        ("https://booth:8089/", "wss://booth:8089/ws/control"),
        ("127.0.0.1:8089", "ws://127.0.0.1:8089/ws/control"),
    ],
)
def test_build_ws_control_url(base, url):
    assert build_ws_control_url(base) == url


class TestWSMPV:
    def test_commands_and_properties_round_trip(self, stub, player):
        stub.property_values.update({"time-pos": 12.5, "pause": True})
        assert player.command("loadfile", "/tmp/x.mp4", "replace") == ["loadfile", "/tmp/x.mp4", "replace"]
        assert player.command("get_property", "time-pos") == 12.5
        assert player.pause is True
        player.loop_file = "inf"  # attribute names map to dashed properties
        assert ["set_property", "loop-file", "inf"] in stub.received_commands
        assert stub.auth_header == "Bearer sekret-token"

    def test_error_reply_raises_and_unavailable_property_is_none(self, stub, player):
        stub.errors.update({"bad": "boom", "get_property": "property unavailable"})
        with pytest.raises(MPVError):
            player.command("bad")
        assert player.command("get_property", "duration") is None

    def test_read_timeout_drops_connection(self, stub, player):
        stub.errors["get_property"] = None
        with pytest.raises(TimeoutError):
            player.command("get_property", "pause", timeout=0.3)
        assert _wait(lambda: player._ws is None, timeout=2.0)

    def test_observer_unobserves_its_id_first(self, stub, player):
        # The agent's mpv outlives Cinefin and ids restart at 1, so a dead session leaves
        # a twin observer under the same id; without the unobserve every change fires twice.
        stub.property_values["time-pos"] = 3.0
        received = []
        oid = player.bind_property_observer("time-pos", lambda name, data: received.append((name, data)))
        assert _wait(lambda: received) and received == [("time-pos", 3.0)]
        cmds = stub.received_commands
        assert cmds.index(["unobserve_property", oid]) < cmds.index(["observe_property", oid, "time-pos"])

    def test_callback_may_issue_command_without_deadlock(self, stub, player):
        stub.property_values.update({"time-pos": 1.0, "playlist-count": 3})
        inner = []
        player.bind_property_observer(
            "time-pos", lambda n, d: inner.append(player.command("get_property", "playlist-count"))
        )
        assert _wait(lambda: inner) and inner == [3]

    def test_reconnect_resubscribes_observers(self, stub, player):
        events = []
        player.bind_property_observer("pause", lambda name, data: events.append(data))
        assert _wait(lambda: events)
        first = stub.connection_count
        stub.drop_client()
        assert _wait(lambda: stub.connection_count > first, timeout=8.0)
        assert _wait(lambda: len(events) >= 2, timeout=8.0)
        assert len([c for c in stub.received_commands if c[:1] == ["observe_property"]]) >= 2

    def test_reconnect_callback_runs_before_the_observers_report_again(self, stub, player):
        order = []
        player.bind_property_observer("pause", lambda name, data: order.append("value"))
        assert _wait(lambda: order)
        player.reconnect_callback = lambda: order.append("reconnected")
        stub.drop_client()
        assert _wait(lambda: order.count("value") >= 2, timeout=8.0)
        assert order[1:] == ["reconnected", "value"]

    def test_concurrent_sends_are_serialized_and_none_dropped(self, stub, player):
        active = max_concurrent = 0
        lock = threading.Lock()
        orig_send = player._ws.send

        def probe_send(payload):
            nonlocal active, max_concurrent
            with lock:
                active += 1
                max_concurrent = max(max_concurrent, active)
            try:
                time.sleep(0.003)
                return orig_send(payload)
            finally:
                with lock:
                    active -= 1

        player._ws.send = probe_send
        errors = []

        def worker():
            try:
                player.command("get_property", "pause")
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(24)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert not errors and max_concurrent == 1
        assert len([c for c in stub.received_commands if c and c[0] == "get_property"]) == 24


class TestMPVController:
    def test_connects_and_observes(self, stub, controller):
        assert isinstance(controller.player, WSMPV)
        stub.wait_for_client()
        observed = {c[2] for c in stub.received_commands if c[:1] == ["observe_property"]}
        assert {"chapter", "pause", "path", "playlist-pos", "time-pos"} <= observed
        got = []
        controller.add_event_handler("file_end", got.append)
        stub.push_event({"event": "end-file", "reason": "eof"})
        assert _wait(lambda: got) and got[0]["reason"] == "eof"

    def test_command_methods_send_the_right_frames(self, stub, controller):
        controller.load_file("/tmp/movie.mp4")
        controller.load_file("/tmp/a.mp4", options="end=5", title="Trailer: Crazy, Stupid, Love")
        controller.enqueue_file("/tmp/b.mp4", title="Command: Lights")
        controller.set_audio_track(2)
        controller.set_subtitle_track(1)
        controller.playlist_jump(4)
        cmds = stub.received_commands
        assert ["loadfile", "/tmp/movie.mp4", "replace"] in cmds
        # force-media-title's %N% prefix is the byte length (commas are fine inside it).
        assert [
            "loadfile",
            "/tmp/a.mp4",
            "replace",
            -1,
            "end=5,force-media-title=%28%Trailer: Crazy, Stupid, Love",
        ] in cmds
        assert ["loadfile", "/tmp/b.mp4", "append", -1, "force-media-title=%15%Command: Lights"] in cmds
        assert ["set_property", "aid", 2] in cmds
        assert ["set_property", "sid", 1] in cmds
        assert ["set_property", "playlist-pos", 4] in cmds
