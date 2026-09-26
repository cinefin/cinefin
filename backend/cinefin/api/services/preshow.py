"""Pre-show cue list: the one place that reads `scheduler.preshow_commands`.

Each configured cue is `{"command": <id>, "lead": <seconds-before-scheduled-start>}`.
A cue with lead 0 fires when the programme starts (inside `start_programme`); a cue
with lead > 0 is fired ahead of `start_time` by the schedule runner. Legacy int
entries (a bare command id) read as lead 0."""

import logging

from cinefin.api.models import Command, Settings
from cinefin.api.services import command_runner

logger = logging.getLogger(__name__)


def cues() -> list[tuple[int, int]]:
    """[(command_id, lead_seconds)] in configured order; tolerant of legacy int entries."""
    out: list[tuple[int, int]] = []
    for raw in Settings.get("scheduler.preshow_commands") or []:
        if isinstance(raw, bool):
            continue
        if isinstance(raw, int):
            out.append((raw, 0))
        elif isinstance(raw, dict) and isinstance(raw.get("command"), int) and not isinstance(raw["command"], bool):
            lead = raw.get("lead", 0)
            out.append((raw["command"], int(lead) if isinstance(lead, int | float) and lead > 0 else 0))
    return out


def command_ids() -> list[int]:
    return [cid for cid, _ in cues()]


def advance_cues() -> list[tuple[int, int]]:
    """Lead > 0 cues, earliest first (largest lead), for the schedule runner's run-up pass."""
    return sorted([(cid, lead) for cid, lead in cues() if lead > 0], key=lambda c: -c[1])


def fire(ids: list[int]) -> int:
    """Fire the given command ids in order on a background thread. Returns how many resolved."""
    by_id = {c.id: c for c in Command.objects.filter(id__in=ids)}
    missing = [i for i in ids if i not in by_id]
    if missing:
        logger.warning("Pre-show command(s) %s no longer exist; skipping", missing)
    resolved = [by_id[i] for i in ids if i in by_id]
    command_runner.execute_many_sequential(resolved, trigger="preshow")
    return len(resolved)


def fire_at_start() -> None:
    """Fire the at-start cues (lead 0) — called from start_programme on a scheduled run."""
    ids = [cid for cid, lead in cues() if lead <= 0]
    if ids:
        fire(ids)


def fire_all() -> int:
    """Fire every configured cue now, in order — the manual 'run pre-show now' path."""
    return fire(command_ids())
