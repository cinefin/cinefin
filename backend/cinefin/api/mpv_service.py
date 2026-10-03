import logging
import re
import threading
import time

from . import playout_timing
from .exceptions import UnprocessableEntityError
from .models import MoviePlayback, Playlist, PlaylistItem, PlayoutHost, PlayoutSession
from .mpv_controller import MPVController
from .services import standby as standby_spec
from .utils.assets import system_black_stream_url

logger = logging.getLogger(__name__)

# What the player's window title says is playing ("Trailer: …"); the player
# appends its own name. Standby matches the playout agent's own "System Ident".
STANDBY_TITLE = "System Ident"
BLACK_TITLE = "Black"
_KIND_LABELS = {
    "movie": "Feature",
    "trailer": "Trailer",
    "bumper": "User Media",
    "media": "User Media",
    "command": "Command",
    "certification": "Certification",
    "url": "URL",
}


def _labelled(kind, name):
    label = _KIND_LABELS.get(kind)
    if not label:
        return name or None
    return f"{label}: {name}" if name else label


def item_title(item):
    """The window title for a playlist item: its kind and name, from the linked
    content, else what the playlist recorded when it was built."""
    kind, meta = item.content_type, item.metadata or {}
    if kind == "system":
        return BLACK_TITLE
    name = None
    if kind == "movie":
        movie = item.movie_playback.movie if item.movie_playback else None
        name = movie.title if movie else meta.get("movie_title")
    elif kind == "trailer":
        name = item.trailer.title if item.trailer else meta.get("trailer_title")
    elif kind == "bumper":
        name = item.bumper.title if item.bumper else meta.get("bumper_title")
    elif kind == "command":
        name = item.command.name if item.command else meta.get("command_name")
    elif kind == "certification":
        name = item.certification.certification if item.certification else None
    if not name and item.programme_block:
        name = item.programme_block.cached_title
    return _labelled(kind, name)


def manual_title(kind, title):
    """The window title for a manual-mode item."""
    return _labelled(kind, title)


# Standby loads its ident with per-file options after a playlist index argument,
# which mpv added in 0.38.
MIN_MPV_VERSION = (0, 38)
# How long load_programme waits for the player to report standby on screen.
STANDBY_WAIT_SECONDS = 5.0

# Leaving standby for a programme fades the picture to black, moves on, then
# reveals the next entry (see _leave_standby). The cover is a full-screen black
# ASS rectangle drawn with osd-overlay: id 2, since a playout agent relays our
# commands on its own mpv connection and draws its card as overlay 1, and a
# high z so the cover sits above that card.
COVER_OVERLAY_ID = 2
COVER_Z = 100
COVER_FADE_SECONDS = 0.8
COVER_REVEAL_SECONDS = 0.4
COVER_STEPS_PER_SECOND = 25
# How long the reveal waits for the next entry's first frame before lifting the cover anyway.
COVER_FIRST_FRAME_WAIT = 3.0


class ProgrammeState:
    """The programme lifecycle. Pause is mpv's own, and a finished programme goes
    straight to standby, so these three are all there is; the phase every surface
    shows is worked out from them in services/playout_service.py."""

    NOT_LOADED = "not_loaded"
    LOADED = "loaded"  # cued, not started
    RUNNING = "running"  # started


