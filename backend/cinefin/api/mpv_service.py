"""The playout service: the programme lifecycle, standby, manual mode and cues over MPV."""

import logging
import re
import threading
import time

from . import playout_timing
from .exceptions import UnprocessableEntityError
from .models import Playlist, PlayoutHost, PlayoutSession, Programme
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


def manual_title(kind, title):
    """The window title for an item of ``kind`` called ``title``."""
    label = _KIND_LABELS.get(kind)
    if not label:
        return title or None
    return f"{label}: {title}" if title else label


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
    return manual_title(kind, name)


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

_SUB_BORDER_STYLES = ("outline-and-shadow", "opaque-box", "background-box")


class ProgrammeState:
    """The programme lifecycle. Pause is mpv's own, and a finished programme goes
    straight to standby, so these three are all there is; the phase every surface
    shows is worked out from them in services/playout_service.py."""

    NOT_LOADED = "not_loaded"
    LOADED = "loaded"  # cued, not started
    RUNNING = "running"  # started


def _delegate(name, default=False):
    """A method that connects on demand and forwards to the controller's ``name``."""

    def method(self, *args):
        if not self._ensure_connected():
            return default
        return getattr(self.controller, name)(*args)

    method.__name__ = name
    return method


class MPVService:
    def __init__(self):
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

        # Serialises connection setup: concurrent status polls can race the lazy
        # connect, and because a WSMPV self-heals its socket an orphaned
        # controller never dies; it keeps firing duplicate events (and duplicate
        # advances, which skip items).
        self._connect_lock = threading.Lock()

        # MoviePlayback ids whose audio/subtitle tracks are already set.
        self._tracks_done = set()
        # Playlist item ids whose credits command has fired.
        self.credits_executed = {}
        # Last programme item order reached; command cues fire when the
        # cursor moves forward past them. -1 = still in pre-show.
        self._programme_cursor = -1

        self._executing_command = False  # a hold-black command item is on screen
        # A programme the player lost (it restarted) while on air, for the operator to resume
        # or dismiss: {"programme_id", "order", "seconds", "credits", "schedule_id"}.
        self.interrupted = None
        # The mpv position whose hold is running: the link coming back re-sends the position,
        # which must not start the same hold (and fire its command) a second time.
        self._hold_position = None
        self._hold_progress = None  # {'duration','elapsed'} while a hold-black command runs
        # Cued title card: its mpv index, when to pause into it (0 = first frame, else after the
        # fade-in) and whether it has started (armed by its file-start, so standby's clock can't trip it).
        self._title_index = None
        self._title_pause_at = None
        self._title_armed = False
        # Bumped by each fade off standby, so an older reveal never lifts a newer cover.
        self._cover_gen = 0

        # Live playback cache, updated from the mpv property observers so the
        # status push can build a snapshot with no per-request mpv round-trips.
        self._live = {"time": None, "duration": None, "pause": None, "playlist_pos": None, "file": None}

        # Manual mode: one-off items played outside any programme, 1:1 with MPV's
        # playlist ahead of a trailing black sentinel (whose start puts the
        # player on standby, as at a programme's end). Empty = not in manual mode.
        self.manual_items = []

    @property
    def executing_command(self) -> bool:
        return self._executing_command

    @property
    def running(self):
        return self.programme_state == ProgrammeState.RUNNING

    def _set_state(self, new_state):
        self.programme_state = new_state
        self._persist_session()
        self._notify_live()

    def _persist_session(self):
        """Snapshot the lifecycle to the DB so a restarted process can re-attach.
        Never allowed to break playback."""
        try:
            session = PlayoutSession.load()
            session.state = self.programme_state
            session.programme = self.current_programme if self.programme_state != ProgrammeState.NOT_LOADED else None
            session.playlist_offset = self.playlist_offset
            session.programme_cursor = self._programme_cursor
            session.credits_executed = sorted(self.credits_executed.keys())
            session.manual_items = list(self.manual_items)
            session.save()
        except Exception:
            logger.exception("Failed to persist playout session")

    def _restore_session(self):
        """Re-attach after a process restart: MPV keeps playing across Django restarts, so
        a persisted programme or manual queue the player still holds is taken back."""
        if self._session_restored:
            return
        self._session_restored = True
        try:
            session = PlayoutSession.load()
            entries = self.controller.get_playlist() if self.controller else None
            if session.manual_items:
                if entries is not None and len(entries) == len(session.manual_items) + 1:
                    self.manual_items = list(session.manual_items)
                    logger.info(f"Re-attached to manual play ({len(self.manual_items)} items)")
                else:
                    logger.info("Persisted manual queue is stale; clearing")
                    self._forget_session(session)
                return
            if session.state not in (ProgrammeState.LOADED, ProgrammeState.RUNNING) or not session.programme_id:
                return

            playlist = Playlist.objects.filter(programme_id=session.programme_id).first()
            if playlist is None or not self._holds_programme(playlist, session.playlist_offset, entries):
                logger.info("Persisted playout session is stale (the player no longer holds it); clearing")
                programme_id, was_running = session.programme_id, session.state == ProgrammeState.RUNNING
                order, credits = session.programme_cursor, list(session.credits_executed)
                self._forget_session(session)
                schedule_id = self._abandon_screening(programme_id, "The player no longer had it after a restart")
                if was_running:
                    self._remember_interrupted(programme_id, order, None, credits, schedule_id)
                return

            self.current_programme = session.programme
            self.current_playlist = playlist
            self.playlist_offset = session.playlist_offset
            self._programme_cursor = session.programme_cursor
            self.programme_state = session.state
            self.credits_executed = dict.fromkeys(session.credits_executed, True)
            self._tracks_done = set()
            # A hold-black item may have set loop-file before the restart; its
            # watcher thread died with the old process, so clear the loop or
            # the black clip repeats forever.
            self.controller.set_property("loop-file", "no")
            logger.info(
                f"Re-attached to playout session: '{session.programme.name}' "
                f"({session.state}, offset {session.playlist_offset})"
            )
            self._catch_up()
        except Exception:
            logger.exception("Failed to restore playout session")

    @staticmethod
    def _forget_session(session):
        session.state, session.programme, session.manual_items = ProgrammeState.NOT_LOADED, None, []
        session.save()

    @staticmethod
    def _holds_programme(playlist, offset, entries):
        """Whether MPV's playlist ``entries`` still holds ``playlist``'s items after ``offset``.
        A restarted player comes back holding only its standby; an exact match also keeps a
        manual queue or another programme from being taken for this one."""
        if not entries:
            return False
        files = list(playlist.items.order_by("order").values_list("file", flat=True))
        names = [entry.get("filename", "") for entry in entries[offset:]]

        def bare(url):  # stream URLs carry a ?t= token
            return (url or "").split("?")[0]

        return len(names) == len(files) and all(bare(a) == bare(b) for a, b in zip(names, files, strict=True))

    @staticmethod
    def _abandon_screening(programme_id, reason):
        from .services import schedule_runner

        return schedule_runner.abandon_running(programme_id, reason)

    def _remember_interrupted(self, programme_id, order, seconds, credits, schedule_id):
        self.interrupted = {
            "programme_id": programme_id,
            "order": max(order, 0),
            "seconds": seconds if order >= 0 else None,
            "credits": credits,
            "schedule_id": schedule_id,
        }
        logger.info(f"Interrupted at item {max(order, 0)} ({seconds or 0:.0f}s): the operator may resume it")
        self._notify_live()

    def resume_interrupted(self):
        """Cue the interrupted programme again and play on from the item and second where the
        player lost it. The cues before that item already fired, and are not fired again."""
        lost = self.interrupted
        programme = Programme.objects.filter(id=(lost or {}).get("programme_id")).first()
        if programme is None:
            self.interrupted = None
            return False
        with self._playout_lock:
            if not self.load_programme(programme):
                self.interrupted = lost
                return False
            index = self.playlist_offset + lost["order"]
            self._title_pause_at, self._title_armed = None, False
            self._programme_cursor = lost["order"]
            self.credits_executed = dict.fromkeys(lost["credits"], True)
            self._set_state(ProgrammeState.RUNNING)
            self._leave_standby(index, reveal=COVER_REVEAL_SECONDS)
            if not self.controller.play():
                self._set_state(ProgrammeState.LOADED)
                return False
        if lost["seconds"]:
            threading.Thread(target=self._seek_once_loaded, args=(index, lost["seconds"]), daemon=True).start()
        from .services import schedule_runner

        schedule_runner.resume_abandoned(lost["schedule_id"])
        logger.info(f"Resumed '{programme.name}' at item {lost['order']}")
        return True

    def _seek_once_loaded(self, index, seconds, wait=10.0):
        """Seek to ``seconds`` once the player has entry ``index`` loaded (it can't seek before)."""
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            c = self.controller
            if c and c.get_property("playlist_pos", quiet=True) == index and c.get_property("duration", quiet=True):
                c.seek(seconds)
                return
            time.sleep(0.2)
        logger.warning(f"Resumed at the start of the item: it did not load within {wait:.0f}s")

    def dismiss_interrupted(self):
        self.interrupted = None
        self._notify_live()
        return True

    def _catch_up(self):
        """After re-attaching, act on where the player got to meanwhile: the observers'
        first values arrive before the session is restored, so they were ignored."""
        if not self.running:
            return
        c = self.controller
        if self._is_black_clip(c.get_property("path")) and self._is_end_sentinel_position():
            logger.info("The programme ended while Cinefin was away; going to standby")
            self.standby()
            return
        pos = c.get_property("playlist_pos")
        if pos is None or pos < self.playlist_offset:
            return
        order = pos - self.playlist_offset
        window = playout_timing.cue_window(self._programme_cursor, order)
        self._programme_cursor = order
        self._persist_session()
        if window:
            self._fire_cues_between(*window)

    def _reconcile(self):
        """The player link came back. A player that restarted meanwhile is on standby with
        our programme or manual queue gone: stop reporting it as cued or on air, which would
        show a phase that isn't true and hold back every later screening."""
        if self.idle() or not self._playout_lock.acquire(blocking=False):
            return  # nothing to check, or a load or start is setting the state itself
        try:
            entries = self.controller.get_playlist() if self.controller else None
            if entries is None:
                return  # can't tell
            if self.manual_items:
                gone, what = len(entries) != len(self.manual_items) + 1, "the manual queue"
            else:
                gone = not self._holds_programme(self.current_playlist, self.playlist_offset, entries)
                what = f"'{self.current_programme.name}'"
            if not gone:
                return
            logger.warning(f"The player no longer holds {what} (it restarted?); going to standby")
            programme_id = self.current_programme.id if self.current_programme else None
            lost = (
                (self._programme_cursor, self._live.get("time"), sorted(self.credits_executed))
                if self.running
                else None
            )
            # An agent is on standby already; a restarted local mpv sits idle on black.
            if not self.standby():
                self._clear()
            if programme_id:
                schedule_id = self._abandon_screening(programme_id, "The player restarted while it was on")
                if lost:
                    self._remember_interrupted(programme_id, *lost, schedule_id)
        finally:
            self._playout_lock.release()

    def _drop_controller(self):
        if self.controller is not None:
            try:
                self.controller.terminate()
            except Exception:  # noqa: BLE001 - best effort; never block a reconnect or switch
                logger.debug("controller terminate failed", exc_info=True)
        self.controller = None

    def unload_for_host_switch(self):
        """The active playout host changed: leave the old host on standby and drop
        the control link so the next connect targets the new host. Best-effort:
        a wedged old host must not block the switch."""
        try:
            if self.controller is not None and getattr(self.controller, "_connected", False):
                self.standby()
        except Exception:  # noqa: BLE001
            logger.debug("standby during host switch failed", exc_info=True)
        self._drop_controller()
        self._host = None
        self._lazy_initialized = False
        self._session_restored = False
        self.current_programme = None
        self.current_playlist = None
        self.playlist_offset = 0
        self.programme_state = ProgrammeState.NOT_LOADED
        self._persist_session()

    def _connect(self):
        """Connect to the active playout host. Tears down any existing controller
        first (a dereferenced WSMPV keeps its link alive and keeps dispatching
        events). Only called under _connect_lock."""
        try:
            self._drop_controller()
            self.controller = MPVController()
            self._host = PlayoutHost.get_active()

            # The controller degrades to disconnected rather than raising.
            if not getattr(self.controller, "_connected", False):
                self.controller = None
                return False

            c = self.controller
            c.add_event_handler("file_end", self._handle_file_end)
            c.add_event_handler("file_start", self._handle_file_start)
            c.add_event_handler("playlist_change", self._handle_playlist_change)
            c.add_event_handler("time_pos", self._handle_time_pos)
            c.add_event_handler("pause", self._handle_pause)
            # A dropped link: push the status so every surface shows the player offline.
            c.add_event_handler("quit", lambda _value: self._notify_live())
            c.add_event_handler("reconnect", lambda _value: self._reconcile())

            self._check_mpv_version()
            self.apply_subtitle_style()
            logger.info("MPV service connected")
            return True
        except Exception as e:
            logger.error(f"Failed to connect MPV service: {e}")
            self.controller = None
            return False

    def apply_subtitle_style(self):
        """Apply the room's subtitle style (Settings → playout.subtitles) to the
        live player. Cosmetic and best-effort."""
        if not self.controller or not getattr(self.controller, "_connected", False):
            return
        from cinefin.api.models import Settings

        s = Settings.get("playout.subtitles") or {}
        border = s.get("border_style")
        props = {
            "sub-font-size": s.get("font_size", 55),
            "sub-color": s.get("color", "#FFFFFF"),
            "sub-border-style": border if border in _SUB_BORDER_STYLES else "outline-and-shadow",
            "sub-back-color": s.get("back_color", "#000000"),
            "sub-pos": s.get("position", 100),
            "sub-margin-y": s.get("margin_y", 22),
            "sub-use-margins": "yes" if s.get("use_margins", True) else "no",
            "sub-bold": "yes" if s.get("bold", False) else "no",
        }
        # Quietly: a property missing on an older mpv (e.g. sub-margin-y) is harmless.
        for name, value in props.items():
            self.controller.set_property(name, value, quiet=True)

    def _check_mpv_version(self):
        """A local mpv must be 0.38 or newer for standby's per-file options (an
        agent's mpv is the player's business)."""
        self.player_warning = ""
        if (self.controller.transport or ("",))[0] != "socket":
            return
        version = str(self.controller.get_property("mpv-version") or "")
        match = re.search(r"(\d+)\.(\d+)", version)
        if match and (int(match[1]), int(match[2])) < MIN_MPV_VERSION:
            self.player_warning = f"{version} is too old for standby: update mpv to 0.38 or newer"
            logger.warning("Local player: %s", self.player_warning)

    def _ensure_connected(self):
        # Double-checked under _connect_lock so only one thread ever builds the controller.
        if not self._lazy_initialized or not self.controller:
            with self._connect_lock:
                if not self._lazy_initialized or not self.controller:
                    self._lazy_initialized = True
                    if not self._connect():
                        return False
        self._restore_session()
        return True

    def ensure_link(self):
        """Keep the control link to the active agent open (called by
        ``services/playout_link.py``); False when the agent could not be reached.
        A controller for a host that is no longer active (or a stale token) is
        torn down first. Local-socket hosts are left to connect on demand."""
        from .mpv_controller import _transport_config

        want = _transport_config()
        if want is None or want[0] != "ws":
            return True
        if self.controller is not None and getattr(self.controller, "transport", want) != want:
            logger.info("The active playout host changed; reconnecting")
            self.unload_for_host_switch()
        return self._ensure_connected()

    def idle(self) -> bool:
        """True when no programme is loaded and no manual queue plays."""
        return self.current_programme is None and not self.manual_items

    def _clear(self):
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
            if host is not None:
                # The row was read when the link connected; its name and show_status may have
                # changed since, and a stale copy would send the player an old spec.
                try:
                    host.refresh_from_db()
                except PlayoutHost.DoesNotExist:
                    return False
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
        self.interrupted = None

        with self._playout_lock:
            try:
                playlist = Playlist.objects.filter(programme=programme).first()
                if playlist is None:
                    logger.error(f"No playlist found for programme: {programme.name}")
                    return False
                items = list(
                    playlist.items.select_related(
                        "movie_playback__movie", "trailer", "bumper", "command", "certification", "programme_block"
                    ).order_by("order")
                )
                # An empty programme could never complete: refuse it before touching any state.
                if not items:
                    logger.error(f"Programme '{programme.name}' has an empty playlist; refusing to load")
                    return False

                # Clears any loaded programme or manual queue.
                if not self._ensure_standby():
                    logger.error("The player did not go to standby; not loading the programme")
                    return False

                title_url = programme.get_title_stream_url()
                c = self.controller
                c.playlist_clear()  # keeps the current entry: standby
                if title_url and not c.enqueue_file(title_url, title=f"Programme: {programme.name}"):
                    return self._abort_load("the title card")
                self.playlist_offset = len(c.get_playlist() or [])
                if self.playlist_offset != (2 if title_url else 1):
                    return self._abort_load(f"standby (the player's playlist has {self.playlist_offset} entries)")

                # Every item MUST land in MPV's playlist: a dropped append would
                # misalign every later item's cues, audio and credits markers.
                for item in items:
                    if not c.enqueue_file(item.file, title=item_title(item)):
                        return self._abort_load(f"item {item.order} ({item.file})")

                self.current_programme = programme
                self.current_playlist = playlist
                self._programme_cursor = -1
                self.credits_executed.clear()
                self._tracks_done = set()
                self._set_state(ProgrammeState.LOADED)
                logger.info(f"Programme loaded: {len(items)} items after standby (offset {self.playlist_offset})")

                if title_url:
                    fade_in = programme.title_fade_in or 0
                    self._title_index = 1
                    self._title_pause_at = fade_in if programme.title_hold and fade_in > 0 else 0.0
                    # A title card that fades in from black needs no reveal.
                    self._leave_standby(1, reveal=0.0 if fade_in > 0 else COVER_REVEAL_SECONDS)
                    c.pause(False)
                return True
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
            if self.controller.play():
                return True
            # Still cued: a programme stuck "running" would hold back every later screening.
            logger.error("The player did not start; the programme stays cued")
            self._set_state(ProgrammeState.LOADED)
            return False

    def _leave_standby(self, index, reveal):
        """Move from standby (entry 0) to entry ``index`` through black: fade a
        black cover in over COVER_FADE_SECONDS, move, then lift the cover over
        ``reveal`` seconds once the entry shows its first frame (0 lifts it at
        once). Only the fade runs here, under the playout lock; the reveal runs
        on its own thread. The move always happens, and the cover is always
        lifted, whatever fails. With standby not on screen this just moves."""
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

    def _current_item(self, pos=None):
        """The programme's playlist item at mpv index ``pos`` (default: the current one), or None."""
        if pos is None:
            pos = self.controller.get_property("playlist_pos")
        if pos is None or pos < self.playlist_offset:
            return None
        return self.current_playlist.items.filter(order=pos - self.playlist_offset).first()

    def _handle_file_end(self, event_data):
        """A file ended (MPV advances by itself). One that failed to open or
        dropped (reason "error") is logged against its item, since it would
        otherwise look like a normal end."""
        if not (self.running and self.current_playlist and (event_data or {}).get("reason") == "error"):
            return
        try:
            pos = self.controller.get_property("playlist_pos")
            item = self._current_item(pos)
            if item is not None:
                logger.warning(
                    f"MPV playback error on '{item.file}' ({item.content_type}, order {item.order}); "
                    f"advancing to the next item"
                )
            else:
                logger.warning(f"MPV playback error at playlist position {pos}; advancing")
        except Exception:
            logger.warning("MPV reported a playback error (details unavailable)")

    @staticmethod
    def _is_black_clip(filepath):
        return bool(filepath) and ("/stream/system/black" in filepath or "system/black.mp4" in filepath)

    def _is_end_sentinel_position(self):
        """True when MPV is on the trailing "system" black item (programme end).
        Hold-black command items play the same clip, so the path alone can't tell."""
        try:
            pos = self.controller.get_property("playlist_pos") if self.controller else None
            if pos is None:
                return False  # can't tell (the link is down): never end a programme on a guess
            if not self.current_playlist:
                return True
            if pos < self.playlist_offset:
                return False  # still in pre-show
            item = self._current_item(pos)
            return item is None or item.content_type == "system"
        except Exception:
            logger.exception("Failed to resolve playlist position for black.mp4 disambiguation")
            return False

    def _handle_file_start(self, filepath):
        logger.info(f"File started: {filepath}")
        # The duration is refetched lazily on the next time-pos.
        self._live["file"] = filepath
        self._live["duration"] = None
        self._notify_live()

        if self._title_pause_at is not None:
            self._title_started()

        if self.manual_items and self._is_black_clip(filepath):
            logger.info("Manual queue finished; going to standby")
            self.standby()
            return

        if self._is_black_clip(filepath) and self.running and self._is_end_sentinel_position():
            logger.info("Programme ended; going to standby")
            self.standby()
            return

        if self.current_playlist:
            threading.Thread(target=self._configure_tracks_for_file, args=(filepath,), daemon=True).start()

    def _handle_playlist_change(self, position):
        """Advance the programme cursor, fire any command cues passed over, and
        run hold-black command items. Moving forward fires every cue between the
        old and new cursor, in order; moving backward fires nothing (the cues
        re-fire when playback passes them again)."""
        self._live["playlist_pos"] = position
        self._notify_live()
        if not self.running or not self.current_playlist:
            return
        if position is None or position < self.playlist_offset:
            return
        order = position - self.playlist_offset
        previous_order = self._programme_cursor
        self._programme_cursor = order
        self._persist_session()

        try:
            window = playout_timing.cue_window(previous_order, order)
            if window:
                self._fire_cues_between(*window)

            item = self._current_item(position)
            if item is None:
                logger.warning(f"Playlist item not found for programme order {order}")
            elif item.content_type == "command" and position != self._hold_position:
                self._hold_position = position
                # Never block the event handler.
                threading.Thread(target=self._hold, args=(item, position), daemon=True).start()
        except Exception as e:
            logger.error(f"Error handling playlist position change: {e}")

    def _fire_cues_between(self, previous_order, new_order):
        """Fire instant command cues in (previous_order, new_order], in order."""
        from cinefin.api.services import command_runner

        commands = []
        for cue in self.current_playlist.cues.filter(
            fires_before_order__gt=previous_order, fires_before_order__lte=new_order
        ).order_by("fires_before_order", "seq"):
            if cue.command is None:
                logger.warning(f"Command cue '{cue.command_name}' points at a deleted command; skipping")
            else:
                commands.append(cue.command)
        if commands:
            logger.info(f"Firing {len(commands)} command cue(s) for items {previous_order + 1}..{new_order}")
            command_runner.execute_many_sequential(commands, trigger="block")

    def _hold(self, item, mpv_position):
        try:
            self._run_hold_item(item, mpv_position)
        finally:
            if self._hold_position == mpv_position:
                self._hold_position = None

    def _run_hold_item(self, item, mpv_position):
        """Run a hold-black command item: fire the command, keep the black clip
        looping until the command has finished AND its duration has elapsed
        (pause-aware), then advance.

        The black clip is only a few seconds long, so loop-file is what holds the
        screen; Command.duration is a minimum dwell, not a cap (providers time
        out at TIMEOUT_SECONDS, so this is bounded). A deleted command with no
        duration lets the black clip play out once."""
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
        # Overtime is the backstop for a runner thread that never signals.
        dwell = playout_timing.HoldDwell(hold_seconds, overtime=command_runner.TIMEOUT_SECONDS + 5.0)
        # MPV reports the looping clip's few-second length, so status shows the hold's own clock.
        self._hold_progress = dwell.progress
        looped = self.controller.set_property("loop-file", "inf")
        try:
            while not dwell.satisfied(done.is_set()):
                time.sleep(0.25)
                pos = self.controller.get_property("playlist_pos", quiet=True)
                if pos is None and self.running:
                    continue  # the link is down: wait it out, the dwell standing still
                verdict = dwell.tick(
                    0.25,
                    running=self.running,
                    on_item=pos == mpv_position,
                    paused=bool(self.controller.get_property("pause", quiet=True)),
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
        # Only advance if MPV is still on THIS hold's entry: a failing stream
        # before adjacent holds can error-advance several times, and a stale hold
        # thread's next() would cut the NEXT hold short.
        if self.controller.get_property("playlist_pos") == mpv_position:
            logger.info(f"Hold complete ('{name}', {hold_seconds}s minimum), advancing")
            self.controller.next()
        else:
            logger.info(f"Hold '{name}' superseded (playback moved on); not advancing")

    def _title_started(self):
        """The cued title card began (after standby): pause on its first frame, or arm the
        fade-in hold. Dropped once the programme starts or playback moves past the title.
        (NOT_LOADED still counts as cueing: the file-start can land before LOADED is set.)"""
        pos = self.controller.get_property("playlist_pos") if self.controller else None
        if self.running or (pos is not None and pos > self._title_index):
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
        if self.running or (pos is not None and pos != self._title_index):
            self._title_pause_at, self._title_armed = None, False
            return
        if pos is None:
            return
        duration = self._live["duration"]
        if time_pos >= self._title_pause_at or (duration and time_pos >= duration - 0.5):
            self._title_pause_at, self._title_armed = None, False
            self.controller.pause()

    def _handle_time_pos(self, time_pos):
        """Cache the position, hold a fading title card, and fire a feature's credits command."""
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
            item = self._current_item()
            if item is None or item.content_type != "movie" or self.credits_executed.get(item.id):
                return
            playback = item.content_object
            if playback is None:
                return
            movie, command = playback.movie, playback.credits_command
            if command and playout_timing.credits_due(time_pos, movie.credits_marker):
                logger.info(
                    f"Credits marker reached at {int(time_pos)}s (marker: {movie.credits_marker}s) for '{movie.title}'"
                )
                from cinefin.api.services import command_runner

                threading.Thread(
                    target=command_runner.execute,
                    args=(command,),
                    kwargs={"trigger": "credits", "wait": True},
                    daemon=True,
                ).start()
                self.credits_executed[item.id] = True
                self._persist_session()
        except Exception as e:
            logger.error(f"Error checking credits marker: {e}")

    def _handle_pause(self, paused):
        self._live["pause"] = paused
        self._notify_live()

    def _notify_live(self):
        """Wake the playout status push."""
        try:
            from cinefin.api.services.playout_events import playout_event_bus

            playout_event_bus.publish()
        except Exception:  # noqa: BLE001 - never let a notify break an event handler
            pass

    def _configure_tracks_for_file(self, filepath):
        """Select the block's audio and subtitle tracks when its feature starts."""
        if not self.current_playlist:
            return
        try:
            item = next(
                (
                    i
                    for i in self.current_playlist.items.all()
                    if i.file == filepath and i.content_type == "movie" and i.content_object is not None
                ),
                None,
            )
            if item is None:
                return
            playback = item.content_object
            if playback.id in self._tracks_done:
                return
            logger.info(
                f"Configuring tracks for {filepath}: MoviePlayback ID {playback.id}, "
                f"audio_track: {playback.audio_track_index}, subtitle_track: {playback.subtitle_track_index}"
            )
            time.sleep(0.5)  # let the file load
            # MPV track ids are 1-based; ours are 0-based.
            if playback.audio_track_index is not None:
                self.controller.set_audio_track(playback.audio_track_index + 1)
            # Subtitles stay visible so the track can be changed later; track 0 is none.
            self.controller.enable_subtitles()
            sub = playback.subtitle_track_index
            self.controller.set_subtitle_track(0 if sub is None else sub + 1)
            self._tracks_done.add(playback.id)
        except Exception as e:
            logger.error(f"Error configuring tracks for file {filepath}: {e}", exc_info=True)

    play = _delegate("play")
    pause = _delegate("pause")
    next = _delegate("next")
    previous = _delegate("previous")
    seek = _delegate("seek")
    seek_relative = _delegate("seek_relative")
    playlist_jump = _delegate("playlist_jump")
    _mpv_command = _delegate("_mpv_command")
    get_status = _delegate("get_status", None)
    get_playlist = _delegate("get_playlist", None)
    get_track_list = _delegate("get_track_list", None)

    def manual_add(self, title, kind, url, now=False):
        """Play (``now``) or queue a one-off item. The caller ends any loaded programme first.

        Play now puts the item straight after the current one and skips to it, keeping
        the rest of the queue; the first item starts the queue (and its sentinel)."""
        if not self._ensure_connected():
            return False
        self.interrupted = None
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
                self._persist_session()
                self._notify_live()
                return ok
            end = len(c.get_playlist() or [])  # the sentinel is the last entry
            to = min((c.get_property("playlist_pos") or 0) + 1, end - 1) if now else end - 1
            ok = c.enqueue_file(url, title=manual_title(kind, title)) and c._mpv_command("playlist-move", end, to)
            if ok:
                self.manual_items.insert(to, entry)
                self._persist_session()
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
                self._persist_session()
            self._notify_live()
            return ok

    def manual_move(self, index, to):
        """Move queued item ``index`` to position ``to``."""
        with self._playout_lock:
            n = len(self.manual_items)
            if not (0 <= index < n and 0 <= to < n) or index == to or not self._ensure_connected():
                return False
            # MPV's playlist-move inserts *before* its target, so a move down targets one past it.
            ok = self.controller._mpv_command("playlist-move", index, to + 1 if to > index else to)
            if ok:
                self.manual_items.insert(to, self.manual_items.pop(index))
                self._persist_session()
            self._notify_live()
            return ok

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

    def get_playlist_info(self):
        """MPV's playlist, each entry labelled and mapped to its programme position."""
        empty = {"playlist": [], "current_index": 0, "total_items": 0, "programme_offset": 0}
        if not self._ensure_connected():
            return empty
        try:
            mpv_playlist = self.controller.get_playlist() or []
            current_index = self.controller.get_property("playlist_pos") or 0
            offset = self.playlist_offset
            items = []
            for i, entry in enumerate(mpv_playlist):
                file = entry.get("filename", "")
                # Pre-show entries are standby and the title card: label them.
                preshow = i < offset
                items.append(
                    {
                        "index": i,
                        "title": self._preshow_title(file) if preshow else (self.getFileName(file) or f"Item {i + 1}"),
                        "type": self._guess_file_type(file),
                        "file": file,
                        "current": i == current_index,
                        "programme_position": None if preshow else i - offset,
                    }
                )
            return {
                "playlist": items,
                "current_index": current_index,
                "total_items": len(mpv_playlist),
                "programme_offset": offset,
            }
        except Exception as e:
            logger.error(f"Error getting playlist info: {e}")
            return empty

    @staticmethod
    def getFileName(path):
        """Display-usable last path segment. Stream URLs end "/?t=<token>", so
        strip the query string and trailing slash first."""
        if not path:
            return ""
        return path.split("?")[0].rstrip("/").split("/")[-1] or path

    def in_preshow(self, position) -> bool:
        """True while standby or the title card is on screen ahead of the programme's
        first item (anything before ``playlist_offset``)."""
        if not self.current_playlist or self.playlist_offset <= 0:
            return False
        return position is not None and position < self.playlist_offset

    @staticmethod
    def _preshow_title(url):
        path = (url or "").split("?")[0]
        if "/stream/title/" in path:
            return "Title card"
        if "/stream/system/black/" in path:
            return "Black"
        return "Standby"

    @staticmethod
    def _guess_file_type(filename):
        if not filename:
            return "unknown"
        lower = filename.lower()
        ext = lower.split(".")[-1] if "." in lower else ""
        if ext in ("mp4", "mkv", "avi", "mov", "wmv"):
            if "trailer" in lower:
                return "trailer"
            if "bumper" in lower or "ident" in lower:
                return "bumper"
            return "movie"
        return "audio" if ext in ("mp3", "wav", "flac") else "video"

    def terminate(self):
        logger.info("Terminating MPV service...")
        try:
            if self.controller:
                self.controller.terminate()
            self.controller = None
            self._lazy_initialized = False
            self._set_state(ProgrammeState.NOT_LOADED)
        except Exception as e:
            logger.error(f"Error terminating MPV service: {e}")


mpv_service = MPVService()
