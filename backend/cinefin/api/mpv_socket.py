"""SocketMPV — the local-transport twin of WSMPV.

Same mpv JSON-IPC vocabulary and machinery; the only difference is the wire: a
plain operator-run mpv speaks newline-delimited JSON over a Unix socket instead
of the agent's WebSocket. Subclasses WSMPV, overriding only the transport
touchpoints. No process control — the operator owns the mpv process.
"""

import json
import logging
import socket

from .mpv_ws import WSMPV, MPVError, _note_reachable, _note_unreachable

logger = logging.getLogger(__name__)

_RECV_BYTES = 65536


class SocketMPV(WSMPV):
    """Drive a local mpv over its JSON-IPC Unix socket. Drop-in for WSMPV."""

    def __init__(self, socket_path, quit_callback=None, connect_timeout=5.0):
        # Must exist before WSMPV.__init__ opens the connection: both are in
        # _INTERNAL_ATTRS so __setattr__ stores them instead of sending set_property.
        self.socket_path = socket_path
        self._recv_buf = b""
        super().__init__(url=socket_path, token=None, quit_callback=quit_callback, connect_timeout=connect_timeout)

    def _open_connection(self):
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(self.connect_timeout)
            sock.connect(self.socket_path)
            sock.settimeout(None)  # persistent reader loop
        except OSError as e:
            _note_unreachable(self.url, str(e))
            raise MPVError(f"Cannot connect to mpv socket {self.socket_path}: {e}") from e
        with self._ws_lock:
            self._ws = sock
        self._recv_buf = b""
        _note_reachable(self.url)

    def _raw_send(self, ws, frame):
        """One newline-terminated JSON frame (mpv IPC framing is line-delimited), serialized against other writers."""
        payload = (json.dumps(frame) + "\n").encode("utf-8")
        with self._send_lock:
            ws.sendall(payload)

    def _recv_frames(self, ws):
        """Byte-stream read → complete JSON lines, buffering a partial trailing line. ``None`` when peer closed."""
        chunk = ws.recv(_RECV_BYTES)
        if not chunk:
            return None
        buf = self._recv_buf + chunk
        parts = buf.split(b"\n")
        self._recv_buf = parts[-1]  # trailing partial (or b"" after a clean split)
        return [p.decode("utf-8", "replace") for p in parts[:-1]]


def probe_socket(path, timeout=2.0):
    """Is a local mpv answering on ``path``? Returns ``(reachable, error)``.
    A refused/absent socket means no player (mpv only listens while running)."""
    if not path:
        return False, "No socket path configured"
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(path)
        sock.close()
        return True, None
    except OSError as e:
        return False, str(e)
