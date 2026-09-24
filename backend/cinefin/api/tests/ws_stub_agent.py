"""Minimal in-process WebSocket agent for the WSMPV contract tests."""

import base64
import hashlib
import json
import socket
import struct
import threading

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _accept_key(client_key: str) -> str:
    digest = hashlib.sha1((client_key + _WS_GUID).encode()).digest()
    return base64.b64encode(digest).decode()


def _read_http_headers(conn: socket.socket) -> dict:
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
    headers = {}
    for line in data.split(b"\r\n")[1:]:
        if b":" in line:
            k, _, v = line.partition(b":")
            headers[k.strip().decode().lower()] = v.strip().decode()
    return headers


def _recv_frame(conn: socket.socket):
    hdr = _recv_exact(conn, 2)
    if hdr is None:
        return None
    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0F
    masked = b2 & 0x80
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", _recv_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _recv_exact(conn, 8))[0]
    mask = _recv_exact(conn, 4) if masked else b"\x00\x00\x00\x00"
    payload = _recv_exact(conn, length) or b""
    if masked:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 0x8:
        return None
    return payload.decode()


def _recv_exact(conn: socket.socket, n: int):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


def _send_frame(conn: socket.socket, text: str) -> None:
    payload = text.encode()
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < 65536:
        header.append(126)
        header += struct.pack(">H", length)
    else:
        header.append(127)
        header += struct.pack(">Q", length)
    conn.sendall(bytes(header) + payload)


class StubAgent:
    """Threaded stub agent. Use as a context manager; ``url`` gives ws://…/ws/control."""

    def __init__(self, property_values=None):
        self.property_values = property_values or {}
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]

        self.received_commands = []
        self.auth_header = None
        self.connection_count = 0

        self._conn = None
        self._conn_lock = threading.Lock()
        self._client_ready = threading.Event()
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

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
        key = headers.get("sec-websocket-key", "")
        accept = _accept_key(key)
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        with self._conn_lock:
            self._conn = conn
        self._client_ready.set()
        try:
            while self._running:
                text = _recv_frame(conn)
                if text is None:
                    break
                self._on_command(conn, json.loads(text))
        except OSError:
            pass
        finally:
            with self._conn_lock:
                if self._conn is conn:
                    self._conn = None
            try:
                conn.close()
            except OSError:
                pass

    def _on_command(self, conn: socket.socket, frame: dict):
        cmd = frame.get("command", [])
        rid = frame.get("request_id")
        self.received_commands.append(cmd)
        name = cmd[0] if cmd else None

        if name == "get_property":
            prop = cmd[1] if len(cmd) > 1 else None
            data = self.property_values.get(prop)
            _send_frame(conn, json.dumps({"request_id": rid, "error": "success", "data": data}))
            return

        if name == "observe_property":
            observer_id = cmd[1]
            prop = cmd[2]
            _send_frame(conn, json.dumps({"request_id": rid, "error": "success"}))
            _send_frame(
                conn,
                json.dumps(
                    {
                        "event": "property-change",
                        "id": observer_id,
                        "name": prop,
                        "data": self.property_values.get(prop),
                    }
                ),
            )
            return

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
            conn = self._conn
            self._conn = None
        if conn is not None:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass

    def close(self) -> None:
        self._running = False
        self.drop_client()
        try:
            self._server.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
