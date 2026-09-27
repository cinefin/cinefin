"""The pre-show sequence: the one place that reads `scheduler.preshow_commands`.

An ordered list of steps run at a screening's lead-in: commands (each waits until it has
finished and its configured duration has passed) and one cue step, which loads the programme
so its title slate holds until it plays. The cue defaults to first; moving it lower lets
commands such as a player restart run before the programme is loaded. Legacy entries (bare
command ids, `{command, lead}`) read as commands."""

import logging
import threading
import time

from cinefin.api.models import Command, Settings
from cinefin.api.services import command_runner

logger = logging.getLogger(__name__)

CUE = "cue"
CUE_WAIT_SECONDS = 60  # how long the cue keeps retrying while the player comes back (e.g. after a restart)

# One sequence at a time: held by a scheduled run from lead-in to play, or by a manual lead-in.
lock = threading.Lock()


def steps() -> list[int | str]:
    """Ordered steps: command ids and exactly one CUE (prepended when none is configured)."""
    out: list[int | str] = []
    for raw in Settings.get("scheduler.preshow_commands") or []:
        if isinstance(raw, dict) and raw.get("cue"):
            if CUE not in out:
                out.append(CUE)
        elif isinstance(raw, dict):
            raw = raw.get("command")
        if isinstance(raw, int) and not isinstance(raw, bool) and raw not in out:
            out.append(raw)
    return out if CUE in out else [CUE, *out]


def command_ids() -> list[int]:
    return [s for s in steps() if s != CUE]


def run(programme) -> None:
    """Run the sequence in order, blocking. Raises only when the programme can't be cued."""
    by_id = {c.id: c for c in Command.objects.filter(id__in=command_ids())}
    for step in steps():
        if step == CUE:
            _cue(programme)
        elif step in by_id:
            _run_command(by_id[step])
        else:
            logger.warning("Pre-show command %s no longer exists; skipping", step)


def _run_command(command: Command) -> None:
    started = time.monotonic()
    command_runner.execute(command, trigger="preshow", wait=True)  # never raises
    rest = (command.duration or 0) - (time.monotonic() - started)
    if rest > 0:
        time.sleep(rest)


def _cue(programme) -> None:
    from cinefin.api.models import Playlist

    if not Playlist.objects.filter(programme=programme).exists() or programme.playlist_stale:
        from cinefin.api.services import ProgrammeService

        if ProgrammeService.refresh_playlist(programme) is None:
            raise RuntimeError("Failed to generate playlist — check the application logs")

    deadline = time.monotonic() + CUE_WAIT_SECONDS
    while not _load(programme):
        if time.monotonic() >= deadline:
            raise RuntimeError("Failed to load programme into playout system")
        time.sleep(2)


def _load(programme) -> bool:
    from cinefin.api.mpv_service import ProgrammeState, mpv_service

    if (
        mpv_service.programme_state == ProgrammeState.LOADED
        and getattr(mpv_service.current_programme, "id", None) == programme.id
    ):
        return True  # already cued
    return mpv_service.load_programme(programme)
