import logging
import os
import threading
import time

from . import playout_timing
from .models import (
    Bumper,
    Command,
    MoviePlayback,
    Playlist,
    PlaylistItem,
    PlayoutSession,
    Settings,
)
from .mpv_controller import MPVController
from .utils.assets import system_ident_path, system_ident_stream_url

logger = logging.getLogger(__name__)


class ProgrammeState:
    """Programme lifecycle states"""

    NOT_LOADED = "not_loaded"
    LOADED = "loaded"  # Programme loaded but not started
    RUNNING = "running"  # Programme actively running
    PAUSED = "paused"  # Programme paused by user
    COMPLETED = "completed"  # Programme finished
    ERROR = "error"  # Programme encountered error


# Expected lifecycle transitions. Anything outside this map is logged as a
# warning (not rejected): MPV events can arrive in surprising orders and a
# hard failure here would wedge playout.
VALID_TRANSITIONS = {
    ProgrammeState.NOT_LOADED: {ProgrammeState.LOADED, ProgrammeState.ERROR},
    ProgrammeState.LOADED: {ProgrammeState.RUNNING, ProgrammeState.NOT_LOADED, ProgrammeState.ERROR},
    ProgrammeState.RUNNING: {
        ProgrammeState.PAUSED,
        ProgrammeState.COMPLETED,
        ProgrammeState.NOT_LOADED,
        ProgrammeState.ERROR,
    },
    ProgrammeState.PAUSED: {ProgrammeState.RUNNING, ProgrammeState.NOT_LOADED, ProgrammeState.ERROR},
    ProgrammeState.COMPLETED: {ProgrammeState.LOADED, ProgrammeState.NOT_LOADED, ProgrammeState.ERROR},
    ProgrammeState.ERROR: {ProgrammeState.NOT_LOADED, ProgrammeState.LOADED},
}


