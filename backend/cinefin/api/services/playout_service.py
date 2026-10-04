"""The playout status and its actions.

`playout_status()` works out, once, what the player is doing (its phase), what the
audience sees, a one-line label and the actions allowed now. GET /playout/status and
the WebSocket push both send it, and every surface (the top bar lamp, the playout bar,
the remote, the dashboard, the kiosk) reads it instead of deriving its own rules.
`perform()` runs a transport action and refuses (409) one the phase does not allow."""

import logging
from datetime import timedelta

from django.utils import timezone

from cinefin.api.exceptions import ConflictError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Command, PlaylistItem, PlayoutHost, Programme, ProgrammeSchedule
from cinefin.api.schemas.playout import (
    InterruptedSchema,
    ItemSchema,
    ManualItemSchema,
    ManualQueueSchema,
    NextScreeningSchema,
    PlaybackStatusSchema,
    PlayerSchema,
    PlaylistStatusSchema,
    PlayoutStatusDataSchema,
    ProgrammeFeatureSchema,
    ProgrammeInfoSchema,
)

logger = logging.getLogger(__name__)

OFFLINE, STANDBY, CUED, PRESHOW, PLAYING, PAUSED, HOLD, MANUAL = (
    "offline",
    "standby",
    "cued",
    "preshow",
    "playing",
    "paused",
    "hold",
    "manual",
)

# The actions each phase allows. Cue is POST /playout/load; the rest are POST
# /playout/control. Manual play has no previous or jump, and cueing a programme
# replaces it (see allowed_actions).
ACTIONS = {
    OFFLINE: [],
    STANDBY: ["cue"],
    CUED: ["start", "cue", "end"],
    PRESHOW: ["pause", "next", "seek", "jump", "end"],
    PLAYING: ["pause", "previous", "next", "seek", "jump", "end"],
    PAUSED: ["resume", "previous", "next", "seek", "jump", "end"],
    HOLD: ["previous", "end_hold", "jump", "end"],
    MANUAL: ["pause", "next", "seek", "end"],
}

_ACTION_WORDS = {
    "cue": "cue a programme",
    "start": "start",
    "pause": "pause",
    "resume": "resume",
    "previous": "go back an item",
    "next": "skip to the next item",
    "seek": "seek",
    "jump": "jump to an item",
    "end_hold": "end a hold",
    "end": "end",
    "recover": "resume the interrupted programme",
    "dismiss": "dismiss the interrupted programme",
}
_PHASE_WORDS = {
    OFFLINE: "the player can't be reached",
    STANDBY: "nothing is loaded",
    CUED: "the programme is cued but not started",
    PRESHOW: "the pre-show is playing",
    PLAYING: "the programme is playing",
    PAUSED: "playback is paused",
    HOLD: "a command is holding the screen",
    MANUAL: "the manual queue is playing",
}


def mark_programme_played(programme_id: int) -> None:
    """Record that a programme just started. Queryset update avoids races and doesn't bump updated_at."""
    Programme.objects.filter(pk=programme_id).update(last_played_at=timezone.now())


def phase_of(snap: dict | None) -> str:
    """The phase, from a player snapshot (``mpv_service.snapshot()``; None = unreachable)."""
    from cinefin.api.mpv_service import ProgrammeState, mpv_service

    if snap is None:
        return OFFLINE
    if mpv_service.manual_items:
        return PAUSED if snap["pause"] else MANUAL
    if mpv_service.current_programme is None:
        return STANDBY
    if mpv_service.programme_state != ProgrammeState.RUNNING:
        return CUED
    if mpv_service.executing_command:
        return HOLD
    if snap["pause"]:
        return PAUSED
    if mpv_service.in_preshow(snap["pos"]):
        return PRESHOW
    return PLAYING


def allowed_actions(phase: str, manual: bool, interrupted: bool = False) -> list[str]:
    actions = list(ACTIONS[phase])
    if manual:
        actions = [a for a in actions if a not in ("previous", "jump")] + ["cue"]
    if interrupted and phase == STANDBY:
        actions += ["recover", "dismiss"]
    return actions


def require(action: str) -> None:
    """Refuse (409) an action the current phase doesn't allow."""
    from cinefin.api.mpv_service import mpv_service

    phase = phase_of(mpv_service.snapshot())
    allowed = allowed_actions(phase, bool(mpv_service.manual_items), bool(mpv_service.interrupted))
    if action not in allowed:
        raise ConflictError(
            f"Can't {_ACTION_WORDS.get(action, action)} now: {_PHASE_WORDS[phase]}",
            error_code="ACTION_NOT_ALLOWED",
            details={"phase": phase, "actions": allowed},
        )


