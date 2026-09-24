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


class MPVController:
    """mpv over one of two JSON-IPC transports (chosen by the active host's kind):
    the agent WebSocket (WSMPV) or a local mpv Unix socket (SocketMPV). With no
    active host the controller stays cleanly disconnected."""

    def __init__(self):
        self.event_handlers = {
            "pause": [],
            "chapter_change": [],
            "file_end": [],
            "file_start": [],
            "track_change": [],
            "seek": [],
            "idle": [],
            "playlist_change": [],
            "time_pos": [],
        }

        self.player = None
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
            factory = (
                (lambda: SocketMPV(target, quit_callback=self._on_quit))
                if kind == "socket"
                else (lambda: WSMPV(target, token=token, quit_callback=self._on_quit))
            )
            return self._connect_player(factory, kind, target)

    def _connect_player(self, factory, kind, target):
        """Open the chosen transport. Caller holds _connection_lock. player is
        already None here (first connect or after teardown), so nothing leaks."""
        try:
            self.player = factory()
            logger.info("Connected to mpv via %s at %s", "local socket" if kind == "socket" else "agent WS", target)
            self._register_observers()
            self._connected = True
            return True
        except Exception:
            self.player = None
            self._connected = False
            return False

    def _on_quit(self):
        """The mpv link dropped. WSMPV reconnects and re-subscribes itself, so we
        keep _connected True — flipping it False would spawn a second WSMPV (churn + dup observers)."""
        logger.info("MPV link dropped; WSMPV will reconnect")
        self._dispatch_event("quit", None)

    def _register_observers(self):
        try:
            self.player.bind_property_observer("chapter", self._on_chapter_change)
            self.player.bind_property_observer("pause", self._on_pause_change)
            self.player.bind_property_observer("path", self._on_path_change)
            self.player.bind_property_observer("idle-active", self._on_idle_change)
            self.player.bind_property_observer("playlist-pos", self._on_playlist_pos_change)
            self.player.bind_property_observer("time-pos", self._on_time_pos_change)

            self.player.bind_event("end-file", self._on_end_file)
            self.player.bind_event("file-loaded", self._on_file_loaded)
            self.player.bind_event("start-file", self._on_start_file)
            self.player.bind_event("playlist-change", self._on_playlist_change)

            logger.info("Registered all MPV event observers")
        except Exception as e:
            logger.error(f"Error registering observers: {e}")

    def _on_chapter_change(self, name, value):
        if value is not None:
            logger.debug(f"Chapter changed to {value}")
            self._dispatch_event("chapter_change", value)

    def _on_pause_change(self, name, value):
        logger.debug(f"Pause state changed to {value}")
        self._dispatch_event("pause", value)

    def _on_path_change(self, name, value):
        if value is not None:
            logger.debug(f"File changed to {value}")
            self._dispatch_event("file_start", value)

    def _on_idle_change(self, name, value):
        if value:
            logger.debug("MPV entered idle state")
            self._dispatch_event("idle", None)

    def _on_playlist_pos_change(self, name, value):
        if value is not None:
            logger.debug(f"Playlist position changed to {value}")
            self._dispatch_event("playlist_change", value)

    def _on_time_pos_change(self, name, value):
        if value is not None:
            self._dispatch_event("time_pos", value)

    def _on_end_file(self, event_data):
        logger.debug(f"File ended with reason: {event_data.get('reason', 'unknown')}")
        self._dispatch_event("file_end", event_data)

    def _on_file_loaded(self, event_data):
        logger.debug(f"File loaded: {event_data}")

    def _on_start_file(self, event_data):
        filename = event_data.get("filename", "")
        logger.debug(f"Starting file: {filename}")

    def _on_playlist_change(self, event_data):
        logger.debug(f"Playlist changed: {event_data}")

    def _dispatch_event(self, event_name, value):
        if event_name in self.event_handlers:
            for handler in self.event_handlers[event_name]:
                try:
                    handler(value)
                except Exception as e:
                    logger.error(f"Error in event handler for {event_name}: {e}")

    def add_event_handler(self, event_name, handler_function):
        if event_name in self.event_handlers:
            self.event_handlers[event_name].append(handler_function)
            return True
        else:
            logger.warning(f"Unknown event: {event_name}")
            return False

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

    def play(self, filepath=None):
        try:
            if filepath:
                self.player.play(filepath)
            else:
                self.player.pause = False
            return True
        except Exception as e:
            logger.error(f"Error playing: {e}")
            return False

    def pause(self, pause=True):
        try:
            self.player.pause = pause
            return True
        except Exception as e:
            logger.error(f"Error setting pause: {e}")
            return False

    def toggle_pause(self):
        return self._mpv_command("cycle", "pause")

    def stop(self):
        try:
            self.player.command("stop")
            return True
        except Exception as e:
            logger.error(f"Error stopping playback: {e}")
            return False

    def load_file(self, filepath, replace=True):
        if not self._ensure_connected():
            return False

        mode = "replace" if replace else "append"
        logger.info(f"Loading file: {filepath} (mode: {mode})")
        return self._mpv_command("loadfile", filepath, mode)

    def enqueue_file(self, filepath):
        return self.load_file(filepath, replace=False)

    def next(self):
        if not self._ensure_connected():
            return False

        try:
            # Every attribute read is a live get_property, so playlist_pos can be
            # None (idle mpv) — treat None as "at the end" (else the comparison raises).
            playlist = self.get_playlist() or []
            current_pos = self.get_property("playlist_pos")

            if current_pos is None or current_pos >= len(playlist) - 1:
                logger.warning(f"Already at end of playlist (pos {current_pos}, length {len(playlist)})")
                return False

            return self._mpv_command("playlist-next")
        except Exception as e:
            logger.error(f"Error in next(): {e}")
            return False

    def previous(self):
        return self._mpv_command("playlist-prev")

    def seek(self, position, reference="absolute", percent=False):
        try:
            if percent:
                self.player.command("seek", position, reference + "-percent")
            else:
                self.player.command("seek", position, reference)
            return True
        except Exception as e:
            logger.error(f"Error seeking: {e}")
            return False

    def keypress(self, key):
        return self._mpv_command("keypress", key)

    def get_property(self, name):
        """Accepts dashed or underscore names — a dashed name would silently read
        back a plain Python attribute instead of asking MPV."""
        try:
            return getattr(self.player, name.replace("-", "_"))
        except Exception as e:
            logger.error(f"Error getting property {name}: {e}")
            return None

    def set_property(self, name, value, quiet=False):
        """Accepts dashed or underscore names (see get_property). quiet logs a
        failure at DEBUG — for best-effort cosmetic writes that shouldn't spam the log."""
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

    def disable_subtitles(self):
        return self._mpv_command("set_property", "sub-visibility", False)

    def seek_relative(self, seconds):
        return self.seek(seconds, reference="relative")

    def seek_percentage(self, percent):
        return self.seek(percent, reference="absolute", percent=True)

    def set_volume(self, volume):
        return self._mpv_command("set_property", "volume", volume)

    def volume_up(self):
        return self._mpv_command("add", "volume", 10)

    def volume_down(self):
        return self._mpv_command("add", "volume", -10)

    def mute(self):
        return self._mpv_command("set_property", "mute", True)

    def unmute(self):
        return self._mpv_command("set_property", "mute", False)

    def toggle_mute(self):
        return self._mpv_command("cycle", "mute")

    def select_audio_track(self, track_id):
        return self._mpv_command("set_property", "aid", track_id)

    def select_subtitle_track(self, track_id):
        return self._mpv_command("set_property", "sid", track_id)

    def playlist_jump(self, index):
        return self._mpv_command("set_property", "playlist-pos", index)

    def set_speed(self, speed):
        return self._mpv_command("set_property", "speed", speed)

    def toggle_fullscreen(self):
        return self._mpv_command("cycle", "fullscreen")

    def set_fullscreen(self, enabled):
        return self._mpv_command("set_property", "fullscreen", enabled)

    def chapter_next(self):
        return self._mpv_command("add", "chapter", 1)

    def chapter_previous(self):
        return self._mpv_command("add", "chapter", -1)

    def chapter_seek(self, chapter_number):
        return self._mpv_command("set_property", "chapter", chapter_number)

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

        try:
            pause = self.player.pause
            state = "paused" if pause else "playing"

            # Try alternate property names for compatibility
            time_pos = self._num(getattr(self.player, "time_pos", None))
            if time_pos is None:
                time_pos = self._num(getattr(self.player, "playback_time", None))

            duration = self._num(getattr(self.player, "duration", None))
            if duration is None:
                duration = self._num(getattr(self.player, "length", None))

            file_path = getattr(self.player, "stream_open_filename", None)
            if not file_path:
                file_path = getattr(self.player, "path", None)
            if not file_path:
                file_path = getattr(self.player, "filename", None)

            volume = self._num(getattr(self.player, "volume", None))

            video_params = getattr(self.player, "video_params", None) or {}

            video_info = {
                "width": self._num(video_params.get("w")) or self._num(getattr(self.player, "width", None)),
                "height": self._num(video_params.get("h")) or self._num(getattr(self.player, "height", None)),
                "aspect": self._num(video_params.get("aspect")),
                "pixelformat": video_params.get("pixelformat"),
                "colormatrix": video_params.get("colormatrix"),
                "colorlevels": video_params.get("colorlevels"),
                "primaries": video_params.get("primaries"),
                "gamma": video_params.get("gamma"),
                "fps": self._num(getattr(self.player, "container_fps", None))
                or self._num(getattr(self.player, "estimated_vf_fps", None)),
                "codec": getattr(self.player, "video_codec", None),
                "bitrate": self._num(getattr(self.player, "video_bitrate", None)),
                "hw_decoding": getattr(self.player, "hwdec_current", None),
            }

            audio_info = {
                "codec": getattr(self.player, "audio_codec", None),
                "channels": getattr(self.player, "audio_params", {}).get("channels")
                if getattr(self.player, "audio_params", None)
                else None,
                "samplerate": getattr(self.player, "audio_params", {}).get("samplerate")
                if getattr(self.player, "audio_params", None)
                else None,
                "bitrate": self._num(getattr(self.player, "audio_bitrate", None)),
            }

            return {
                "pause": pause,
                "playback_status": state,
                "file_path": file_path,
                "time": time_pos,
                "length": duration,
                "playlist_pos": getattr(self.player, "playlist_pos", None),
                "volume": volume,
                "muted": getattr(self.player, "mute", None),
                "speed": self._num(getattr(self.player, "speed", None)) or 1.0,
                "fullscreen": getattr(self.player, "fullscreen", None),
                "video": video_info,
                "audio": audio_info,
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
        """Clear all playlist items except the currently playing one"""
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
                    for event_type in self.event_handlers:
                        self.event_handlers[event_type].clear()

                    self.player.terminate()
                    time.sleep(0.1)

                logger.info("MPV controller terminated")
            except Exception as e:
                logger.error(f"Error terminating MPV controller: {e}")
            finally:
                self.player = None
                self._connected = False
