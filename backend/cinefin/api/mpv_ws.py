"""WSMPV — a WebSocket transport standing in for the slice of
``python_mpv_jsonipc.MPV`` that MPVController touches, so the swap is invisible
to ``mpv_service``. The agent relays mpv's own JSON-IPC, so the wire vocabulary
is mpv's and needs no translation.

Threading model mirrors python-mpv-jsonipc: a daemon reader thread dispatches
replies by ``request_id`` and events to observers off the calling thread, so
callbacks never block command round-trips.
"""

import json
import logging
import queue
import threading

import websocket  # websocket-client

logger = logging.getLogger(__name__)


class MPVError(Exception):
    """mpv command returned ``error != "success"`` or the link is unusable.
    Named after python-mpv-jsonipc's error type so ``except MPVError`` callers keep working."""


# Match python-mpv-jsonipc's command timeout (its module-level TIMEOUT is 120s).
COMMAND_TIMEOUT = 120.0
# Reads must fail fast: a silently-dropped peer buffers the send without error and
# never replies, so a full COMMAND_TIMEOUT block would keep the UI showing stale
# "connected". Reads are sub-second when alive, so this never bites the happy path.
READ_TIMEOUT = 5.0
RECONNECT_DELAY = 2.0

# Reachability "log once per episode" state, keyed by WS URL.
_reachable_state: dict[str, bool] = {}


def _note_unreachable(url: str, reason: str) -> None:
    if _reachable_state.get(url) is not False:
        logger.warning("MPV agent not reachable at %s (%s) — playout needs a running agent.", url, reason)
    _reachable_state[url] = False


def _note_reachable(url: str) -> None:
    if _reachable_state.get(url) is False:
        logger.info("MPV agent reachable again at %s", url)
    _reachable_state[url] = True