def perform(action: str, seconds: float | None = None, offset: float | None = None, index: int | None = None):
    """Run a transport action (any but cue, which is /playout/load) once the phase allows it."""
    from cinefin.api.mpv_service import mpv_service

    if action == "seek" and seconds is None and offset is None:
        raise ValidationError("seek needs seconds or offset")
    if action == "jump" and (index is None or index < 0):
        raise ValidationError("jump needs a player playlist index")
    require(action)

    if action == "start":
        programme = mpv_service.current_programme
        ok = mpv_service.start_programme()
        if ok:
            mark_programme_played(programme.id)
    elif action == "pause":
        ok = mpv_service.pause()
    elif action == "resume":
        ok = mpv_service.play()
    elif action in ("next", "end_hold"):
        ok = mpv_service.next()  # moving off a hold ends it
    elif action == "previous":
        ok = mpv_service.previous()
    elif action == "seek":
        ok = mpv_service.seek_relative(offset) if offset is not None else mpv_service.seek(seconds)
    elif action == "jump":
        ok = mpv_service.playlist_jump(index)
    elif action == "end":
        ok = mpv_service.standby()
    elif action == "recover":
        ok = mpv_service.resume_interrupted()
    elif action == "dismiss":
        ok = mpv_service.dismiss_interrupted()
    else:
        raise ValidationError(f"Unknown action: {action}")
    if not ok:
        raise UnprocessableEntityError(
            f"The player didn't {_ACTION_WORDS.get(action, action)}", error_code="PLAYER_FAILED"
        )


def _interrupted(lost: dict | None) -> InterruptedSchema | None:
    """What the player lost, for the operator to resume."""
    if not lost:
        return None
    programme = Programme.objects.filter(id=lost["programme_id"]).first()
    if programme is None:
        return None
    item = PlaylistItem.objects.filter(playlist__programme=programme, order=lost["order"]).first()
    return InterruptedSchema(
        programme_id=programme.id,
        programme_name=programme.name,
        position=lost["order"],
        item_title=_item(item).title if item else None,
        seconds=lost["seconds"],
    )


