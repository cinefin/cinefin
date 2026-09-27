"""A screening's lead-in: its own ordered steps, run from its start_time.

Each `ProgrammeSchedule.preshow` is a list of commands (each waits until it has finished
and its configured duration has passed) and one cue step, which loads the programme so its
title slate holds until it plays. No cue step means the cue runs first; moving it lower lets
commands such as a player restart run before the programme is loaded."""

import logging
import threading
import time

from cinefin.api.models import Command
from cinefin.api.services import command_runner

logger = logging.getLogger(__name__)

CUE = "cue"
CUE_WAIT_SECONDS = 60  # how long the cue keeps retrying while the player comes back (e.g. after a restart)

# One lead-in at a time: held by a scheduled run from its lead-in to play.
lock = threading.Lock()


def steps(raw: list) -> list[int | str]:
    """Ordered steps from stored `[{"command": id} | {"cue": true}]`: command ids and exactly one CUE
    (prepended when none is stored). Duplicates and malformed entries are dropped."""
    out: list[int | str] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        if item.get("cue"):
            if CUE not in out:
                out.append(CUE)
            continue
        cid = item.get("command")
        if isinstance(cid, int) and not isinstance(cid, bool) and cid not in out:
            out.append(cid)
    return out if CUE in out else [CUE, *out]


def command_ids(raw: list) -> list[int]:
    return [s for s in steps(raw) if s != CUE]


def clean(raw: list) -> list[dict]:
    """The stored form of submitted steps: normalised, unknown commands dropped."""
    valid = set(Command.objects.filter(id__in=command_ids(raw)).values_list("id", flat=True))
    return [{"cue": True} if s == CUE else {"command": s} for s in steps(raw) if s == CUE or s in valid]


def run(programme, raw: list) -> None:
    """Run a screening's steps in order, blocking. Raises only when the programme can't be cued."""
    by_id = {c.id: c for c in Command.objects.filter(id__in=command_ids(raw))}
    for step in steps(raw):
        if step == CUE:
            _cue(programme)
        elif step in by_id:
            _run_command(by_id[step])
        else:
            logger.warning("Lead-in command %s no longer exists; skipping", step)


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