class WSMPV:
    """Drop-in for ``python_mpv_jsonipc.MPV``, speaking mpv JSON-IPC over a
    WebSocket to the agent's ``/ws/control`` endpoint."""

    def __init__(self, url, token=None, quit_callback=None, connect_timeout=5.0):
        self.url = url
        self.token = token
        self.quit_callback = quit_callback
        self.connect_timeout = connect_timeout

        self._ws = None
        self._ws_lock = threading.Lock()
        # websocket-client's send() is NOT safe for concurrent writes: interleaved
        # bytes make an unparseable frame the agent drops. Many threads send, so
        # every write goes through this lock.
        self._send_lock = threading.Lock()

        self._rid = 1
        self._rid_lock = threading.Lock()
        self._pending: dict[int, threading.Event] = {}
        self._results: dict[int, dict] = {}

        self._observer_id = 1
        self._observer_lock = threading.Lock()
        self._observers: dict[int, tuple[str, object]] = {}

        self._event_bindings: dict[str, set] = {}

        self._closed = False
        self._quit_fired = False

        # Callbacks run on a dedicated FIFO worker, NOT the reader thread: observer
        # handlers call back into the controller, so running them inline would
        # deadlock (command() would block for a reply the busy reader can't deliver).
        # A single worker preserves event ordering (cue sequencing depends on it).
        self._callbacks: queue.Queue = queue.Queue()

        # First connect synchronously so MPVController's constructor sees a live link (raises on failure).
        self._open_connection()

        self._reader = threading.Thread(target=self._read_loop, name="wsmpv-reader", daemon=True)
        self._reader.start()
        self._dispatcher = threading.Thread(target=self._dispatch_loop, name="wsmpv-dispatch", daemon=True)
        self._dispatcher.start()

    def _dispatch_loop(self):
        """Run queued observer/event callbacks serially, off the reader thread."""
        while True:
            fn = self._callbacks.get()
            if fn is None:  # shutdown sentinel
                return
            try:
                fn()
            except Exception as e:  # noqa: BLE001 — a callback must not kill the dispatcher
                logger.error("WSMPV callback raised: %s", e)

    def _open_connection(self):
        header = []
        if self.token:
            header.append(f"Authorization: Bearer {self.token}")
        try:
            ws = websocket.create_connection(self.url, timeout=self.connect_timeout, header=header)
            ws.settimeout(None)  # persistent reader loop
        except Exception as e:
            _note_unreachable(self.url, str(e))
            raise MPVError(f"Cannot connect to agent WS: {e}") from e
        with self._ws_lock:
            self._ws = ws
        _note_reachable(self.url)

    def _resubscribe(self):
        """Re-register property observers after a reconnect (mpv drops them).

        Runs on the reader thread, so it must NOT block on replies (the reader is
        what delivers them) — send the observe_property frames fire-and-forget.
        """
        with self._observer_lock:
            observers = list(self._observers.items())
        for observer_id, (name, _cb) in observers:
            try:
                self._send_fire_and_forget({"command": ["observe_property", observer_id, name]})
            except Exception as e:  # noqa: BLE001 — best effort; loop resumes on next reconnect
                logger.error("WSMPV re-subscribe of %s failed: %s", name, e)

    def _raw_send(self, ws, frame):
        """Write one frame, serialized against all other writers (see _send_lock)."""
        payload = json.dumps(frame)
        with self._send_lock:
            ws.send(payload)

    def _send_fire_and_forget(self, frame):
        with self._ws_lock:
            ws = self._ws
        if ws is not None:
            self._raw_send(ws, frame)

    def _recv_frames(self, ws):
        """One blocking read → its complete JSON frames, or ``None`` when the peer
        closed. The agent may pack several newline-delimited frames per WS message.
        Overridden by the socket transport (byte stream); the rest is transport-agnostic."""
        raw = ws.recv()
        if raw is None or raw == "":
            return None
        return raw.splitlines()

    def _read_loop(self):
        while not self._closed:
            with self._ws_lock:
                ws = self._ws
            if ws is None:
                if not self._reconnect():
                    continue
                with self._ws_lock:
                    ws = self._ws
                if ws is None:
                    continue
            try:
                frames = self._recv_frames(ws)
            except Exception:  # noqa: BLE001 — connection dropped; try to recover
                self._drop_connection()
                continue
            if frames is None:  # peer closed the socket
                self._drop_connection()
                continue
            for line in frames:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                self._dispatch(data)

    def _dispatch(self, data):
        if "request_id" in data:
            rid = data["request_id"]
            event = self._pending.get(rid)
            if event is not None:
                self._results[rid] = data
                event.set()
            return
        if "event" in data:
            name = data["event"]
            # Callbacks are QUEUED to the dispatch thread, never run inline: they
            # call back into the controller and would deadlock the reader (see _dispatch_loop).
            if name == "property-change":
                observer_id = data.get("id")
                with self._observer_lock:
                    entry = self._observers.get(observer_id)
                if entry is not None:
                    _obs_name, cb = entry
                    pname, pdata = data.get("name"), data.get("data")
                    self._callbacks.put(lambda: cb(pname, pdata))
                return
            for cb in list(self._event_bindings.get(name, ())):
                self._callbacks.put(lambda cb=cb: cb(data))

    def _drop_connection(self):
        """Tear down the current WS, wake blocked commands, fire quit_callback once."""
        with self._ws_lock:
            ws = self._ws
            self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass
            _note_unreachable(self.url, "connection dropped")
        # Wake any command blocked on a reply so it fails fast instead of hanging.
        for rid, event in list(self._pending.items()):
            self._results[rid] = {"request_id": rid, "error": "connection lost"}
            event.set()
        if not self._quit_fired and self.quit_callback and not self._closed:
            self._quit_fired = True
            try:
                self.quit_callback()
            except Exception as e:  # noqa: BLE001
                logger.error("WSMPV quit_callback raised: %s", e)

    def _reconnect(self):
        """One reconnect + observer re-subscribe. Returns True on success."""
        if self._closed:
            return False
        try:
            self._open_connection()
        except Exception:  # noqa: BLE001 — already logged once via _note_unreachable
            stop = threading.Event()
            stop.wait(RECONNECT_DELAY)  # back off before the reader retries
            return False
        # Fresh link = possibly-restarted mpv: allow quit_callback to fire again, re-register observers.
        self._quit_fired = False
        self._resubscribe()
        return True

    def command(self, command, *args, timeout=None):
        """Send the command frame, block for the reply, return ``data``. Raises
        MPVError on ``error != "success"``, returns None for ``property unavailable``
        — byte-for-byte python-mpv-jsonipc's ``command``.

        A reply that never arrives means a silent half-open drop the reader can't
        see (its recv blocks forever), so we tear the link down here to unblock it.
        """
        with self._rid_lock:
            rid = self._rid
            self._rid += 1

        event = threading.Event()
        self._pending[rid] = event
        frame = {"command": [command, *args], "request_id": rid}

        with self._ws_lock:
            ws = self._ws
        if ws is None:
            self._pending.pop(rid, None)
            raise MPVError("Not connected to MPV agent.")
        try:
            self._raw_send(ws, frame)
        except Exception as e:
            self._pending.pop(rid, None)
            self._drop_connection()
            raise MPVError(f"Send to MPV agent failed: {e}") from e

        got = event.wait(timeout=timeout if timeout is not None else COMMAND_TIMEOUT)
        data = self._results.pop(rid, None)
        self._pending.pop(rid, None)
        if not got or data is None:
            # No reply: on a silent drop the send never errored, so close here to
            # unblock the reader's recv() and flip _ws to None (next call fails fast).
            self._drop_connection()
            raise TimeoutError("No response from MPV agent.")
        error = data.get("error")
        if error != "success":
            if error == "property unavailable":
                return None
            raise MPVError(error)
        return data.get("data")

    def play(self, url):
        self.command("loadfile", url)

    def bind_property_observer(self, name, callback):
        with self._observer_lock:
            observer_id = self._observer_id
            self._observer_id += 1
            self._observers[observer_id] = (name, callback)
        self.command("observe_property", observer_id, name)
        return observer_id

    def bind_event(self, name, callback):
        self._event_bindings.setdefault(name, set()).add(callback)

    def terminate(self, join=True):
        """Close the WS. Does NOT stop agent-side mpv (that's ``/mpv/stop``)."""
        self._closed = True
        self._callbacks.put(None)  # stop the dispatch worker
        with self._ws_lock:
            ws = self._ws
            self._ws = None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # noqa: BLE001
                pass

    def __getattr__(self, name):
        """Non-attribute reads are mpv property reads (dashes restored). Fail fast
        (READ_TIMEOUT) so a dead agent can't hang a status poll."""
        return self.command("get_property", name.replace("_", "-"), timeout=READ_TIMEOUT)

    def __setattr__(self, name, value):
        """Internal names go to __dict__; everything else is an mpv property write."""
        if name in _INTERNAL_ATTRS:
            object.__setattr__(self, name, value)
            return
        self.command("set_property", name.replace("_", "-"), value)


# Names WSMPV owns as real instance attributes — assignments to these go to
# __dict__; everything else on a WSMPV instance is an mpv property write.
_INTERNAL_ATTRS = frozenset(
    {
        "url",
        "token",
        "quit_callback",
        "connect_timeout",
        "_ws",
        "_ws_lock",
        "_send_lock",
        "_rid",
        "_rid_lock",
        "_pending",
        "_results",
        "_observer_id",
        "_observer_lock",
        "_observers",
        "_event_bindings",
        "_closed",
        "_quit_fired",
        "_reader",
        "_callbacks",
        "_dispatcher",
        # Owned by the local-socket subclass (SocketMPV) — same __setattr__ trap.
        "socket_path",
        "_recv_buf",
    }
)


def build_ws_control_url(agent_url):
    """``http(s)://host:port`` → ``ws(s)://host:port/ws/control`` (https maps to wss for a fronting proxy)."""
    base = (agent_url or "").strip().rstrip("/")
    if base.startswith("https://"):
        base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        base = "ws://" + base[len("http://") :]
    elif not (base.startswith("ws://") or base.startswith("wss://")):
        base = "ws://" + base
    return base + "/ws/control"