def _clock(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _features(programme: Programme) -> list[ProgrammeFeatureSchema]:
    features, seen = [], set()
    blocks = (
        programme.blocks.filter(content_type="movie", movie__isnull=False).select_related("movie").order_by("order")
    )
    for block in blocks:
        movie = block.movie
        if movie.id in seen:
            continue
        seen.add(movie.id)
        features.append(
            ProgrammeFeatureSchema(
                id=movie.id,
                title=movie.title,
                year=movie.year,
                certification=movie.certification or None,
                runtime_minutes=movie.runtime,
                thumbnail_url=movie.thumbnail_url,
            )
        )
    return features


def programme_info(programme: Programme) -> ProgrammeInfoSchema:
    return ProgrammeInfoSchema(
        id=programme.id,
        name=programme.name,
        description=programme.description,
        runtime_minutes=programme.get_total_runtime_minutes(),
        runtime_formatted=programme.get_formatted_runtime(),
        block_count=programme.blocks.count(),
        created_at=programme.created_at.isoformat() if programme.created_at else None,
        features=_features(programme),
    )


def _item(playlist_item) -> ItemSchema:
    from cinefin.api.services.playlist_utils import PlaylistUtils

    d = PlaylistUtils.build_playlist_item_details(playlist_item)
    return ItemSchema(
        type=d["type"],
        position=playlist_item.order,
        title=d["title"],
        duration=d["duration"] or None,
        details={"content_id": d["content_id"], "metadata": d["metadata"]},
    )


def _player(host: PlayoutHost | None) -> PlayerSchema | None:
    if host is None:
        return None
    return PlayerSchema(id=host.id, name=host.name, kind=host.kind, show_status=host.show_status)


def next_screening() -> NextScreeningSchema | None:
    """The next screening still to play, and when its lead-in cues it (after the
    minimum durations of the commands before its cue step)."""
    from cinefin.api.services import preshow

    now = timezone.now()
    upcoming = ProgrammeSchedule.objects.filter(status="scheduled", start_time__gte=now - timedelta(days=1))
    for s in upcoming.select_related("programme").order_by("start_time"):
        if s.play_time() < now:
            continue
        steps = preshow.steps(s.preshow)
        wait = sum(c.duration or 0 for c in Command.objects.filter(id__in=steps[: steps.index(preshow.CUE)]))
        return NextScreeningSchema(
            id=s.id,
            programme_id=s.programme_id,
            programme_name=s.programme.name,
            start_time=s.play_time(),
            cue_time=s.start_time + timedelta(seconds=wait),
        )
    return None


def playout_status() -> PlayoutStatusDataSchema:
    """Everything a surface shows about the player, worked out once."""
    from cinefin.api.mpv_service import mpv_service
    from cinefin.api.services import standby
    from cinefin.api.services.playlist_utils import PlaylistUtils

    host = PlayoutHost.get_active()
    snap = mpv_service.snapshot() if host else None
    phase = phase_of(snap)
    manual = list(mpv_service.manual_items)
    status = PlayoutStatusDataSchema(
        phase=phase,
        actions=allowed_actions(phase, bool(manual), bool(mpv_service.interrupted)),
        player=_player(host),
        next_screening=next_screening(),
        interrupted=_interrupted(mpv_service.interrupted),
    )
    if phase == OFFLINE:
        status.label = f"{host.name} is offline" if host else "No player is set up"
        return status
    if phase == STANDBY:
        status.screen, status.label = standby.resolve_ident()[3], "Standby"
        return status

    # The item's clock. A hold reports its own dwell: mpv's is the looping black clip.
    pos = snap["pos"]
    position, duration = snap["time"] or 0.0, snap["duration"] or 0.0
    hold = mpv_service._hold_progress
    if phase == HOLD and hold and hold.get("duration"):
        duration = float(hold["duration"])
        position = min(float(hold.get("elapsed", 0.0)), duration)
    status.playback = PlaybackStatusSchema(
        position=position,
        duration=duration,
        remaining=max(0.0, duration - position),
        percentage=round(position / duration * 100, 1) if duration > 0 else 0.0,
    )

    if manual:
        at = pos if pos is not None and 0 <= pos < len(manual) else None
        status.manual = ManualQueueSchema(items=[ManualItemSchema(**i) for i in manual], position=at)
        title = manual[at]["title"] if at is not None else ""
        status.screen = title
        status.label = (
            f"Paused · {title}" if phase == PAUSED else f"Manual · {(at or 0) + 1} of {len(manual)} · {title}"
        )
        return status

    programme, offset = mpv_service.current_programme, mpv_service.playlist_offset
    items = list(mpv_service.current_playlist.items.order_by("order"))
    shown = [i for i in items if i.content_type != "system"]  # not the end-of-programme sentinel
    order = pos - offset if pos is not None and pos >= offset else None
    current = items[order] if order is not None and order < len(items) else None
    upcoming = items[0 if order is None else order + 1 :][:1]
    timing = PlaylistUtils.calculate_playlist_timing(items, order, position if order is not None else None)
    status.programme = programme_info(programme)
    status.playlist = PlaylistStatusSchema(
        current_position=order,
        total_items=len(shown),
        mpv_position=pos,
        offset=offset,
        programme_total_duration=timing["total_duration"],
        programme_elapsed_time=timing["elapsed_time"],
        programme_remaining_time=timing["remaining_time"],
    )
    title_card = offset == 2 and pos == 1
    if current is not None:
        status.current_item = _item(current)
    elif title_card:
        status.current_item = ItemSchema(type="title", position=-1, title="Title card")
    if upcoming and upcoming[0].content_type != "system":
        status.next_item = _item(upcoming[0])

    title = status.current_item.title if status.current_item else ""
    if phase == CUED:
        status.screen = "Title card" if title_card else "Standby"
        status.label = f"Cued · {programme.name}"
    elif phase == PRESHOW:
        status.screen, status.label = "Title card", "Pre-show · Title card"
    elif phase == PAUSED and order is None:
        status.screen, status.label = "Title card", "Pre-show · paused"
    elif phase == HOLD:
        status.screen, status.label = "Black", f"Hold · {title}"
    elif phase == PAUSED:
        status.screen, status.label = title, f"Paused · {title} at {_clock(position)}"
    else:
        status.screen = title
        status.label = f"Item {order + 1} of {len(shown)} · {title}" if order is not None else "On air"
    return status
