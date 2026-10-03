"""MPVController and the connection around it: one self-healing link, value coercion, the Unix-socket transport."""

import json
import os
import socket
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from cinefin.api.mpv_controller import MPVController
from cinefin.api.mpv_service import MPVService
from cinefin.api.mpv_socket import SocketMPV, probe_socket


class TestSingleSelfHealingConnection:
    """One WSMPV per controller: a second connection duplicates observers and skips items."""

    def test_errors_and_quit_keep_the_one_connection(self):
        c = MPVController()
        player = c.player = MagicMock()
        c._connected = True
        player.command.side_effect = Exception("boom")
        with patch("cinefin.api.mpv_controller.WSMPV") as ws_cls:
            assert c._mpv_command("set_property", "pause", True) is False
            assert c._ensure_connected() is True
            c._on_quit()
        ws_cls.assert_not_called()
        assert c._connected is True and c.player is player

    @pytest.mark.django_db
    def test_the_service_builds_one_controller_and_retires_the_old(self, monkeypatch):
        built = []

        def make_controller():
            time.sleep(0.05)
            built.append(MagicMock(_connected=True))
            return built[-1]

        service = MPVService()
        for name in ("_restore_session", "_check_mpv_version", "apply_subtitle_style"):
            monkeypatch.setattr(service, name, lambda: None)
        with patch("cinefin.api.mpv_service.MPVController", side_effect=make_controller):
            threads = [threading.Thread(target=service._ensure_connected) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert len(built) == 1 and service.controller is built[0]
            assert service._connect() is True
        built[0].terminate.assert_called_once()
        assert service.controller is built[1]


class UnixMpvStub:
    """A local mpv's JSON IPC socket: newline-delimited JSON."""

    def __init__(self):
        self.property_values = {}
        self.received_commands = []
        self.path = os.path.join(tempfile.mkdtemp(), "mpvsocket")
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(self.path)
        self._server.listen(1)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            buf = b""
            while chunk := conn.recv(65536):
                *lines, buf = (buf + chunk).split(b"\n")
                for line in filter(bytes.strip, lines):
                    frame = json.loads(line)
                    cmd = frame.get("command", [])
                    self.received_commands.append(cmd)
                    data = self.property_values.get(cmd[1]) if cmd[:1] == ["get_property"] else cmd
                    reply = {"request_id": frame.get("request_id"), "error": "success", "data": data}
                    conn.sendall((json.dumps(reply) + "\n").encode())


def test_socket_transport():
    stub = UnixMpvStub()
    stub.property_values["pause"] = True
    assert probe_socket(stub.path) == (True, None)
    player = SocketMPV(stub.path)
    try:
        assert player.command("loadfile", "x.mkv") == ["loadfile", "x.mkv"]
        assert player.pause is True
        player.loop_file = "inf"
        deadline = time.monotonic() + 5
        while ["set_property", "loop-file", "inf"] not in stub.received_commands and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ["set_property", "loop-file", "inf"] in stub.received_commands
    finally:
        player.terminate()
        stub._server.close()
