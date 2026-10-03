"""Minimal in-process WebSocket agent for the WSMPV contract tests."""

import base64
import contextlib
import hashlib
import json
import socket
import struct
import threading

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _read_http_headers(conn: socket.socket) -> dict:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    headers = {}
    for line in data.split(b"\r\n")[1:]:
        k, sep, v = line.partition(b":")
        if sep:
            headers[k.strip().decode().lower()] = v.strip().decode()
    return headers


def _recv_exact(conn: socket.socket, n: int):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _recv_raw_frame(conn: socket.socket):
    hdr = _recv_exact(conn, 2)
    if hdr is None:
        return None, b""
    opcode, masked, length = hdr[0] & 0x0F, hdr[1] & 0x80, hdr[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", _recv_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exact(conn, 8))[0]
    mask = _recv_exact(conn, 4) if masked else b"\x00\x00\x00\x00"
    payload = _recv_exact(conn, length) or b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _send_frame(conn: socket.socket, text: str, opcode: int = 0x1) -> None:
    payload = text.encode()
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header += bytes([126]) + struct.pack(">H", length)
    else:
        header += bytes([127]) + struct.pack(">Q", length)
    conn.sendall(bytes(header) + payload)


class StubAgent:
    """Threaded stub agent; a context manager. ``errors`` maps a command name to an
    mpv error string to reply with, or None to swallow the request unanswered."""

    def __init__(self):
        self.property_values = {}
        self.errors: dict[str, str | None] = {}
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self.received_commands = []
        self.auth_header = None
        self.connection_count = 0
        self.pings = 0
        self.answer_pings = True  # False plays a dead agent
        self._conn = None
        self._conn_lock = threading.Lock()
        self._client_ready = threading.Event()
        self._running = True
        threading.Thread(target=self._serve, daemon=True).start()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/ws/control"

    def _serve(self):
        while self._running:
            try:
                conn, _ = self._server.accept()
            except OSError:
                return
            self.connection_count += 1
            self._handle(conn)

    def _handle(self, conn: socket.socket):
        headers = _read_http_headers(conn)
        self.auth_header = headers.get("authorization")
        accept = base64.b64encode(hashlib.sha1((headers.get("sec-websocket-key", "") + _WS_GUID).encode()).digest())
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept + b"\r\n\r\n"
        )
        with self._conn_lock:
            self._conn = conn
        self._client_ready.set()
        try:
            while self._running:
                opcode, payload = _recv_raw_frame(conn)
                if opcode is None or opcode == 0x8:
                    break
                if opcode == 0x9:
                    self.pings += 1
                    if self.answer_pings:
                        _send_frame(conn, payload.decode(), opcode=0xA)
                elif opcode != 0xA:
                    self._on_command(conn, json.loads(payload.decode()))
        except OSError:
            pass
        finally:
            with self._conn_lock:
                if self._conn is conn:
                    self._conn = None
            with contextlib.suppress(OSError):
                conn.close()

    def _on_command(self, conn: socket.socket, frame: dict):
        cmd = frame.get("command", [])
        rid = frame.get("request_id")
        self.received_commands.append(cmd)
        name = cmd[0] if cmd else None
        if name in self.errors:
            if self.errors[name] is not None:
                _send_frame(conn, json.dumps({"request_id": rid, "error": self.errors[name]}))
            return
        if name == "get_property":
            _send_frame(
                conn, json.dumps({"request_id": rid, "error": "success", "data": self.property_values.get(cmd[1])})
            )
        elif name == "observe_property":
            _send_frame(conn, json.dumps({"request_id": rid, "error": "success"}))
            event = {"event": "property-change", "id": cmd[1], "name": cmd[2], "data": self.property_values.get(cmd[2])}
            _send_frame(conn, json.dumps(event))
        else:
            _send_frame(conn, json.dumps({"request_id": rid, "error": "success", "data": cmd}))

    def push_event(self, event: dict) -> None:
        with self._conn_lock:
            conn = self._conn
        if conn is not None:
            _send_frame(conn, json.dumps(event))

    def wait_for_client(self, timeout=5.0) -> bool:
        return self._client_ready.wait(timeout)

    def drop_client(self) -> None:
        self._client_ready.clear()
        with self._conn_lock:
            conn, self._conn = self._conn, None
        if conn is not None:
            with contextlib.suppress(OSError):
                conn.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                conn.close()

    def close(self) -> None:
        self._running = False
        self.drop_client()
        with contextlib.suppress(OSError):
            self._server.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