class MPVService:
    """Service to manage MPV instances and handle programme playback"""

    def __init__(self):
        """Initialize MPV service with lazy loading"""
        self.controller = None
        self.current_programme = None
        self.current_playlist = None
        self.playlist_offset = 0
        self.programme_state = ProgrammeState.NOT_LOADED
        self._lazy_initialized = False
        self._session_restored = False

        # Serialises load/start so a schedule-runner tick and a concurrent
        # manual load/run can't interleave mid-load and leave a torn
        # current_programme / playlist_offset (which would break the strict
        # mpv_index = playlist_offset + order invariant). RLock so the guarded
        # methods can call each other without self-deadlock.
        self._playout_lock = threading.RLock()

        # Serialises connection setup. Both runserver and gunicorn are
        # multi-threaded, so concurrent status polls can race the lazy connect on
        # the first hit; without this each thread would build its own
        # MPVController, and because a WSMPV self-heals its socket the orphaned
        # ones never die — they keep firing duplicate events (and duplicate
        # advances, which skip items). Guards _ensure_connected's connect path.
        self._connect_lock = threading.Lock()

        # Track audio/subtitle settings per programme block
        self.audio_set = {}
        self.subtitle_set = {}

        # Track credits command execution per playlist item
        self.credits_executed = {}

        # Last programme item order reached; command cues fire when the
        # cursor moves forward past them. -1 = still in pre-show.
        self._programme_cursor = -1

        # True while a hold-black command item is on screen (surfaced in status)
        self._executing_command = False
        self._hold_progress = None  # {'duration','elapsed'} while a hold-black command runs

        # Live playback cache, updated from the mpv property observers so the SSE
        # status stream (and its poll fallback) can build a snapshot with no
        # per-request mpv round-trips. See services/playout_events.py.
        self._live = {"time": None, "duration": None, "pause": None, "playlist_pos": None, "file": None}

        # Don't auto-connect - use lazy initialization instead

    @property
    def executing_command(self) -> bool:
        """True while a hold-black command item is holding the screen."""
        return self._executing_command

    def _set_state(self, new_state):
        """Move the programme lifecycle to ``new_state``, warning on unexpected jumps."""
        current = self.programme_state
        if new_state != current and new_state not in VALID_TRANSITIONS.get(current, set()):
            logger.warning(f"Unexpected programme state transition: {current} -> {new_state}")
        self.programme_state = new_state
        self._persist_session()
        self._notify_live()  # push the programme-state change to the SSE stream

    def _persist_session(self):
        """Snapshot the lifecycle to the DB so a restarted process can re-attach.

        Never allowed to break playback: DB errors are logged and swallowed.
        """
        try:
            session = PlayoutSession.load()
            session.state = self.programme_state
            session.programme = self.current_programme if self.programme_state != ProgrammeState.NOT_LOADED else None
            session.playlist_offset = self.playlist_offset
            session.programme_cursor = self._programme_cursor
            session.credits_executed = sorted(self.credits_executed.keys())
            session.save()
        except Exception:
            logger.exception("Failed to persist playout session")

    def _restore_session(self):
        """
        Re-attach to a screening after a process restart.

        MPV keeps playing across Django restarts; if the persisted session says
        a programme was loaded/running and MPV still has a playlist, restore the
        in-memory lifecycle instead of reporting "no programme loaded".
        """
        if self._session_restored:
            return
        self._session_restored = True
        try:
            session = PlayoutSession.load()
            if session.state == ProgrammeState.NOT_LOADED or not session.programme_id:
                return

            mpv_playlist = self.controller.get_playlist() if self.controller else []
            if not mpv_playlist or len(mpv_playlist) <= session.playlist_offset:
                # MPV was restarted too (or playlist gone) — session is stale
                logger.info("Persisted playout session is stale (MPV has no matching playlist); clearing")
                session.state = ProgrammeState.NOT_LOADED
                session.programme = None
                session.save()
                return

            playlist = Playlist.objects.filter(programme_id=session.programme_id).first()
            if playlist is None:
                logger.info("Persisted playout session references a missing playlist; clearing")
                session.state = ProgrammeState.NOT_LOADED
                session.programme = None
                session.save()
                return

            self.current_programme = session.programme
            self.current_playlist = playlist
            self.playlist_offset = session.playlist_offset
            self._programme_cursor = session.programme_cursor
            self.programme_state = session.state
            self.credits_executed = dict.fromkeys(session.credits_executed, True)
            self._build_track_maps()
            # A hold-black item may have set loop-file before the restart; its
            # watcher thread died with the old process, so clear the loop or
            # the black clip repeats forever.
            self.controller.set_property("loop-file", "no")
            logger.info(
                f"Re-attached to playout session: '{session.programme.name}' "
                f"({session.state}, offset {session.playlist_offset})"
            )
        except Exception:
            logger.exception("Failed to restore playout session")

    @property
    def running(self):
        """True while the programme lifecycle is RUNNING (read-only, derived from programme_state)."""
        return self.programme_state == ProgrammeState.RUNNING

    def unload_for_host_switch(self):
        """The active playout host changed: stop/clear any loaded programme and
        drop the control link so the next connect targets the new host's agent.

        reset() runs against the *old* controller (still connected to the old
        host), so it leaves that host idle on its ident and persists the session
        as NOT_LOADED. We then tear the controller down; ``_ensure_connected``
        rebuilds it against the newly-active host. Best-effort throughout — a
        wedged or unreachable old host must not block the switch."""
        try:
            if self.controller is not None and getattr(self.controller, "_connected", False):
                self.reset()
        except Exception:  # noqa: BLE001 — never let the old host block a switch
            logger.debug("reset during host switch failed", exc_info=True)
        if self.controller is not None:
            try:
                self.controller.terminate()
            except Exception:  # noqa: BLE001
                logger.debug("controller terminate during host switch failed", exc_info=True)
        self.controller = None
        self._lazy_initialized = False
        self._session_restored = False
        self.current_programme = None
        self.current_playlist = None
        self.playlist_offset = 0
        self.programme_state = ProgrammeState.NOT_LOADED
        self._persist_session()

    def _connect(self):
        """Connect to MPV over the active playout host's agent WebSocket.

        Idempotent: tears down any existing controller first. A WSMPV reconnects
        its own socket, so a controller that is merely dereferenced keeps its
        agent link alive and keeps dispatching events into this singleton
        (duplicate logs + duplicate advances). Only ever called under
        _connect_lock, so the teardown can't race a concurrent connect.
        """
        try:
            if self.controller is not None:
                try:
                    self.controller.terminate()
                except Exception:  # noqa: BLE001 — best effort; never block a reconnect
                    logger.debug("terminate of previous controller failed", exc_info=True)
                self.controller = None

            self.controller = MPVController()

            # The controller doesn't raise when MPV isn't running (it degrades to
            # a disconnected state, logged once by the controller) — so treat a
            # non-connected controller as a failed connect rather than reporting
            # "connected" and holding a dead controller.
            if not getattr(self.controller, "_connected", False):
                self.controller = None
                return False

            # Register event handlers
            self.controller.add_event_handler("file_end", self._handle_file_end)
            self.controller.add_event_handler("file_start", self._handle_file_start)
            self.controller.add_event_handler("playlist_change", self._handle_playlist_change)
            self.controller.add_event_handler("idle", self._handle_idle)
            self.controller.add_event_handler("time_pos", self._handle_time_pos)
            self.controller.add_event_handler("pause", self._handle_pause)

            # Apply the room's subtitle style now that we're connected. Purely
            # cosmetic — never let it break the connection.
            self.apply_subtitle_style()

            logger.info("MPV service connected")
            return True
        except Exception as e:
            logger.error(f"Failed to connect MPV service: {e}")
            self.controller = None
            return False

    # mpv border-style enum for each Cinefin subtitle style.
    _SUB_BORDER_STYLES = {
        "outline-and-shadow": "outline-and-shadow",
        "opaque-box": "opaque-box",
        "background-box": "background-box",
    }

    def apply_subtitle_style(self):
        """Apply the room's subtitle style (Settings → playout.subtitles) to the
        live player via set_property — no restart. Cosmetic and best-effort: a
        disconnected player or a bad value is swallowed. Per-block subtitle
        *track* selection is unaffected."""
        if not self.controller or not getattr(self.controller, "_connected", False):
            return
        from cinefin.api.models import Settings

        s = Settings.get("playout.subtitles") or {}
        props = {
            "sub-font-size": s.get("font_size", 55),
            "sub-color": s.get("color", "#FFFFFF"),
            "sub-border-style": self._SUB_BORDER_STYLES.get(s.get("border_style"), "outline-and-shadow"),
            "sub-back-color": s.get("back_color", "#000000"),
            "sub-pos": s.get("position", 100),
            "sub-margin-y": s.get("margin_y", 22),
            "sub-use-margins": "yes" if s.get("use_margins", True) else "no",
            "sub-bold": "yes" if s.get("bold", False) else "no",
        }
        # Cosmetic + best-effort: a property missing on the host's mpv version
        # (e.g. sub-margin-y on older builds) is harmless, so apply quietly —
        # set_property(quiet=True) logs a miss at DEBUG, not ERROR.
        for name, value in props.items():
            self.controller.set_property(name, value, quiet=True)

    def _ensure_connected(self):
        """Ensure MPV connection is active with lazy initialization"""
        just_connected = False
        # Double-checked under _connect_lock so only one thread ever builds the
        # controller — concurrent callers that lose the race reuse it rather than
        # spawning duplicate, self-healing controllers (see _connect_lock).
        if not self._lazy_initialized or not self.controller:
            with self._connect_lock:
                if not self._lazy_initialized or not self.controller:
                    if not self._lazy_initialized:
                        logger.info("Lazy initializing MPV service...")
                    self._lazy_initialized = True
                    if not self._connect():
                        return False
                    just_connected = True
        self._restore_session()
        # On a fresh connect with nothing loaded, put the System Ident on screen
        # so the idle splash isn't blank — this is what makes a local mpv the
        # operator started with `--idle` show the ident the moment we connect,
        # matching the agent. Guarded to idle only, and run AFTER restore so a
        # re-attached running programme is never clobbered.
        if just_connected and self.programme_state == ProgrammeState.NOT_LOADED:
            try:
                self._load_ident_paused()
            except Exception:
                logger.debug("Idle-ident load on connect failed", exc_info=True)
        return True

    def _resolve_ident_stream(self):
        """The stream URL of the ident to idle on, and a label for the log.

        A user media item chosen in Settings -> Playout wins; otherwise the
        bundled System Ident does, so a fresh install idles on something rather
        than on black. Returns ``(url, label)``, never ``(None, ...)`` unless the
        bundled asset itself is missing."""
        ident_id = Settings.get("cinema.default_ident_id")
        if ident_id:
            try:
                ident = Bumper.objects.get(id=ident_id)
            except Bumper.DoesNotExist:
                logger.warning("Default ident id %s not found; falling back to the System Ident", ident_id)
            else:
                stream_url = (ident.get_stream_url() or {}).get("stream_url")
                if stream_url:
                    return stream_url, ident.title
                logger.warning(
                    "Ident '%s' has no stream URL; falling back to the System Ident",
                    ident.title,
                )

        if not os.path.exists(system_ident_path()):
            logger.warning("Bundled System Ident is missing from the assets dir")
            return None, ""
        return system_ident_stream_url(), "System Ident"

    def _load_ident_paused(self):
        """Load the ident and pause on it — the shared "back to the idle screen"
        step used by reset() and the end-of-programme handler.

        The ident is *streamed* from Django: the playout host is remote and
        streaming-only, so the bumper's local ``file_path`` is meaningless there —
        always load the stream URL, never the path. Returns True when an ident was
        loaded, False when none is usable (the caller then pauses on black)."""
        stream_url, label = self._resolve_ident_stream()
        if not stream_url:
            return False
        # loadfile replace makes the ident the whole playlist; pause holds it as
        # the idle splash.
        self.controller.load_file(stream_url, replace=True)
        self.controller.pause()
        logger.info("Reset to ident (streamed): %s", label)
        return True

    def show_idle(self):
        """Best-effort: put the paused idle ident on screen if nothing is loaded.

        Called when a player (re)connects — a host is activated or mpv starts —
        so the screen shows the ident immediately instead of waiting for the
        next status poll. Never clobbers a loaded/running programme, and never
        raises: a wedged or absent player just leaves the screen as it was."""
        try:
            if self.programme_state != ProgrammeState.NOT_LOADED:
                return False
            if not self._ensure_connected():
                return False
            return self._load_ident_paused()
        except Exception:  # noqa: BLE001 — a background nudge must never surface
            logger.debug("show_idle failed", exc_info=True)
            return False

    def reset(self):
        """Clear programme state and return to the paused System Ident."""
        logger.info("Resetting MPV state")

        if not self._ensure_connected():
            return False

        self._programme_cursor = -1
        self._set_state(ProgrammeState.NOT_LOADED)
        self.current_programme = None
        self.current_playlist = None
        self.credits_executed.clear()

        if not self._load_ident_paused():
            # Nothing usable (the bundled asset is missing too) — clear the
            # playlist and pause on black.
            self.controller.playlist_clear()
            self.controller.pause()
        return True

    def _build_track_maps(self):
        """(Re)build the per-movie audio/subtitle bookkeeping from the playlist."""
        self.audio_set.clear()
        self.subtitle_set.clear()
        for item in self.current_playlist.items.all():
            if item.content_type == "movie":
                movie_playback = item.content_object
                if movie_playback is None:
                    # Wrapper was deleted (movie removed from library) —
                    # skip; playback falls back to the stored file path.
                    logger.warning(f"Playlist item {item.id} has no MoviePlayback; skipping track setup")
                    continue
                self.audio_set[movie_playback.id] = False
                self.subtitle_set[movie_playback.id] = False

    def load_programme(self, programme):
        """Load a programme for playback, first resetting to ensure clean state"""
        logger.info(f"Loading programme: {programme.name}")

        if not self._ensure_connected():
            return False

        with self._playout_lock:
            try:
                # An empty programme (no resolvable items) would leave MPV looping
                # the ident forever with no way to complete — refuse it up front,
                # before touching any state, so the caller gets a clean failure.
                playlist = Playlist.objects.get(programme=programme)
                item_count = playlist.items.count()
                if item_count == 0:
                    logger.error(f"Programme '{programme.name}' has an empty playlist; refusing to load")
                    return False

                # The opening item (position 0) is the programme's generated
                # title card if it has one, else the System Ident. Both are
                # streamed from Django — the player is remote, so a local path
                # wouldn't resolve on the host.
                title_stream_url = (
                    programme.get_title_stream_url() if hasattr(programme, "get_title_stream_url") else None
                )

                if title_stream_url:
                    logger.info(f"Loading programme title (streamed): {programme.name}")
                    self.controller.load_file(title_stream_url, replace=True)
                    self.controller.pause()
                else:
                    # No title configured, reset to load the System Ident
                    logger.info("No programme title configured, loading the System Ident")
                    self.reset()

                # Set programme and get playlist
                self.current_programme = programme
                self.current_playlist = playlist
                self._programme_cursor = -1
                self._set_state(ProgrammeState.LOADED)

                # Initialize track settings for movie blocks
                self.credits_executed.clear()
                self._build_track_maps()

                # Store the current MPV playlist length to calculate offsets
                # The title/ident is at position 0, so programme items start at position 1
                current_mpv_length = len(self.controller.get_playlist() or [])
                self.playlist_offset = current_mpv_length
                logger.debug(
                    f"Current MPV playlist length: {current_mpv_length}, playlist offset: {self.playlist_offset}"
                )
                logger.debug(f"Programme will start at MPV playlist index: {self.playlist_offset}")

                # Append all programme files to the existing MPV playlist. Every
                # item MUST land in MPV's playlist: the DB playlist is 1:1 with
                # MPV's (mpv_index = playlist_offset + order), so a dropped
                # append would silently misalign every later item's cues, audio
                # and credits markers. If an append fails (socket dropped), abort
                # the whole load rather than run a misaligned show.
                for idx, item in enumerate(playlist.items.order_by("order")):
                    if not self.controller.enqueue_file(item.file):
                        logger.error(
                            f"Failed to enqueue item at order {idx} ({item.file}); "
                            f"aborting load to preserve playlist alignment"
                        )
                        self.reset()
                        self._set_state(ProgrammeState.NOT_LOADED)
                        self.current_programme = None
                        self.current_playlist = None
                        return False
                    mpv_index = self.playlist_offset + idx
                    logger.debug(f"Enqueued at MPV index {mpv_index}: {item.file} ({item.content_type})")

                logger.info(f"Programme loaded: {item_count} items appended to playlist")
                self._persist_session()  # capture the final playlist_offset
                return True

            except Playlist.DoesNotExist:
                logger.error(f"No playlist found for programme: {programme.name}")
                return False
            except Exception as e:
                logger.error(f"Error loading programme: {e}")
                return False

    def start_programme(self, preshow: bool = False):
        """Start programme playback"""
        with self._playout_lock:
            if not self.current_programme or not self.current_playlist:
                logger.error("No programme loaded")
                return False

            logger.info(f"Starting programme playback: {self.current_programme.name}")

            # Log current playlist state for debugging
            current_pos = self.controller.get_property("playlist_pos") if self.controller else None
            mpv_playlist = self.controller.get_playlist() if self.controller else []
            logger.debug(f"Current MPV position: {current_pos}, playlist length: {len(mpv_playlist)}")
            logger.debug(
                f"Programme offset: {self.playlist_offset}, first programme item at MPV index: {self.playlist_offset}"
            )

            self._set_state(ProgrammeState.RUNNING)

            # Fire the configured pre-show commands (Settings → Scheduler) only
            # when the schedule runner starts the show — a manual run from the
            # remote/dashboard is an operator poking at playback, not the start
            # of a screening. Sequential, on a background thread, so a slow
            # command never delays the show; failures are logged and swallowed
            # inside _run_preshow_commands (a broken lighting/projector command
            # must never stop the feature from playing).
            if preshow:
                self._run_preshow_commands()

            # Start playback from current position
            # If we're at position 0 (the System Ident), let it play in full
            if current_pos == 0 and self.playlist_offset == 1:
                logger.info("Starting programme with the System Ident")

            return self.controller.play()

    def stop_programme(self):
        """Stop programme playback"""
        logger.info("Stopping programme playback")
        self._set_state(ProgrammeState.PAUSED)

        return self.controller.pause()

    def _handle_file_end(self, event_data):
        """Handle when a file ends"""
        if not self.running or not self.current_playlist:
            return

        reason = event_data.get("reason", "") if event_data else ""
        logger.debug(f"File ended: {reason}")

        if reason == "error":
            # A file/stream failed to open or dropped mid-playback (HTTP stream
            # gone, transcode died, local file vanished). MPV advances the
            # playlist itself, but at DEBUG this is indistinguishable from a
            # normal eof and buries a real fault. Surface it at WARNING against
            # the item that failed, then run the same bookkeeping as a normal
            # end so the programme keeps moving instead of wedging.
            self._log_playback_error()
            self._handle_playlist_item_end()
        elif reason in ["eof", "stop"]:
            self._handle_playlist_item_end()

    def _log_playback_error(self):
        """Emit a WARNING naming the playlist item MPV failed to play, if known."""
        try:
            pos = self.controller.get_property("playlist_pos") if self.controller else None
            if pos is None:
                logger.warning("MPV reported a playback error (file failed to open or dropped)")
                return
            order = pos - self.playlist_offset
            item = self.current_playlist.items.filter(order=order).first() if order >= 0 else None
            if item is not None:
                logger.warning(
                    f"MPV playback error on '{item.file}' ({item.content_type}, order {order}); "
                    f"advancing to the next item"
                )
            else:
                logger.warning(f"MPV playback error at playlist position {pos}; advancing")
        except Exception:
            logger.warning("MPV reported a playback error (details unavailable)")

    @staticmethod
    def _is_black_clip(filepath):
        """True if a file/URL is the system black clip — the streamed URL
        (/stream/system/black/) or, defensively, a legacy local path."""
        return bool(filepath) and ("/stream/system/black" in filepath or "system/black.mp4" in filepath)

    def _is_end_sentinel_position(self):
        """
        True when MPV is on the trailing "system" black item (programme end).

        Command items play the same system/black.mp4 placeholder in local mode,
        so the file path alone can't identify the end of the programme — the
        current playlist item's content_type can.
        """
        try:
            pos = self.controller.get_property("playlist_pos") if self.controller else None
            if pos is None or not self.current_playlist:
                return True  # can't tell — fall back to the old path-based behaviour
            programme_pos = pos - self.playlist_offset
            if programme_pos < 0:
                return False  # still in pre-show
            item = self.current_playlist.items.filter(order=programme_pos).first()
            return item is None or item.content_type == "system"
        except Exception:
            logger.exception("Failed to resolve playlist position for black.mp4 disambiguation")
            return True

    def _handle_file_start(self, filepath):
        """Handle when a file starts"""
        logger.info(f"File started: {filepath}")

        # New file → cache it and clear the stale duration (refetched lazily on
        # the next time-pos), then push the stream.
        self._live["file"] = filepath
        self._live["duration"] = None
        self._notify_live()

        # Black video at end of programme - reset to ident. The black clip is
        # streamed (/stream/system/black/) now that the player is remote;
        # interior hold-black command items play the same clip, so confirm it's
        # really the end sentinel via the playlist item's content_type.
        if filepath and self._is_black_clip(filepath) and self.running and self._is_end_sentinel_position():
            logger.info("Programme ended — resetting to the System Ident")

            self._programme_cursor = -1
            self._set_state(ProgrammeState.COMPLETED)
            self.current_programme = None
            self.current_playlist = None
            self.credits_executed.clear()
            self._persist_session()  # completed: clear the programme reference too

            # Same streamed-ident reset as reset(): loadfile-replace swaps the
            # end-sentinel black clip for the ident. (The old path appended the
            # bumper's LOCAL file_path — meaningless on the remote host, so the
            # programme ended on black instead of the ident.)
            if not self._load_ident_paused():
                self.controller.pause()  # no ident configured — hold on black
            return

        if not self.current_playlist:
            return

        # Configure tracks for movies
        threading.Thread(target=self._configure_tracks_for_file, args=(filepath,), daemon=True).start()

    def _handle_playlist_change(self, position):
        """
        Handle playlist position changes: advance the programme cursor, fire
        any command cues passed over, and run hold-black command items.

        Cue policy: moving forward fires every cue between the old and new
        cursor, in order — a jump that skips items still fires their cues.
        Moving backward fires nothing (the cues re-fire when playback passes
        them again).
        """
        self._live["playlist_pos"] = position
        self._notify_live()  # discrete change → push the stream immediately
        if not self.running or not self.current_playlist:
            return

        logger.debug(f"Playlist position changed to {position}")

        if position is None or position < self.playlist_offset:
            return
        programme_item_order = position - self.playlist_offset

        previous_order = self._programme_cursor
        self._programme_cursor = programme_item_order
        self._persist_session()

        try:
            window = playout_timing.cue_window(previous_order, programme_item_order)
            if window:
                self._fire_cues_between(*window)

            item = self.current_playlist.items.filter(order=programme_item_order).first()
            if item is None:
                logger.warning(f"Playlist item not found for programme order {programme_item_order}")
                return
            logger.debug(f"MPV index {position} -> programme item order {programme_item_order} ({item.content_type})")

            if item.content_type == "command":
                # Hold-black item: fire its command and keep black on screen
                # for the command's duration (thread — never block the event
                # handler).
                threading.Thread(target=self._run_hold_item, args=(item, position), daemon=True).start()
        except Exception as e:
            logger.error(f"Error handling playlist position change: {e}")

    def _fire_cues_between(self, previous_order, new_order):
        """Fire instant command cues in (previous_order, new_order], in order."""
        cues = list(
            self.current_playlist.cues.filter(
                fires_before_order__gt=previous_order, fires_before_order__lte=new_order
            ).order_by("fires_before_order", "seq")
        )
        if not cues:
            return

        from cinefin.api.services import command_runner

        commands = []
        for cue in cues:
            if cue.command is None:
                logger.warning(f"Command cue '{cue.command_name}' points at a deleted command; skipping")
                continue
            commands.append(cue.command)
        if commands:
            logger.info(f"Firing {len(commands)} command cue(s) for items {previous_order + 1}..{new_order}")
            command_runner.execute_many_sequential(commands, trigger="block")

    def _run_hold_item(self, item, mpv_position):
        """
        Run a hold-black command item: fire the command, keep the black clip
        looping until the command has finished AND its duration has elapsed
        (pause-aware), then advance.

        The system black clip is only a few seconds long, so the loop-file
        setting is what actually holds the screen — Command.duration is a
        minimum dwell, not a cap: a command that outlives it keeps black up
        until it completes (providers time out at TIMEOUT_SECONDS, so this
        is bounded). A deleted command with no duration falls back to letting
        the black clip play out once at its natural length.
        """
        from django.db import close_old_connections

        from cinefin.api.services import command_runner

        command = item.command
        hold_seconds = float(command.duration or 0) if command else 0.0

        done = threading.Event()
        if command is not None:

            def _fire():
                try:
                    close_old_connections()
                    command_runner.execute(command, trigger="block", wait=True)
                finally:
                    done.set()

            threading.Thread(target=_fire, daemon=True, name=f"hold-cmd-{command.name[:24]}").start()
        else:
            logger.warning(f"Hold item {item.id} points at a deleted command; holding without firing")
            done.set()
            if hold_seconds <= 0:
                return

        self._executing_command = True
        # The dwell/overtime clock is pure (playout_timing.HoldDwell); this
        # loop only sleeps, gathers observations and acts on the verdict.
        # Overtime is the backstop for a runner thread that never signals.
        dwell = playout_timing.HoldDwell(hold_seconds, overtime=command_runner.TIMEOUT_SECONDS + 5.0)
        # Expose the hold's own clock: MPV reports the looping black clip's
        # few-second file length, so status surfaces would show "5s" for every
        # command. get_status() overrides position/duration from this.
        self._hold_progress = dwell.progress
        looped = self.controller.set_property("loop-file", "inf")
        try:
            while not dwell.satisfied(done.is_set()):
                time.sleep(0.25)
                verdict = dwell.tick(
                    0.25,
                    running=self.running,
                    on_item=self.controller.get_property("playlist_pos") == mpv_position,
                    paused=bool(self.controller.get_property("pause")),
                    command_done=done.is_set(),
                )
                self._hold_progress = dwell.progress
                if verdict == playout_timing.ABORT:
                    return  # programme stopped, or the operator moved on manually
                if verdict == playout_timing.TIMEOUT:
                    logger.warning(
                        f"Hold item {item.id}: command '{command.name}' still not finished "
                        f"after {dwell.duration + dwell.overtime:.0f}s; advancing anyway"
                    )
                    break
        finally:
            self._executing_command = False
            self._hold_progress = None
            if looped:
                self.controller.set_property("loop-file", "no")

        name = command.name if command else "<deleted>"
        # Only advance if MPV is still on THIS hold's entry. A failing stream
        # before adjacent holds makes MPV error-advance multiple times in
        # quick succession (native open + ytdl fallback each fire an error),
        # leaving a stale hold thread whose unconditional next() would cut the
        # NEXT hold short mid-dwell.
        if self.controller.get_property("playlist_pos") == mpv_position:
            logger.info(f"Hold complete ('{name}', {hold_seconds}s minimum), advancing")
            self.controller.next()
        else:
            logger.info(f"Hold '{name}' superseded (playback moved on); not advancing")

    def _run_preshow_commands(self):
        """Fire the configured pre-show commands (Settings → Scheduler) in order."""
        try:
            ids = [i for i in (Settings.get("scheduler.preshow_commands") or []) if isinstance(i, int)]
            if not ids:
                return
            by_id = {c.id: c for c in Command.objects.filter(id__in=ids)}
            missing = [i for i in ids if i not in by_id]
            if missing:
                logger.warning(f"Pre-show command(s) {missing} no longer exist; skipping")

            from cinefin.api.services import command_runner

            command_runner.execute_many_sequential([by_id[i] for i in ids if i in by_id], trigger="preshow")
        except Exception:
            logger.exception("Failed to start pre-show commands")

    def _handle_time_pos(self, time_pos):
        """Handle time position changes and check for credits markers"""
        # Cache for the SSE snapshot (the stream ticks position itself, so no
        # publish here). Duration isn't known until the file loads, so fetch it
        # once — lazily, on the first tick after a file start clears it.
        self._live["time"] = time_pos
        if self._live["duration"] is None and self.controller:
            d = self.controller.get_property("duration")
            if d not in (None, "none"):
                self._live["duration"] = d

        if not self.running or not self.current_playlist or time_pos is None:
            return

        try:
            # Get current playlist position
            current_pos = self.controller.get_property("playlist_pos")
            if current_pos is None or current_pos < self.playlist_offset:
                return

            programme_item_order = current_pos - self.playlist_offset

            # Get the playlist item
            item = self.current_playlist.items.get(order=programme_item_order)

            # Check if this is a movie and we haven't executed its credits command yet
            if item.content_type == "movie" and not self.credits_executed.get(item.id, False):
                movie_playback = item.content_object
                if isinstance(movie_playback, MoviePlayback):
                    movie = movie_playback.movie
                    credits_marker = movie.credits_marker
                    credits_command = movie_playback.credits_command

                    # Execute the command when playback reaches or passes the marker
                    if credits_command and playout_timing.credits_due(time_pos, credits_marker):
                        logger.info(
                            f"Credits marker reached at {int(time_pos)}s (marker: {credits_marker}s) "
                            f"for '{movie.title}'"
                        )
                        # Execute in a thread to avoid blocking
                        threading.Thread(
                            target=self._execute_credits_command, args=(credits_command,), daemon=True
                        ).start()
                        self.credits_executed[item.id] = True
                        self._persist_session()

        except PlaylistItem.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Error checking credits marker: {e}")

    def _handle_playlist_item_end(self):
        """Handle when a playlist item ends"""
        if not self.running or not self.current_playlist:
            return

        try:
            current_pos = self.controller.get_property("playlist_pos") or 0
            programme_item_order = current_pos - self.playlist_offset

            if programme_item_order >= 0:
                try:
                    item = self.current_playlist.items.get(order=programme_item_order)
                    logger.debug(f"Playlist item ended: {item.content_type} at programme order {programme_item_order}")

                    # Programme completion is now handled by the reset dummy file approach
                    # This ensures predictable programme endings when the reset command starts

                    # Commands are now executed when they start, not when they end
                    # This method can be used for other end-of-file logic if needed

                except PlaylistItem.DoesNotExist:
                    logger.warning(f"Playlist item not found for programme order {programme_item_order}")

        except Exception as e:
            logger.error(f"Error handling playlist item end: {e}")

    def _handle_idle(self, event_data):
        """Handle when MPV goes idle - should not happen with reset sequence in playlist"""
        logger.warning("MPV went idle unexpectedly")
        self._notify_live()

    def _handle_pause(self, paused):
        """Cache pause state (observed) and push the stream."""
        self._live["pause"] = paused
        self._notify_live()

    def _notify_live(self):
        """Wake the SSE playout stream(s) so they push the latest snapshot."""
        try:
            from cinefin.api.services.playout_events import playout_event_bus

            playout_event_bus.publish()
        except Exception:  # noqa: BLE001 — never let a notify break an event handler
            pass

    def _configure_tracks_for_file(self, filepath):
        """Configure audio and subtitle tracks for the current file"""
        if not self.current_playlist:
            return

        try:
            # Find the playlist item for this file
            for item in self.current_playlist.items.all():
                if item.file == filepath and item.content_type == "movie":
                    # content_object is a MoviePlayback instance, not a ProgrammeBlock
                    movie_playback = item.content_object
                    if movie_playback is None:
                        logger.warning(f"Playlist item {item.id} has no MoviePlayback; skipping track config")
                        continue
                    movie_id = movie_playback.id

                    # The one INFO line for this block; the per-track detail
                    # below is DEBUG-level chatter (10+ lines per movie start).
                    logger.info(
                        f"Configuring tracks for {filepath}: MoviePlayback ID {movie_id}, "
                        f"audio_track: {movie_playback.audio_track_index}, "
                        f"subtitle_track: {movie_playback.subtitle_track_index}"
                    )

                    # Small delay to ensure file is loaded
                    time.sleep(0.5)

                    # Get available tracks for debugging
                    tracks = self.controller.get_track_list()
                    if tracks:
                        logger.debug(f"Raw track list: {tracks}")
                        # Handle both dict and string formats
                        if isinstance(tracks, list) and len(tracks) > 0:
                            if isinstance(tracks[0], dict):
                                audio_tracks = [t for t in tracks if t.get("type") == "audio"]
                                subtitle_tracks = [t for t in tracks if t.get("type") == "sub"]
                                logger.debug(
                                    f"Available tracks - Audio: {len(audio_tracks)}, Subtitles: {len(subtitle_tracks)}"
                                )
                            else:
                                logger.debug(f"Track list contains {len(tracks)} items (non-dict format)")

                    # Set audio track
                    if not self.audio_set.get(movie_id, False) and movie_playback.audio_track_index is not None:
                        logger.debug(
                            f"Setting audio track {movie_playback.audio_track_index} for MoviePlayback {movie_id}"
                        )
                        # MPV uses 1-based indexing for tracks
                        # Note: audio_track_index 0 -> MPV track 1
                        mpv_audio_track = movie_playback.audio_track_index + 1
                        logger.debug(
                            f"Setting MPV audio track to {mpv_audio_track} (0-based index {movie_playback.audio_track_index})"
                        )
                        result = self.controller.set_audio_track(mpv_audio_track)
                        logger.debug(f"Audio track set result: {result}")
                        self.audio_set[movie_id] = True

                    # Set subtitle track
                    if not self.subtitle_set.get(movie_id, False):
                        # Always enable subtitle visibility so tracks can be changed later
                        self.controller.enable_subtitles()

                        if movie_playback.subtitle_track_index is not None:
                            logger.debug(
                                f"Setting subtitle track {movie_playback.subtitle_track_index} for MoviePlayback {movie_id}"
                            )
                            # MPV uses 1-based indexing for tracks
                            # Note: subtitle_track_index 0 -> MPV track 1
                            mpv_subtitle_track = movie_playback.subtitle_track_index + 1
                            logger.debug(
                                f"Setting MPV subtitle track to {mpv_subtitle_track} (0-based index {movie_playback.subtitle_track_index})"
                            )
                            result = self.controller.set_subtitle_track(mpv_subtitle_track)
                            logger.debug(f"Subtitle track set result: {result}")
                        else:
                            logger.debug(
                                "No subtitle track specified, setting to 0 (disabled) but keeping visibility enabled"
                            )
                            # Set subtitle track to 0 (no track) but keep visibility enabled
                            self.controller.set_subtitle_track(0)
                        self.subtitle_set[movie_id] = True
                    break

        except Exception as e:
            logger.error(f"Error configuring tracks for file {filepath}: {e}", exc_info=True)

    def _execute_credits_command(self, command):
        """Execute a credits command via the command runner (recorded in history)"""
        from cinefin.api.services import command_runner

        command_runner.execute(command, trigger="credits", wait=True)

    # Delegation methods for backward compatibility
    def play(self):
        """Start/resume playback"""
        if not self._ensure_connected():
            return False
        return self.controller.play()

    def pause(self):
        """Pause playback"""
        if not self._ensure_connected():
            return False
        return self.controller.pause()

    def toggle_pause(self):
        """Toggle pause state"""
        if not self._ensure_connected():
            return False
        return self.controller.toggle_pause()

    def stop(self):
        """Stop playback"""
        if not self._ensure_connected():
            return False
        return self.controller.stop()

    def next(self):
        """Go to next playlist item"""
        if not self._ensure_connected():
            return False
        return self.controller.next()

    def previous(self):
        """Go to previous playlist item"""
        if not self._ensure_connected():
            return False
        return self.controller.previous()

    def seek(self, position):
        """Seek to position"""
        if not self._ensure_connected():
            return False
        return self.controller.seek(position)

    def keypress(self, key):
        """Send keypress to MPV"""
        if not self._ensure_connected():
            return False
        return self.controller.keypress(key)

    def get_status(self):
        """Get current playback status"""
        if not self._ensure_connected():
            return None
        return self.controller.get_status()

    def get_enhanced_status(self):
        """Get enhanced status with both programme and playback states"""
        # Get basic MPV status
        mpv_status = self.get_status() if self._ensure_connected() else None

        # Calculate remaining time if position and duration are available
        position = mpv_status.get("time") if mpv_status else None  # Controller uses 'time', not 'time_pos'
        duration = mpv_status.get("length") if mpv_status else None  # Controller uses 'length', not 'duration'
        remaining = None
        if position is not None and duration is not None and duration > 0:
            remaining = max(0, duration - position)

        # Get current playlist position for debugging
        playlist_pos = mpv_status.get("playlist_pos") if mpv_status else None

        # Determine playback state
        playback_state = "disconnected"
        if mpv_status:
            # Use the playback_status from controller, or fall back to checking pause property
            if "playback_status" in mpv_status:
                playback_state = mpv_status["playback_status"]
            else:
                # Fallback: check pause property directly
                playback_state = "paused" if mpv_status.get("pause", False) else "playing"

        # Determine final programme state (check for pre-show)
        final_programme_state = self.programme_state
        if self.programme_state == ProgrammeState.RUNNING and self.in_preshow(mpv_status):
            final_programme_state = "pre_show"

        # While a hold-black command runs, MPV's clock describes the looping
        # black clip (a few seconds, restarting) — report the command's own
        # dwell instead so every surface shows real progress.
        hold = self._hold_progress
        if hold and hold.get("duration"):
            duration = hold["duration"]
            position = min(hold.get("elapsed", 0.0), duration)
            remaining = max(0, duration - position)

        # Build enhanced status response
        status = {
            "programme": {
                "state": final_programme_state,
                "loaded": self.current_programme is not None,
                "running": self.running,
                "name": self.current_programme.name if self.current_programme else None,
                "id": self.current_programme.id if self.current_programme else None,
                "can_start": self.programme_state == ProgrammeState.LOADED,
                "can_pause": self.programme_state == ProgrammeState.RUNNING,
                "can_stop": self.programme_state in [ProgrammeState.RUNNING, ProgrammeState.PAUSED],
            },
            "playback": {
                "state": playback_state,
                "position": position,
                "duration": duration,
                "remaining": remaining,
                "playlist_pos": playlist_pos,
                "playlist_offset": self.playlist_offset if self.current_playlist else None,
            },
            "playlist": None,
            "debug": {
                "executing_command": self._executing_command,
                "mpv_playlist_length": len(self.controller.get_playlist())
                if self.controller and self.controller.get_playlist()
                else 0,
            },
        }

        # Add playlist information if available
        if self.current_playlist:
            current_item = None
            current_file = None
            programme_item_order = None  # unset when MPV has no position (disconnected)

            if mpv_status and mpv_status.get("playlist_pos") is not None:
                mpv_pos = mpv_status["playlist_pos"]
                programme_item_order = mpv_pos - self.playlist_offset

                if programme_item_order >= 0:
                    try:
                        item = self.current_playlist.items.get(order=programme_item_order)
                        current_item = programme_item_order
                        current_file = item.file
                    except Exception:
                        pass

            status["playlist"] = {
                "total_items": self.current_playlist.items.count(),
                "current_item": current_item,
                "current_file": current_file,
                "programme_position": (
                    programme_item_order if programme_item_order is not None and programme_item_order >= 0 else None
                ),
            }

        return status

    def get_playlist(self):
        """Get current MPV playlist"""
        if not self._ensure_connected():
            return None
        return self.controller.get_playlist()

    def get_track_list(self):
        """Get available tracks"""
        if not self._ensure_connected():
            return None
        return self.controller.get_track_list()

    # Backward compatibility properties
    @property
    def connector(self):
        """Backward compatibility: return controller as connector"""
        return self.controller

    @property
    def mpv_index(self):
        """Backward compatibility: get playlist index"""
        if self.controller:
            return self.controller.get_property("playlist_pos") or 0
        return 0

    @property
    def playlist_index(self):
        """Backward compatibility: get playlist index"""
        return self.mpv_index

    @property
    def programme(self):
        """Backward compatibility: get current programme"""
        return self.current_programme

    @property
    def playlist(self):
        """Backward compatibility: get current playlist"""
        return self.current_playlist

    def load_file(self, filepath, replace=True):
        """Load a file for playback"""
        if not self._ensure_connected():
            return False
        return self.controller.load_file(filepath, replace)

    def enqueue_file(self, filepath):
        """Add file to playlist"""
        if not self._ensure_connected():
            return False
        return self.controller.enqueue_file(filepath)

    def set_audio_track(self, index):
        """Set audio track by index"""
        if not self._ensure_connected():
            return False
        return self.controller.set_audio_track(index)

    def set_subtitle_track(self, index):
        """Set subtitle track by index"""
        if not self._ensure_connected():
            return False
        return self.controller.set_subtitle_track(index)

    def enable_subtitles(self):
        """Enable subtitle visibility"""
        if not self._ensure_connected():
            return False
        return self.controller.enable_subtitles()

    def disable_subtitles(self):
        """Disable subtitle visibility"""
        if not self._ensure_connected():
            return False
        return self.controller.disable_subtitles()

    # Volume control methods
    def set_volume(self, volume):
        """Set volume level (0-100)"""
        if not self._ensure_connected():
            return False
        return self.controller.set_volume(volume)

    def volume_up(self):
        """Increase volume"""
        if not self._ensure_connected():
            return False
        return self.controller.volume_up()

    def volume_down(self):
        """Decrease volume"""
        if not self._ensure_connected():
            return False
        return self.controller.volume_down()

    def mute(self):
        """Mute audio"""
        if not self._ensure_connected():
            return False
        return self.controller.mute()

    def unmute(self):
        """Unmute audio"""
        if not self._ensure_connected():
            return False
        return self.controller.unmute()

    def toggle_mute(self):
        """Toggle mute state"""
        if not self._ensure_connected():
            return False
        return self.controller.toggle_mute()

    # Advanced seeking methods
    def seek_relative(self, seconds):
        """Seek relative to current position"""
        if not self._ensure_connected():
            return False
        return self.controller.seek_relative(seconds)

    def seek_percentage(self, percent):
        """Seek to percentage of file"""
        if not self._ensure_connected():
            return False
        return self.controller.seek_percentage(percent)

    # Track selection methods
    def select_audio_track(self, track_id):
        """Select audio track by ID"""
        if not self._ensure_connected():
            return False
        return self.controller.select_audio_track(track_id)

    def select_subtitle_track(self, track_id):
        """Select subtitle track by ID"""
        if not self._ensure_connected():
            return False
        return self.controller.select_subtitle_track(track_id)

    # Playlist control methods
    def get_playlist_info(self):
        """Get detailed playlist information"""
        if not self._ensure_connected():
            return {"playlist": [], "current_index": 0, "total_items": 0, "programme_offset": 0}

        try:
            mpv_playlist = self.controller.get_playlist() or []
            current_index = self.controller.get_property("playlist_pos") or 0

            # Build playlist info with programme position mapping
            playlist_items = []
            for i, item in enumerate(mpv_playlist):
                # Pre-show entries (before the programme offset) are stream
                # URLs — the ident or the generated title card — so label them
                # rather than showing a URL fragment.
                if i < self.playlist_offset:
                    title = self._preshow_title(item.get("filename", ""))
                else:
                    title = self.getFileName(item.get("filename", "")) or f"Item {i + 1}"
                programme_position = None

                # Calculate programme position (excluding the System Ident)
                if i >= self.playlist_offset:
                    programme_position = i - self.playlist_offset

                playlist_items.append(
                    {
                        "index": i,
                        "title": title,
                        "type": self._guess_file_type(item.get("filename", "")),
                        "file": item.get("filename", ""),
                        "current": i == current_index,
                        "programme_position": programme_position,
                    }
                )

            return {
                "playlist": playlist_items,
                "current_index": current_index,
                "total_items": len(mpv_playlist),
                "programme_offset": self.playlist_offset,
            }
        except Exception as e:
            logger.error(f"Error getting playlist info: {e}")
            return {"playlist": [], "current_index": 0, "total_items": 0, "programme_offset": 0}

    def playlist_jump(self, index):
        """Jump to specific playlist item"""
        if not self._ensure_connected():
            return False
        return self.controller.playlist_jump(index)

    # Speed control methods
    def set_speed(self, speed):
        """Set playback speed"""
        if not self._ensure_connected():
            return False
        return self.controller.set_speed(speed)

    # Fullscreen control methods
    def toggle_fullscreen(self):
        """Toggle fullscreen mode"""
        if not self._ensure_connected():
            return False
        return self.controller.toggle_fullscreen()

    def set_fullscreen(self, enabled):
        """Set fullscreen state"""
        if not self._ensure_connected():
            return False
        return self.controller.set_fullscreen(enabled)

    # Chapter navigation methods
    def chapter_next(self):
        """Go to next chapter"""
        if not self._ensure_connected():
            return False
        return self.controller.chapter_next()

    def chapter_previous(self):
        """Go to previous chapter"""
        if not self._ensure_connected():
            return False
        return self.controller.chapter_previous()

    def chapter_seek(self, chapter_number):
        """Seek to specific chapter"""
        if not self._ensure_connected():
            return False
        return self.controller.chapter_seek(chapter_number)

    # Helper methods
    def getFileName(self, path):
        """
        Display-usable last path segment. Stream URLs end "/?t=<token>", so
        strip the query string and trailing slash first — a naive last-segment
        split surfaces the bare token ("?t=…") as a title.
        """
        if not path:
            return ""
        trimmed = path.split("?")[0].rstrip("/")
        return trimmed.split("/")[-1] or path

    def in_preshow(self, mpv_status=None) -> bool:
        """True while the opening item — the generated title card, else the System
        Ident — is on screen and the programme proper hasn't started.

        The test is *positional*: programme items occupy mpv indices
        ``playlist_offset + order``, so anything before the offset is pre-show.
        The previous test compared mpv's current file against the ident Bumper's
        local ``file_path``, which could never match (every playlist entry is a
        stream URL, and the host is remote) and ignored title cards entirely.
        """
        if not self.current_playlist or self.playlist_offset <= 0:
            return False
        if mpv_status is None:
            mpv_status = self.get_status() or {}
        position = mpv_status.get("playlist_pos")
        return position is not None and position < self.playlist_offset

    @staticmethod
    def _preshow_title(url):
        """Friendly label for a pre-show stream URL (System Ident / title card)."""
        path = (url or "").split("?")[0]
        if "/stream/title/" in path:
            return "Title card"
        if "/stream/system/black/" in path:
            return "Black"
        return "System Ident"

    def _guess_file_type(self, filename):
        """Guess file type from filename"""
        if not filename:
            return "unknown"

        ext = filename.lower().split(".")[-1] if "." in filename else ""

        if ext in ["mp4", "mkv", "avi", "mov", "wmv"]:
            if "trailer" in filename.lower():
                return "trailer"
            elif "bumper" in filename.lower() or "ident" in filename.lower():
                return "bumper"
            else:
                return "movie"
        elif ext in ["mp3", "wav", "flac"]:
            return "audio"
        else:
            return "video"

    @property
    def _connected(self):
        """Backward compatibility: get connection status"""
        return self.controller and self.controller._connected if self.controller else False

    def _mpv_command(self, command, *args):
        """Backward compatibility: execute MPV command"""
        if not self._ensure_connected():
            return False
        return self.controller._mpv_command(command, *args)

    def terminate(self):
        """Terminate the MPV service and cleanup resources"""
        logger.info("Terminating MPV service...")
        try:
            if self.controller:
                self.controller.terminate()
            self.controller = None
            self._lazy_initialized = False
            self._set_state(ProgrammeState.NOT_LOADED)
            logger.info("MPV service terminated")
        except Exception as e:
            logger.error(f"Error terminating MPV service: {e}")


# Singleton instance for use in Django
mpv_service = MPVService()
