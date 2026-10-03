import logging
import threading
import time

from .mpv_socket import SocketMPV
from .mpv_ws import WSMPV, build_ws_control_url

logger = logging.getLogger(__name__)


def _transport_config():
    """How to reach the active playout host, or ``None``. Returns
    ``("ws", ws_url, token)`` (agent) or ``("socket", path, None)`` (local mpv).
    A DB lookup must never raise into a connect — any error degrades to 'not configured'."""
    try:
        from .models import PlayoutHost

        host = PlayoutHost.get_active()
        if host is None:
            return None
        if host.kind == PlayoutHost.KIND_LOCAL_SOCKET:
            path = (host.socket_path or "").strip()
            return ("socket", path, None) if path else None
        base = (host.base_url or "").strip()
        return ("ws", build_ws_control_url(base), host.token or "") if base else None
    except Exception as e:  # noqa: BLE001 — never let a DB lookup break a connect
        logger.error("Failed to resolve the active playout host: %s", e)
        return None


def title_option(title):
    """The ``force-media-title`` per-file option for ``title``, in mpv's
    length-prefixed quoting (``%<bytes>%``) so a comma or ``=`` in a name cannot
    split the option list."""
    return f"force-media-title=%{len(title.encode())}%{title}"


class MPVController:
    """mpv over one of two JSON-IPC transports (chosen by the active host's kind):
    the agent WebSocket (WSMPV) or a local mpv Unix socket (SocketMPV). With no
    active host the controller stays cleanly disconnected."""

    def __init__(self):
        self.current_path = None
        self.restart_path = None
        self.restart_serial = 0
        self.event_handlers = {
            e: [] for e in ("pause", "file_end", "file_start", "playlist_change", "time_pos", "quit")
        }

        self.player = None
        # The _transport_config() this controller connected with (None until it
        # has), so the link keeper can tell when the active host has changed.
        self.transport = None
        self._connected = False
        self._connection_lock = threading.Lock()

        self._connect()

    def _connect(self):
        """Connect over the active host's transport. No host / failed handshake
        leaves the controller disconnected and callers degrade gracefully."""
        with self._connection_lock:
            # One WSMPV per controller lifetime: it self-heals its own socket, so
            # a second would mean duplicate observers and N-times event dispatch.
            if self.player is not None:
                return True
            config = _transport_config()
            if config is None:
                self._connected = False
                return False
            kind, target, token = config
            try:
                if kind == "socket":
                    self.player = SocketMPV(target, quit_callback=self._on_quit)
                else:
                    self.player = WSMPV(target, token=token, quit_callback=self._on_quit)
                logger.info("Connected to mpv via %s at %s", "local socket" if kind == "socket" else "agent WS", target)
                self._register_observers()
            except Exception:
                self.player = None
                self._connected = False
                return False
            self._connected = True
            self.transport = config
            return True

    def _on_quit(self):
        """The mpv link dropped. WSMPV reconnects and re-subscribes itself, so we
        keep _connected True — flipping it False would spawn a second WSMPV (churn + dup observers)."""
        logger.info("MPV link dropped; WSMPV will reconnect")
        self._dispatch_event("quit", None)

    def _register_observers(self):
        p = self.player
        try:
            # "chapter" has no handler, but is observed all the same.
            p.bind_property_observer("chapter", lambda _n, _v: None)
            p.bind_property_observer("pause", lambda _n, v: self._dispatch_event("pause", v))
            p.bind_property_observer("path", self._on_path_change)
            p.bind_property_observer("playlist-pos", self._on_value("playlist_change"))
            p.bind_property_observer("time-pos", self._on_value("time_pos"))
            p.bind_event("end-file", lambda data: self._dispatch_event("file_end", data))
            p.bind_event("playback-restart", self._on_playback_restart)
            logger.info("Registered all MPV event observers")
        except Exception as e:
            logger.error(f"Error registering observers: {e}")

    def _on_value(self, event_name):
        """An observer dispatching ``event_name`` for every non-None value."""

        def observer(_name, value):
            if value is not None:
                self._dispatch_event(event_name, value)

        return observer

    def _on_playback_restart(self, event_data=None):
        # mpv has a frame of the current file on screen (after a load or a seek).
        # Counted with the path it happened on, so a caller can wait for the
        # first frame of a new file (see MPVService._reveal).
        self.restart_path = self.current_path
        self.restart_serial += 1

    def _on_path_change(self, name, value):
        self.current_path = value
        if value is not None:
            self._dispatch_event("file_start", value)

    def _dispatch_event(self, event_name, value):
        for handler in self.event_handlers.get(event_name, ()):
            try:
                handler(value)
            except Exception as e:
                logger.error(f"Error in event handler for {event_name}: {e}")

    def add_event_handler(self, event_name, handler_function):
        if event_name not in self.event_handlers:
            logger.warning(f"Unknown event: {event_name}")
            return False
        self.event_handlers[event_name].append(handler_function)
        return True

    def _ensure_connected(self):
        """A WSMPV self-heals its own connection, so its mere presence is
        "connected"; a reconnecting one degrades commands until its socket is back."""
        if self.player is not None:
            return True
        return self._connect()

    def _mpv_command(self, command, *args):
        if not self._ensure_connected():
            return False

        try:
            self.player.command(command, *args)
            return True
        except Exception as e:
            # A failed command doesn't mean the link is dead — don't tear it down
            # (that churns a reconnect). WSMPV self-heals a real drop.
            logger.error(f"MPV command failed: {command} {args} - {e}")
            return False

    def play(self):
        return self.pause(False)

    def pause(self, pause=True):
        try:
            self.player.pause = pause
            return True
        except Exception as e:
            logger.error(f"Error setting pause: {e}")
            return False

    def load_file(self, filepath, replace=True, options="", title=None):
        """``options`` are mpv per-file options ("key=value,..."), passed with the
        playlist index argument that mpv 0.38 put before them. ``title`` names the
        file in the player's window title ("Trailer: …")."""
        if title:
            options = ",".join(o for o in (options, title_option(title)) if o)
        mode = "replace" if replace else "append"
        logger.info(f"Loading file: {filepath} (mode: {mode})")
        if options:
            return self._mpv_command("loadfile", filepath, mode, -1, options)
        return self._mpv_command("loadfile", filepath, mode)

    def enqueue_file(self, filepath, title=None):
        return self.load_file(filepath, replace=False, title=title)

    def next(self):
        if not self._ensure_connected():
            return False
        # playlist_pos is None on an idle mpv: treat that as "at the end".
        playlist = self.get_playlist() or []
        current_pos = self.get_property("playlist_pos")
        if current_pos is None or current_pos >= len(playlist) - 1:
            logger.warning(f"Already at end of playlist (pos {current_pos}, length {len(playlist)})")
            return False
        return self._mpv_command("playlist-next")

    def previous(self):
        return self._mpv_command("playlist-prev")

    def seek(self, position, reference="absolute"):
        return self._mpv_command("seek", position, reference)

    def seek_relative(self, seconds):
        return self.seek(seconds, reference="relative")

    def get_property(self, name):
        """Accepts dashed or underscore names: a dashed name would silently read
        back a plain Python attribute instead of asking MPV."""
        try:
            return getattr(self.player, name.replace("-", "_"))
        except Exception as e:
            logger.error(f"Error getting property {name}: {e}")
            return None

    def set_property(self, name, value, quiet=False):
        """Accepts dashed or underscore names (see get_property). ``quiet`` logs a
        failure at DEBUG, for best-effort cosmetic writes."""
        try:
            setattr(self.player, name.replace("-", "_"), value)
            return True
        except Exception as e:
            (logger.debug if quiet else logger.error)(f"Error setting property {name}: {e}")
            return False

    def set_audio_track(self, index):
        return self._mpv_command("set_property", "aid", index)

    def set_subtitle_track(self, index):
        return self._mpv_command("set_property", "sid", index)

    def enable_subtitles(self):
        return self._mpv_command("set_property", "sub-visibility", True)

    def playlist_jump(self, index):
        return self._mpv_command("set_property", "playlist-pos", index)

    @staticmethod
    def _num(value):
        """Coerce an MPV property to float or None: MPV reports unavailable numeric
        properties as the string 'none', which would otherwise flow in as a string."""
        if isinstance(value, bool) or value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def get_status(self):
        if not self._ensure_connected():
            return None
        n = self._num

        def prop(name):
            return getattr(self.player, name, None)

        try:
            pause = self.player.pause
            # Older and newer mpv name some of these differently: try both.
            time_pos = n(prop("time_pos"))
            if time_pos is None:
                time_pos = n(prop("playback_time"))
            duration = n(prop("duration"))
            if duration is None:
                duration = n(prop("length"))
            file_path = prop("stream_open_filename") or prop("path") or prop("filename")
            volume = n(prop("volume"))
            vp = prop("video_params") or {}
            video = {
                "width": n(vp.get("w")) or n(prop("width")),
                "height": n(vp.get("h")) or n(prop("height")),
                "aspect": n(vp.get("aspect")),
                **{k: vp.get(k) for k in ("pixelformat", "colormatrix", "colorlevels", "primaries", "gamma")},
                "fps": n(prop("container_fps")) or n(prop("estimated_vf_fps")),
                "codec": prop("video_codec"),
                "bitrate": n(prop("video_bitrate")),
                "hw_decoding": prop("hwdec_current"),
            }
            audio_codec = prop("audio_codec")
            ap = prop("audio_params")
            audio = {
                "codec": audio_codec,
                "channels": ap.get("channels") if ap else None,
                "samplerate": ap.get("samplerate") if ap else None,
                "bitrate": n(prop("audio_bitrate")),
            }
            return {
                "pause": pause,
                "playback_status": "paused" if pause else "playing",
                "file_path": file_path,
                "time": time_pos,
                "length": duration,
                "playlist_pos": prop("playlist_pos"),
                "volume": volume,
                "muted": prop("mute"),
                "speed": n(prop("speed")) or 1.0,
                "fullscreen": prop("fullscreen"),
                "panscan": n(prop("panscan")),
                "video": video,
                "audio": audio,
            }
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            return None

    def get_playlist(self):
        if not self._ensure_connected():
            return None
        try:
            return self.player.playlist
        except Exception as e:
            logger.error(f"Error getting playlist: {e}")
            return None

    def playlist_clear(self):
        """Clear every playlist entry but the current one."""
        return self._mpv_command("playlist-clear")

    def get_track_list(self):
        if not self._ensure_connected():
            return None
        try:
            tracks = self.player.track_list
            return {
                "video_tracks": [t for t in tracks if t["type"] == "video"],
                "audio_tracks": [t for t in tracks if t["type"] == "audio"],
                "sub_tracks": [t for t in tracks if t["type"] == "sub"],
            }
        except Exception as e:
            logger.error(f"Error getting track list: {e}")
            return None

    def terminate(self):
        with self._connection_lock:
            try:
                if self.player:
                    for handlers in self.event_handlers.values():
                        handlers.clear()
                    self.player.terminate()
                    time.sleep(0.1)

                logger.info("MPV controller terminated")
            except Exception as e:
                logger.error(f"Error terminating MPV controller: {e}")
            finally:
                self.player = None
                self._connected = False
