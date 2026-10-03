"""FakeMPVAgent — a stateful, in-process playout agent for simulation tests.

It models what Cinefin relies on from mpv and the player: per-file options
(``ab-loop-a``/``ab-loop-b`` loop a range, ``end`` stops early, and
``keep-open=always`` holds the last frame paused instead of moving on), and the
player's standby (``put_standby``/``enter_standby``/``standby_status``, which
the tests wire in place of the agent's HTTP endpoints)."""

import json
import threading

from .ws_stub_agent import StubAgent, _send_frame

DEFAULT_DURATION = 30.0
BUNDLED_IDENT = "/usr/share/cinefin-playout/ident.mp4"
BUNDLED_OPTIONS = "ab-loop-a=4,ab-loop-b=34"


def parse_options(options: str) -> dict[str, str]:
    return dict(pair.split("=", 1) for pair in options.split(",") if "=" in pair) if options else {}


class FakeMPVAgent(StubAgent):
    def __init__(self):
        # State must exist before super().__init__ starts the server thread.
        self.playlist: list[str] = []
        self.entry_options: list[dict] = []  # per-file options, parallel to playlist
        self.eof_reached = False
        self.standby_spec: dict | None = None
        self.standby_loaded: str | None = None
        self.pos: int | None = None
        self.paused = False
        self.time_pos = 0.0
        self.props: dict[str, object] = {}
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

    @property
    def current_options(self) -> dict:
        with self._state_lock:
            if self.pos is None or not (0 <= self.pos < len(self.entry_options)):
                return {}
            return self.entry_options[self.pos]

    def _set_pos(self, new_pos):
        with self._state_lock:
            self.pos = new_pos
            self.time_pos = 0.0
            self.eof_reached = False
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
                return DEFAULT_DURATION if self.current_file else None
            if name in ("path", "stream-open-filename", "filename"):
                return self.current_file
            if name == "idle-active":
                return self.pos is None
            if name == "track-list":
                return []
            if name == "loop-file":
                return self.props.get("loop-file", "no")
            if name == "eof-reached":
                return self.eof_reached
            if name in ("ab-loop-a", "ab-loop-b", "end", "keep-open"):
                return self.current_options.get(name, "no")
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
        # mpv's named-argument form is a dict ({"name": ..., ...}).
        name = cmd.get("name") if isinstance(cmd, dict) else cmd[0] if cmd else None

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
            # mpv 0.38+: loadfile <url> <flags> <index> <options>
            reply()
            self._loadfile(cmd[1], cmd[2] if len(cmd) > 2 else "replace", cmd[4] if len(cmd) > 4 else "")
        elif name == "playlist-next":
            reply()
            with self._state_lock:
                can_advance = self.pos is not None and self.pos < len(self.playlist) - 1
                target = (self.pos or 0) + 1
            if can_advance:
                self._set_pos(target)
        elif name == "playlist-clear":
            # mpv keeps the currently playing entry.
            with self._state_lock:
                current, options = self.current_file, self.current_options
                self.playlist = [current] if current else []
                self.entry_options = [options] if current else []
                if current:
                    self.pos = 0
            reply()
            if current:
                self._emit_property("playlist-pos", 0)
        elif name == "playlist-move":
            # mpv semantics: move entry i so it lands before entry j (j may be len).
            i, j = int(cmd[1]), int(cmd[2])
            with self._state_lock:
                current = self.current_file
                entry = self.playlist.pop(i)
                self.playlist.insert(j - 1 if j > i else j, entry)
                if i < len(self.entry_options):
                    self.entry_options.insert(j - 1 if j > i else j, self.entry_options.pop(i))
                if current is not None:
                    self.pos = self.playlist.index(current)
            reply()
        elif name == "playlist-remove":
            i = int(cmd[1])
            with self._state_lock:
                self.playlist.pop(i)
                if i < len(self.entry_options):
                    self.entry_options.pop(i)
                removing_current = i == self.pos
                if self.pos is not None and i < self.pos:
                    self.pos -= 1
            reply()
            if removing_current:
                self._set_pos(i)
        elif name == "playlist-play-index":
            reply()
            self._set_pos(int(cmd[1]))
        else:
            reply(cmd)

    def _loadfile(self, url, mode, options=""):
        with self._state_lock:
            if mode == "replace":
                self.playlist, self.entry_options = [url], [parse_options(options)]
            else:
                self.playlist.append(url)
                self.entry_options.append(parse_options(options))
        if mode == "replace":
            self._set_pos(0)

    def finish_current(self, reason="eof"):
        """The current file reaches its end (or its ``end`` option). A looped
        range goes round again, and ``keep-open=always`` holds the last frame,
        paused; otherwise mpv moves to the next entry."""
        options = self.current_options
        if reason == "eof" and "ab-loop-b" in options:
            self.set_time(float(options.get("ab-loop-a", 0)))
            return
        if reason == "eof" and options.get("keep-open") == "always":
            with self._state_lock:
                self.eof_reached = True
                if "end" in options:
                    self.time_pos = float(options["end"])
            self._emit_property("eof-reached", True)
            self._set_prop("pause", True)
            return
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
        end = self.current_options.get("end")
        if end is not None and float(seconds) >= float(end):
            self.finish_current()  # an ``end`` option stops the file there
            return
        with self._state_lock:
            self.time_pos = float(seconds)
        self._emit_property("time-pos", float(seconds))

    def commands_named(self, name):
        return [c for c in list(self.received_commands) if c and not isinstance(c, dict) and c[0] == name]

    def overlays(self):
        """The osd-overlay commands received (named-argument dicts), in order."""
        return [c for c in list(self.received_commands) if isinstance(c, dict) and c.get("name") == "osd-overlay"]

    # The player's standby, called in place of its HTTP endpoints (see agent_http()).

    def put_standby(self, spec):
        with self._state_lock:
            self.standby_spec = spec
        return self.standby_status()

    def enter_standby(self):
        spec = self.standby_spec
        if spec:
            path, options = f"/state/idents/{spec['ident']['sha256']}.mp4", spec["ident"]["options"]
        else:
            path, options = BUNDLED_IDENT, BUNDLED_OPTIONS
        self._loadfile(path, "replace", options)
        with self._state_lock:
            self.standby_loaded = path
        self._set_prop("pause", False)
        return self.standby_status()

    def standby_status(self):
        with self._state_lock:
            spec = self.standby_spec
            return {
                "spec": {**spec, "ident": {k: v for k, v in spec["ident"].items() if k != "url"}} if spec else None,
                "file": "",
                "downloading": False,
                "error": "",
                "on_standby": self.current_file is not None and self.current_file == self.standby_loaded,
            }


def agent_http(monkeypatch, fake):
    """Answer the agent's standby HTTP calls from ``fake`` (the fake speaks only WebSocket)."""
    from cinefin.api.services.playout_agent_service import PlayoutAgentService

    monkeypatch.setattr(PlayoutAgentService, "put_standby", classmethod(lambda cls, host, spec: fake.put_standby(spec)))
    monkeypatch.setattr(PlayoutAgentService, "enter_standby", classmethod(lambda cls, host: fake.enter_standby()))
    monkeypatch.setattr(
        PlayoutAgentService, "host_status", classmethod(lambda cls, host: {"standby": fake.standby_status()})
    )
