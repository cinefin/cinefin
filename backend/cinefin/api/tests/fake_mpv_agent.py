"""FakeMPVAgent — a stateful, in-process playout agent for simulation tests."""

import json
import threading

from .ws_stub_agent import StubAgent, _send_frame

DEFAULT_DURATION = 30.0


class FakeMPVAgent(StubAgent):
    def __init__(self, durations=None):
        # State must exist before super().__init__ starts the server thread.
        self.playlist: list[str] = []
        self.pos: int | None = None
        self.paused = False
        self.time_pos = 0.0
        self.durations = durations or {}
        self.props: dict[str, object] = {}
        self.track_list: list[dict] = []
        self._observers: dict[int, str] = {}
        self._state_lock = threading.RLock()
        # Frames are pushed from both the connection thread and the test thread;
        # unserialized writes would interleave bytes on the wire.
        self._send_io_lock = threading.Lock()
        super().__init__()

    def push_event(self, event):
        with self._conn_lock:
            conn = self._conn
        if conn is not None:
            with self._send_io_lock:
                _send_frame(conn, json.dumps(event))

    @property
    def current_file(self):
        with self._state_lock:
            if self.pos is None or not (0 <= self.pos < len(self.playlist)):
                return None
            return self.playlist[self.pos]

    def _emit_property(self, name, value):
        for observer_id, prop in list(self._observers.items()):
            if prop == name:
                self.push_event({"event": "property-change", "id": observer_id, "name": name, "data": value})

    def _set_pos(self, new_pos):
        with self._state_lock:
            self.pos = new_pos
            self.time_pos = 0.0
            current = self.current_file
        self.push_event({"event": "start-file", "playlist_entry_id": (new_pos or 0) + 1})
        self._emit_property("path", current)
        self._emit_property("playlist-pos", new_pos if new_pos is not None else -1)
        self._emit_property("time-pos", 0.0)

    def _get_prop(self, name):
        with self._state_lock:
            if name == "playlist":
                return [
                    {"filename": f, "id": i + 1, "current": i == self.pos, "playing": i == self.pos}
                    for i, f in enumerate(self.playlist)
                ]
            if name == "playlist-pos":
                return self.pos if self.pos is not None else -1
            if name == "pause":
                return self.paused
            if name == "time-pos":
                return self.time_pos if self.pos is not None else None
            if name == "duration":
                current = self.current_file
                return self.durations.get(current, DEFAULT_DURATION) if current else None
            if name in ("path", "stream-open-filename", "filename"):
                return self.current_file
            if name == "idle-active":
                return self.pos is None
            if name == "track-list":
                return self.track_list
            if name == "loop-file":
                return self.props.get("loop-file", "no")
            return self.props.get(name)

    def _set_prop(self, name, value):
        if name == "pause":
            with self._state_lock:
                changed = self.paused != bool(value)
                self.paused = bool(value)
            if changed:
                self._emit_property("pause", self.paused)
            return
        if name == "playlist-pos":
            self._set_pos(int(value))
            return
        with self._state_lock:
            self.props[name] = value
        self._emit_property(name, value)

    def _on_command(self, conn, frame):
        cmd = frame.get("command", [])
        rid = frame.get("request_id")
        self.received_commands.append(cmd)
        name = cmd[0] if cmd else None

        def reply(data=None, error="success"):
            with self._send_io_lock:
                _send_frame(conn, json.dumps({"request_id": rid, "error": error, "data": data}))

        if name == "get_property":
            reply(self._get_prop(cmd[1]))
        elif name == "set_property":
            reply()
            self._set_prop(cmd[1], cmd[2])
        elif name == "observe_property":
            observer_id, prop = cmd[1], cmd[2]
            self._observers[observer_id] = prop
            reply()
            self.push_event({"event": "property-change", "id": observer_id, "name": prop, "data": self._get_prop(prop)})
        elif name == "unobserve_property":
            self._observers.pop(cmd[1], None)
            reply()
        elif name == "loadfile":
            url = cmd[1]
            mode = cmd[2] if len(cmd) > 2 else "replace"
            reply()
            if mode == "replace":
                with self._state_lock:
                    self.playlist = [url]
                self._set_pos(0)
            else:
                with self._state_lock:
                    self.playlist.append(url)
        elif name == "playlist-next":
            reply()
            with self._state_lock:
                can_advance = self.pos is not None and self.pos < len(self.playlist) - 1
                target = (self.pos or 0) + 1
            if can_advance:
                self._set_pos(target)
        elif name == "playlist-prev":
            reply()
            with self._state_lock:
                can_retreat = self.pos is not None and self.pos > 0
                target = (self.pos or 1) - 1
            if can_retreat:
                self._set_pos(target)
        elif name == "playlist-clear":
            # mpv keeps the currently playing entry.
            with self._state_lock:
                current = self.current_file
                self.playlist = [current] if current else []
                if current:
                    self.pos = 0
            reply()
            if current:
                self._emit_property("playlist-pos", 0)
        elif name == "stop":
            reply()
            with self._state_lock:
                self.playlist = []
                self.pos = None
            self._emit_property("playlist-pos", -1)
            self._emit_property("idle-active", True)
        else:
            reply(cmd)

    def finish_current(self, reason="eof"):
        self.push_event({"event": "end-file", "reason": reason})
        with self._state_lock:
            at_end = self.pos is None or self.pos >= len(self.playlist) - 1
            target = (self.pos or 0) + 1
        if at_end:
            with self._state_lock:
                self.pos = None
            self._emit_property("playlist-pos", -1)
            self._emit_property("idle-active", True)
        else:
            self._set_pos(target)

    def set_time(self, seconds):
        with self._state_lock:
            self.time_pos = float(seconds)
        self._emit_property("time-pos", float(seconds))

    def commands_named(self, name):
        return [c for c in list(self.received_commands) if c and c[0] == name]
