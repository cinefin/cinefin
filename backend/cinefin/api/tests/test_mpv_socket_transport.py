import json
import os
import socket
import tempfile
import threading
import time

import pytest

from cinefin.api.mpv_socket import SocketMPV, probe_socket


class UnixMpvStub:
    def __init__(self, property_values=None):
        self.property_values = property_values or {}
        self.received_commands = []
        self._dir = tempfile.mkdtemp()
        self.path = os.path.join(self._dir, "mpvsocket")
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.path)
        self._server.listen(1)
        self._running = True
        self._conn = None
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            self._conn = conn
            buf = b""
            while self._running:
                try:
                    chunk = conn.recv(65536)
                except OSError:
                    break
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    if line.strip():
                        self._on_command(conn, json.loads(line))

    def _on_command(self, conn, frame):
        cmd = frame.get("command", [])
        self.received_commands.append(cmd)
        rid = frame.get("request_id")
        if cmd and cmd[0] == "get_property":
            reply = {"request_id": rid, "error": "success", "data": self.property_values.get(cmd[1])}
        else:
            reply = {"request_id": rid, "error": "success", "data": cmd}
        conn.sendall((json.dumps(reply) + "\n").encode())

    def close(self):
        self._running = False
        try:
            self._server.close()
        except OSError:
            pass


@pytest.fixture
def stub():
    s = UnixMpvStub()
    yield s
    s.close()


def _wait(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


class TestSocketMPVSurface:
    def test_command_round_trips(self, stub):
        player = SocketMPV(stub.path)
        try:
            assert player.command("loadfile", "x.mkv") == ["loadfile", "x.mkv"]
            assert ["loadfile", "x.mkv"] in stub.received_commands
        finally:
            player.terminate()

    def test_property_attribute_get(self, stub):
        stub.property_values["pause"] = True
        player = SocketMPV(stub.path)
        try:
            assert player.pause is True
        finally:
            player.terminate()

    def test_property_attribute_set(self, stub):
        player = SocketMPV(stub.path)
        try:
            player.pause = False
            assert _wait(lambda: ["set_property", "pause", False] in stub.received_commands)
        finally:
            player.terminate()

    def test_dashed_property_name_normalised(self, stub):
        player = SocketMPV(stub.path)
        try:
            player.loop_file = "inf"
            assert _wait(lambda: ["set_property", "loop-file", "inf"] in stub.received_commands)
        finally:
            player.terminate()

    def test_connect_failure_raises(self):
        from cinefin.api.mpv_ws import MPVError

        with pytest.raises(MPVError):
            SocketMPV("/tmp/does-not-exist-cinefin.sock", connect_timeout=0.5)


class TestProbeSocket:
    def test_reachable_when_serving(self, stub):
        ok, err = probe_socket(stub.path)
        assert ok is True
        assert err is None

    def test_unreachable_when_absent(self):
        ok, err = probe_socket("/tmp/nope-cinefin.sock")
        assert ok is False
        assert err

    def test_empty_path(self):
        ok, err = probe_socket("")
        assert ok is False