class MPVService:
    """Service to manage MPV instances and handle programme playback"""

    def __init__(self):
        """Initialize MPV service with lazy loading"""
        self.controller = None
        # The PlayoutHost the controller was connected to, and a problem with
        # its player worth showing in Settings (an mpv too old for standby).
        self._host = None
        self.player_warning = ""
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
        # Cued title card: its mpv index, when to pause into it (0 = first frame, else after the
        # fade-in) and whether it has started (armed by its file-start, so standby's clock can't trip it).
        self._title_index = None
        self._title_pause_at = None
        self._title_armed = False
        # Bumped by each fade off standby, so an older reveal never lifts a newer cover.
        self._cover_gen = 0

        # Live playback cache, updated from the mpv property observers so the SSE
        # status stream (and its poll fallback) can build a snapshot with no
        # per-request mpv round-trips. See services/playout_events.py.
        self._live = {"time": None, "duration": None, "pause": None, "playlist_pos": None, "file": None}

        # Manual mode: one-off items played outside any programme, 1:1 with MPV's
        # playlist ahead of a trailing black sentinel (whose start puts the
        # player on standby, as at a programme's end). Empty = not in manual mode.
        self.manual_items = []

        # Don't auto-connect - use lazy initialization instead

    @property
    def executing_command(self) -> bool:
        """True while a hold-black command item is holding the screen."""
        return self._executing_command

    def _set_state(self, new_state):
        """Move the programme lifecycle to ``new_state``, persist it and push the status."""
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
            if session.state not in (ProgrammeState.LOADED, ProgrammeState.RUNNING) or not session.programme_id:
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

        standby() runs against the *old* controller and host, so it leaves that
        host on standby and persists the session as NOT_LOADED. We then tear the controller down; ``_ensure_connected``
        rebuilds it against the newly-active host. Best-effort throughout — a
        wedged or unreachable old host must not block the switch."""
        try:
            if self.controller is not None and getattr(self.controller, "_connected", False):
                self.standby()
        except Exception:  # noqa: BLE001 — never let the old host block a switch
            logger.debug("standby during host switch failed", exc_info=True)
        if self.controller is not None:
            try:
                self.controller.terminate()
            except Exception:  # noqa: BLE001
                logger.debug("controller terminate during host switch failed", exc_info=True)
        self.controller = None
        self._host = None
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
            self._host = PlayoutHost.get_active()

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
            self.controller.add_event_handler("time_pos", self._handle_time_pos)
            self.controller.add_event_handler("pause", self._handle_pause)
            # A dropped link: push the status so every surface shows the player offline.
            self.controller.add_event_handler("quit", lambda _value: self._notify_live())

            self._check_mpv_version()
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

    def _check_mpv_version(self):
        """A local mpv must be 0.38 or newer for standby's per-file options (an
        agent's mpv is the player's business). Warns once per connect."""
        self.player_warning = ""
        if (self.controller.transport or ("",))[0] != "socket":
            return
        version = str(self.controller.get_property("mpv-version") or "")
        match = re.search(r"(\d+)\.(\d+)", version)
        if match and (int(match[1]), int(match[2])) < MIN_MPV_VERSION:
            self.player_warning = f"{version} is too old for standby: update mpv to 0.38 or newer"
            logger.warning("Local player: %s", self.player_warning)

    def _ensure_connected(self):
        """Ensure MPV connection is active with lazy initialization"""
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
        self._restore_session()
        return True

    def ensure_link(self):
        """Keep the control link to the active agent open (called by the playout
        link keeper, ``services/playout_link.py``). Returns False when the agent
        could not be reached, so the keeper backs off.

        A controller connected to a host that is no longer the active one (or
        with a stale token after re-pairing) is torn down first, the same way a
        host switch does it. Local-socket hosts are left to connect on demand."""
        from .mpv_controller import _transport_config

        want = _transport_config()
        if want is None or want[0] != "ws":
            return True
        controller = self.controller
        if controller is not None and getattr(controller, "transport", want) != want:
            logger.info("The active playout host changed; reconnecting")
            self.unload_for_host_switch()
        return self._ensure_connected()

    def idle(self) -> bool:
        """True when no programme is loaded and no manual queue plays."""
        return self.current_programme is None and not self.manual_items

    def _clear(self):
        """Forget the programme and the manual queue."""
        self._programme_cursor = -1
        self.manual_items = []
        self.current_programme = None
        self.current_playlist = None
        self.credits_executed.clear()
        self._title_index = self._title_pause_at = None
        self._title_armed = False
        self._set_state(ProgrammeState.NOT_LOADED)

    def standby(self):
        """Go to standby, the one way to do it: clear any programme or manual
        queue and put the cinema's ident on screen, played once and then held.

        An agent's player owns standby: it is sent the spec when that may have
        changed, then asked to show it. A local mpv is loaded with the same
        ident and hold options. False when the player could not be reached."""
        if not self._ensure_connected():
            return False
        with self._playout_lock:
            self._clear()
            host = self._host
            if host is None or host.kind != PlayoutHost.KIND_AGENT:
                url, _path, options, label = standby_spec.resolve_ident()
                ok = bool(
                    self.controller.load_file(url, replace=True, options=options, title=STANDBY_TITLE)
                    and self.controller.pause(False)
                )
                if ok:
                    if host is not None:
                        standby_spec.shown_local(host.id, url, options)
                    logger.info("On standby: %s", label)
                return ok

            from .services.playout_agent_service import playout_agent_service

            try:
                standby_spec.sync_spec(host)
                if not standby_spec.in_sync(host, playout_agent_service.enter_standby(host)):
                    # The player lost the spec (reset or re-installed): send it again.
                    standby_spec.sync_spec(host, force=True)
                    playout_agent_service.enter_standby(host)
            except UnprocessableEntityError as e:
                standby_spec.forget(host.id)
                logger.warning("Could not put %s on standby: %s", host.name, e.message)
                return False
            logger.info("On standby (%s)", host.name)
            return True

    def _on_standby(self) -> bool:
        """Whether the player shows standby now (and so holds it as entry 0)."""
        host = self._host
        if host is not None and host.kind == PlayoutHost.KIND_AGENT:
            from .services.playout_agent_service import playout_agent_service

            try:
                status = playout_agent_service.host_status(host)
            except UnprocessableEntityError:
                return False
            return bool((status.get("standby") or {}).get("on_standby"))
        return self.controller.get_property("path") == standby_spec.resolve_ident()[0]

    def _ensure_standby(self) -> bool:
        """Standby on screen with nothing loaded, putting it there when needed
        (a player reports it a moment after being asked)."""
        if self.idle() and self._on_standby():
            return True
        if not self.standby():
            return False
        deadline = time.monotonic() + STANDBY_WAIT_SECONDS
        while not self._on_standby():
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)
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
        """Cue a programme behind standby.

        Standby stays on screen as MPV playlist entry 0 (the ident is never
        replayed): the title card, if any, and every item are appended after it,
        so ``mpv_index = playlist_offset + order`` with an offset of 1, or 2 with
        a title card. A title card starts at once and holds paused (see
        _title_started); without one, standby holds until start_programme."""
        logger.info(f"Loading programme: {programme.name}")

        if not self._ensure_connected():
            return False

        with self._playout_lock:
            try:
                # An empty programme (no resolvable items) could never complete:
                # refuse it before touching any state.
                playlist = Playlist.objects.get(programme=programme)
                items = list(
                    playlist.items.select_related(
                        "movie_playback__movie", "trailer", "bumper", "command", "certification", "programme_block"
                    ).order_by("order")
                )
                if not items:
                    logger.error(f"Programme '{programme.name}' has an empty playlist; refusing to load")
                    return False

                # Clears any loaded programme or manual queue (a programme, or a
                # screening's lead-in, replaces manual play).
                if not self._ensure_standby():
                    logger.error("The player did not go to standby; not loading the programme")
                    return False

                title_url = programme.get_title_stream_url() if hasattr(programme, "get_title_stream_url") else None
                c = self.controller
                c.playlist_clear()  # keeps the current entry: standby
                if title_url and not c.enqueue_file(title_url, title=f"Programme: {programme.name}"):
                    return self._abort_load("the title card")
                self.playlist_offset = len(c.get_playlist() or [])
                if self.playlist_offset != (2 if title_url else 1):
                    return self._abort_load(f"standby (the player's playlist has {self.playlist_offset} entries)")

                # Every item MUST land in MPV's playlist: the DB playlist is 1:1
                # with MPV's, so a dropped append would misalign every later
                # item's cues, audio and credits markers. Abort instead.
                for item in items:
                    if not c.enqueue_file(item.file, title=item_title(item)):
                        return self._abort_load(f"item {item.order} ({item.file})")

                self.current_programme = programme
                self.current_playlist = playlist
                self._programme_cursor = -1
                self.credits_executed.clear()
                self._build_track_maps()
                self._set_state(ProgrammeState.LOADED)  # persists the offset too
                logger.info(f"Programme loaded: {len(items)} items after standby (offset {self.playlist_offset})")

                if title_url:
                    fade_in = programme.title_fade_in or 0
                    self._title_index = 1
                    self._title_pause_at = fade_in if programme.title_hold and fade_in > 0 else 0.0
                    # A title card that fades in from black needs no reveal.
                    self._leave_standby(1, reveal=0.0 if fade_in > 0 else COVER_REVEAL_SECONDS)
                    c.pause(False)
                return True

            except Playlist.DoesNotExist:
                logger.error(f"No playlist found for programme: {programme.name}")
                return False
            except Exception as e:
                logger.error(f"Error loading programme: {e}")
                return False

    def _abort_load(self, what):
        logger.error(f"Failed to queue {what}; aborting the load to keep the playlist aligned")
        self.standby()
        return False

    def start_programme(self):
        """Start the loaded programme: move off standby (or play on from the
        paused title card) and unpause."""
        with self._playout_lock:
            if not self.current_programme or not self.current_playlist:
                logger.error("No programme loaded")
                return False

            logger.info(f"Starting programme playback: {self.current_programme.name}")
            self._set_state(ProgrammeState.RUNNING)
            if self.controller.get_property("playlist_pos") in (None, 0):
                self._leave_standby(1, reveal=COVER_REVEAL_SECONDS)
            return self.controller.play()

    def _leave_standby(self, index, reveal):
        """Move from standby (entry 0) to entry ``index`` through black: fade a
        black cover in over COVER_FADE_SECONDS, move, then lift the cover over
        ``reveal`` seconds once the entry shows its first frame (0 lifts it at
        once). Only the fade runs here, under the playout lock; the reveal runs
        on its own thread. The move always happens, and the cover is always
        lifted, whatever fails. With standby not on screen there is nothing to
        fade, so this just moves."""
        c = self.controller
        if c.get_property("playlist_pos") != 0:
            return c.playlist_jump(index)
        standby_path = c.get_property("path")
        self._cover_gen += 1
        gen = self._cover_gen
        try:
            steps = max(1, round(COVER_FADE_SECONDS * COVER_STEPS_PER_SECOND))
            for step in range(1, steps + 1):
                if not self._cover(c, step / steps):
                    break  # the player refused it: move on without a fade
                time.sleep(COVER_FADE_SECONDS / steps)
        except Exception:
            logger.warning("Fading standby out failed; moving on without it", exc_info=True)
        restarts = getattr(c, "restart_serial", 0)
        moved = c.playlist_jump(index)
        try:
            threading.Thread(
                target=self._reveal,
                args=(c, gen, index, standby_path, reveal, restarts),
                daemon=True,
                name="standby-reveal",
            ).start()
        except Exception:  # noqa: BLE001 - no thread: lift the cover here
            self._cover(c, 0)
        return moved

    def _reveal(self, c, gen, index, standby_path, seconds, restarts=0):
        """Lift the cover once entry ``index`` shows a frame (or playback moved
        elsewhere, or COVER_FIRST_FRAME_WAIT passed), fading it out over ``seconds``.
        A newer fade owns the cover, so a superseded reveal leaves it alone.

        "Shows a frame" is mpv's playback-restart for a file other than standby,
        counted after the move. time-pos is set as soon as the file loads, before
        its first frame is decoded, so lifting on it showed the ident's last frame
        for a moment."""
        try:
            deadline = time.monotonic() + COVER_FIRST_FRAME_WAIT
            while time.monotonic() < deadline and c.get_property("playlist_pos") == index:
                if getattr(c, "restart_serial", 0) > restarts and getattr(c, "restart_path", None) not in (
                    None,
                    standby_path,
                ):
                    break
                time.sleep(0.02)
            steps = round(seconds * COVER_STEPS_PER_SECOND)
            for step in range(steps - 1, 0, -1):
                if gen != self._cover_gen:
                    return
                self._cover(c, step / steps)
                time.sleep(seconds / steps)
        except Exception:  # noqa: BLE001 - the finally still lifts the cover
            logger.debug("Standby reveal failed", exc_info=True)
        finally:
            if gen == self._cover_gen:
                self._cover(c, 0)

    @staticmethod
    def _cover(c, opacity):
        """Draw the black cover at ``opacity`` (0 to 1); 0 removes it. False when mpv refused."""
        if opacity <= 0:
            return c._mpv_command({"name": "osd-overlay", "id": COVER_OVERLAY_ID, "format": "none", "data": ""})
        alpha = round((1 - min(opacity, 1)) * 255)  # ASS alpha: 00 opaque, FF clear
        # Oversized so it covers any screen shape; PlayRes is 1280x720.
        data = (
            rf"{{\an7\pos(0,0)\bord0\shad0\1c&H000000&\1a&H{alpha:02X}&\p1}}"
            r"m -2000 -2000 l 3280 -2000 3280 2720 -2000 2720{\p0}"
        )
        return c._mpv_command(
            {
                "name": "osd-overlay",
                "id": COVER_OVERLAY_ID,
                "format": "ass-events",
                "data": data,
                "res_x": 1280,
                "res_y": 720,
                "z": COVER_Z,
            }
        )

    def _handle_file_end(self, event_data):
        """A file ended. MPV advances the playlist itself; a file or stream that
        failed to open or dropped (reason "error") is logged against its item,
        since it would otherwise look like a normal end."""
        if self.running and self.current_playlist and (event_data or {}).get("reason") == "error":
            self._log_playback_error()

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

        if self._title_pause_at is not None:
            self._title_started()

        if self.manual_items and self._is_black_clip(filepath):
            logger.info("Manual queue finished; going to standby")
            self.standby()
            return

        # The black sentinel at the end of a programme: go to standby. Hold-black
        # command items play the same clip, so confirm it's really the end
        # sentinel via the playlist item's content_type.
        if filepath and self._is_black_clip(filepath) and self.running and self._is_end_sentinel_position():
            logger.info("Programme ended; going to standby")
            self.standby()
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

    def _programme_started(self) -> bool:
        # NOT_LOADED counts as "still cueing": a title's file-start can land before load_programme sets LOADED.
        return self.programme_state == ProgrammeState.RUNNING

    def _title_started(self):
        """The cued title card began (after standby): pause on its first frame, or arm the
        fade-in hold. Dropped once the programme starts or playback moves past the title."""
        pos = self.controller.get_property("playlist_pos") if self.controller else None
        if self._programme_started() or (pos is not None and pos > self._title_index):
            self._title_pause_at = None
        elif pos == self._title_index:
            if self._title_pause_at:
                self._title_armed = True
            else:
                self._title_pause_at = None
                self.controller.pause()

    def _check_title_hold(self, time_pos):
        """Pause the armed title card once its fade-in is done (never past its end, which would
        advance into the programme)."""
        pos = self.controller.get_property("playlist_pos") if self.controller else None
        if self._programme_started() or (pos is not None and pos != self._title_index):
            self._title_pause_at, self._title_armed = None, False
            return
        if pos is None:
            return
        duration = self._live["duration"]
        if time_pos >= self._title_pause_at or (duration and time_pos >= duration - 0.5):
            self._title_pause_at, self._title_armed = None, False
            self.controller.pause()

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

        if self._title_armed and time_pos is not None:
            self._check_title_hold(time_pos)

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

    def manual_add(self, title, kind, url, now=False):
        """Play (``now``) or queue a one-off item. The caller ends any loaded programme first.

        Play now puts the item straight after the current one and skips to it, keeping
        the rest of the queue; the first item starts the queue (and its sentinel)."""
        if not self._ensure_connected():
            return False
        with self._playout_lock:
            entry = {"title": title, "kind": kind}
            c = self.controller
            if not self.manual_items:
                ok = (
                    c.load_file(url, replace=True, title=manual_title(kind, title))
                    and c.enqueue_file(system_black_stream_url(), title=BLACK_TITLE)
                    and c.pause(False)
                )
                self.manual_items = [entry] if ok else []
                self._notify_live()
                return ok
            end = len(c.get_playlist() or [])  # the sentinel is the last entry
            to = min((c.get_property("playlist_pos") or 0) + 1, end - 1) if now else end - 1
            ok = c.enqueue_file(url, title=manual_title(kind, title)) and c._mpv_command("playlist-move", end, to)
            if ok:
                self.manual_items.insert(to, entry)
                if now:
                    ok = c._mpv_command("playlist-play-index", to) and c.pause(False)
            self._notify_live()
            return ok

    def manual_remove(self, index):
        """Drop a queued item (removing the one on screen skips to the next)."""
        with self._playout_lock:
            if not 0 <= index < len(self.manual_items) or not self._ensure_connected():
                return False
            if len(self.manual_items) == 1:
                return self.standby()
            ok = self.controller._mpv_command("playlist-remove", index)
            if ok:
                self.manual_items.pop(index)
            self._notify_live()
            return ok

    def manual_move(self, index, to):
        """Reorder the queue: move item ``index`` to position ``to``."""
        with self._playout_lock:
            n = len(self.manual_items)
            if not (0 <= index < n and 0 <= to < n) or index == to or not self._ensure_connected():
                return False
            # MPV's playlist-move inserts *before* its target, so a move down targets one past it.
            ok = self.controller._mpv_command("playlist-move", index, to + 1 if to > index else to)
            if ok:
                self.manual_items.insert(to, self.manual_items.pop(index))
            self._notify_live()
            return ok

    def get_status(self):
        """Get current playback status"""
        if not self._ensure_connected():
            return None
        return self.controller.get_status()

    def snapshot(self):
        """What status needs from the player, in five reads: pause, time, duration,
        playlist position and path. None when the player can't be reached."""
        if not self._ensure_connected():
            return None
        c = self.controller
        try:
            player = c.player
            pos = player.playlist_pos
            return {
                "pause": bool(player.pause),
                "time": c._num(player.time_pos),
                "duration": c._num(player.duration),
                "pos": pos if isinstance(pos, int) and pos >= 0 else None,
                "path": player.path,
            }
        except Exception as e:  # noqa: BLE001 - an unreachable player is a status, not an error
            logger.debug("Player snapshot failed: %s", e)
            return None

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
                # Pre-show entries (before the programme offset) are standby
                # and the generated title card: label them rather than showing
                # a URL fragment or a file path on the player.
                if i < self.playlist_offset:
                    title = self._preshow_title(item.get("filename", ""))
                else:
                    title = self.getFileName(item.get("filename", "")) or f"Item {i + 1}"
                programme_position = None

                # Calculate programme position (excluding the pre-show entries)
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

    def in_preshow(self, position) -> bool:
        """True while standby or the title card is on screen ahead of the programme's
        first item. Positional: programme items occupy mpv indices
        ``playlist_offset + order``, so anything before the offset is pre-show."""
        if not self.current_playlist or self.playlist_offset <= 0:
            return False
        return position is not None and position < self.playlist_offset

    @staticmethod
    def _preshow_title(url):
        """Friendly label for a pre-show entry (standby / title card)."""
        path = (url or "").split("?")[0]
        if "/stream/title/" in path:
            return "Title card"
        if "/stream/system/black/" in path:
            return "Black"
        return "Standby"

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
