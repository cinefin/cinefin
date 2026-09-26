"""Programme-level playout endpoints (load/run/stop); raw player controls live in mpv_ninja.py."""

import logging
import re
from typing import Any, Literal

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Playlist, PlaylistItem, PlayoutHost, Programme
from cinefin.api.mpv_service import mpv_service
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services.playlist_utils import PlaylistUtils
from cinefin.api.services.playout_agent_service import playout_agent_service
from cinefin.api.services.playout_service import PlayoutService, mark_programme_played

logger = logging.getLogger(__name__)


class ProgrammeFeatureSchema(Schema):
    id: int = Field(..., description="Movie ID")
    title: str = Field(..., description="Movie title")
    year: int | None = Field(None, description="Release year")
    certification: str | None = Field(None, description="Certificate for the active ratings system")
    runtime_minutes: int | None = Field(None, description="Runtime in minutes")
    thumbnail_url: str | None = Field(None, description="Poster URL")


class ProgrammeInfoSchema(Schema):
    id: int = Field(..., description="Programme ID")
    name: str = Field(..., description="Programme name")
    description: str = Field(..., description="Programme description")
    runtime_minutes: int = Field(..., description="Total runtime in minutes")
    runtime_formatted: str = Field(..., description="Formatted runtime string")
    block_count: int = Field(..., description="Number of blocks in programme")
    state: str = Field(..., description="Current programme state")
    created_at: str | None = Field(None, description="ISO timestamp of programme creation")
    features: list[ProgrammeFeatureSchema] = Field(
        default_factory=list, description="The programme's feature films, in running order"
    )


def _programme_features(programme: Programme) -> list[ProgrammeFeatureSchema]:
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


class PlaylistInfoSchema(Schema):
    id: int = Field(..., description="Playlist ID")
    item_count: int = Field(..., description="Number of items in playlist")
    created: bool = Field(..., description="Whether playlist was newly created")


class MPVStatusSchema(Schema):
    paused: bool = Field(..., description="Whether playback is paused")
    position: int = Field(..., description="Current playlist position")
    playlist_count: int = Field(..., description="Total items in MPV playlist")
    time_pos: float | None = Field(None, description="Current time position in seconds")
    duration: float | None = Field(None, description="Total duration in seconds")


class LoadProgrammeSchema(Schema):
    programme_id: int = Field(..., description="ID of programme to load")
    generate_playlist: bool | None = Field(True, description="Whether to generate playlist if missing")


class LoadProgrammeDataSchema(Schema):
    programme: ProgrammeInfoSchema = Field(..., description="Programme information")
    playlist: PlaylistInfoSchema = Field(..., description="Playlist information")
    status: str = Field(..., description="Load status")
    mpv_status: MPVStatusSchema = Field(..., description="MPV player status")
    warnings: list[str] = Field(
        default_factory=list, description="Pre-flight warnings: items whose media is unreachable"
    )


class LoadProgrammeResponseSchema(SuccessResponseSchema):
    data: LoadProgrammeDataSchema = Field(..., description="Programme load data")


class RunProgrammeDataSchema(Schema):
    programme: dict[str, Any] = Field(..., description="Programme information")
    status: str = Field(..., description="Programme status")
    actions: list[str] = Field(..., description="Actions performed")
    mpv_status: MPVStatusSchema = Field(..., description="MPV player status")


class RunProgrammeResponseSchema(SuccessResponseSchema):
    data: RunProgrammeDataSchema = Field(..., description="Programme run data")


class FeatureSchema(Schema):
    number: int = Field(..., description="Feature number in programme")
    movie_title: str = Field(..., description="Movie title")
    movie_id: int = Field(..., description="Movie ID")
    year: int | None = Field(None, description="Movie release year")
    certification: str | None = Field(None, description="Movie certification rating")


class PlaylistStatusSchema(Schema):
    current_position: int | None = Field(None, description="Current position in programme playlist")
    total_items: int = Field(..., description="Total items in playlist")
    progress_percentage: float = Field(..., description="Programme progress percentage")
    programme_total_duration: float = Field(..., description="Total duration of entire programme in seconds")
    programme_elapsed_time: float = Field(..., description="Elapsed time across entire programme in seconds")
    programme_remaining_time: float = Field(..., description="Remaining time in entire programme in seconds")
    programme_time_percentage: float = Field(..., description="Programme progress as time-based percentage")
    mpv_info: dict[str, Any] = Field(..., description="MPV-specific playlist information")


class CurrentItemSchema(Schema):
    type: str = Field(..., description="Type of current item (movie, trailer, etc.)")
    position: int = Field(..., description="Position in programme playlist")
    file: str = Field(..., description="File path of current item")
    title: str | None = Field(None, description="Title of current item")
    details: dict[str, Any] = Field(..., description="Type-specific item details")


class NextItemSchema(Schema):
    type: str = Field(..., description="Type of the upcoming item (movie, trailer, etc.)")
    title: str | None = Field(None, description="Title of the upcoming item")
    duration: float | None = Field(None, description="Duration of the upcoming item in seconds")


class PlaybackStatusSchema(Schema):
    state: str = Field(..., description="Playback state (playing, paused, stopped)")
    position: float = Field(..., description="Current playback position in seconds")
    duration: float = Field(..., description="Total duration in seconds")
    remaining: float = Field(..., description="Remaining time in seconds")
    percentage: float = Field(..., description="Playback progress percentage")


class PlayoutStatusDataSchema(Schema):
    programme: ProgrammeInfoSchema | None = Field(None, description="Current programme information")
    playlist: PlaylistStatusSchema | None = Field(None, description="Playlist status")
    current_item: CurrentItemSchema | None = Field(None, description="Currently playing item")
    next_item: NextItemSchema | None = Field(
        None, description="The upcoming playlist item (the readout's 'Next ·' foot)"
    )
    playback: PlaybackStatusSchema | None = Field(None, description="Playback status")
    executing_command: bool = Field(False, description="True while a hold-black command item is holding the screen")


class PlayoutStatusResponseSchema(SuccessResponseSchema):
    data: PlayoutStatusDataSchema = Field(..., description="Comprehensive playout status")


class StopPlayoutSchema(Schema):
    reset: bool | None = Field(False, description="Whether to reset to default state")


class StopPlayoutDataSchema(Schema):
    actions: list[str] = Field(..., description="Actions performed during stop")


class StopPlayoutResponseSchema(SuccessResponseSchema):
    data: StopPlayoutDataSchema = Field(..., description="Stop playout result")


class ControlPlayoutSchema(Schema):
    action: Literal["play", "pause", "toggle", "next", "previous", "seek"] = Field(
        ..., description="Playback control action"
    )
    position: float | None = Field(None, description="Seek position in seconds (required for seek action)")


class ControlPlayoutDataSchema(Schema):
    action: str = Field(..., description="Action that was performed")
    status: dict[str, Any] = Field(..., description="Current playback status")


class ControlPlayoutResponseSchema(SuccessResponseSchema):
    data: ControlPlayoutDataSchema = Field(..., description="Control action result")


class MPVPlaylistItemSchema(Schema):
    index: int = Field(..., description="Index in MPV playlist")
    title: str = Field(..., description="Item title")
    type: str = Field(..., description="Item type")
    file: str = Field(..., description="File path")
    duration: float | None = Field(None, description="Item duration in seconds")
    current: bool = Field(..., description="Whether this is the current item")
    programme_position: int | None = Field(None, description="Position in programme (excluding pre-show)")
    details: dict[str, Any] = Field(default_factory=dict, description="Additional item details and metadata")


class PlaylistDataSchema(Schema):
    playlist: list[MPVPlaylistItemSchema] = Field(..., description="Playlist items")
    current_index: int = Field(..., description="Current item index")
    total_items: int = Field(..., description="Total number of items")
    programme_offset: int = Field(..., description="Offset for programme items in MPV playlist")
    total_duration: float = Field(..., description="Total playlist duration in seconds")
    elapsed_time: float = Field(..., description="Elapsed time in seconds")
    remaining_time: float = Field(..., description="Remaining time in seconds")


class PlayoutPlaylistResponseSchema(SuccessResponseSchema):
    data: PlaylistDataSchema = Field(..., description="Playlist information")


class JumpPlaylistSchema(Schema):
    index: int | None = Field(None, description="MPV playlist index to jump to")
    programme_position: int | None = Field(
        None, description="Programme position to jump to (will be converted to MPV index)"
    )


class JumpPlaylistDataSchema(Schema):
    index: int = Field(..., description="MPV playlist index jumped to")
    programme_position: int | None = Field(None, description="Programme position (if applicable)")
    item: dict[str, Any] = Field(..., description="Information about jumped-to item")


class JumpPlayoutPlaylistResponseSchema(SuccessResponseSchema):
    data: JumpPlaylistDataSchema = Field(..., description="Playlist jump result")


playout_api = Router()


@playout_api.post(
    "/load",
    response={
        200: LoadProgrammeResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def load_programme(request: HttpRequest, data: LoadProgrammeSchema):
    try:
        programme = Programme.objects.get(pk=data.programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found") from None

    # A missing playlist is generated, and a stale one (blocks changed since it
    # was last built) is rebuilt, so playback always reflects the programme.
    playlist = Playlist.objects.filter(programme=programme).first()
    playlist_created = False

    if data.generate_playlist and (playlist is None or programme.playlist_stale):
        reason = "missing" if playlist is None else "stale"
        logger.info(f"Generating {reason} playlist for programme {data.programme_id}")
        from cinefin.api.services import ProgrammeService

        if ProgrammeService.refresh_playlist(programme) is None:
            raise UnprocessableEntityError("Failed to generate playlist — check the application logs")
        playlist = Playlist.objects.get(programme=programme)
        playlist_created = True
    elif playlist is None:
        raise ValidationError("Programme has no playlist. Set generate_playlist=true to create one.") from None

    from cinefin.api.services.playlist_service import PlaylistService

    preflight_warnings = PlaylistService.verify_playlist_availability(playlist)

    # If the playout agent manages the MPV process, make sure the player is
    # up before loading (best-effort; no-op when the agent is disabled).
    playout_agent_service.ensure_mpv_running()

    success = mpv_service.load_programme(programme)
    if not success:
        raise UnprocessableEntityError("Failed to load programme into playout system")

    mpv_status = mpv_service.get_status() or {}

    return Status(
        200,
        LoadProgrammeResponseSchema(
            success=True,
            data=LoadProgrammeDataSchema(
                programme=ProgrammeInfoSchema(
                    id=programme.id,
                    name=programme.name,
                    description=programme.description,
                    runtime_minutes=programme.get_total_runtime_minutes(),
                    runtime_formatted=programme.get_formatted_runtime(),
                    block_count=programme.blocks.count(),
                    state="loaded",
                ),
                playlist=PlaylistInfoSchema(
                    id=playlist.id, item_count=playlist.items.count(), created=playlist_created
                ),
                status="loaded",
                mpv_status=MPVStatusSchema(
                    paused=mpv_status.get("pause", True),
                    # get_status() always sets "playlist_pos", to None when mpv is
                    # idle — so a bare .get default never applies. Coerce here, or
                    # None flows into a required int field and pydantic 500s.
                    position=mpv_status.get("playlist_pos") or 0,
                    playlist_count=mpv_status.get("playlist_count") or 0,
                ),
                warnings=preflight_warnings,
            ),
        ),
    )


@playout_api.get(
    "/run",
    # One handler on two routes: without explicit ids both registrations derive
    # the same OpenAPI operation_id, which breaks schema consumers. Same below.
    operation_id="playout_run_programme_get",
    response={
        200: RunProgrammeResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
@playout_api.post(
    "/run",
    operation_id="playout_run_programme",
    response={
        200: RunProgrammeResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def run_programme(request: HttpRequest):
    if not mpv_service.current_programme:
        raise ValidationError("No programme loaded. Use /api/v2/playout/load first.")

    programme = mpv_service.current_programme
    actions = []

    success = mpv_service.start_programme()
    if success:
        actions.append("playback_started")
        mark_programme_played(programme.id)
    else:
        raise UnprocessableEntityError("Failed to start playback")

    mpv_status = mpv_service.get_status() or {}

    return Status(
        200,
        RunProgrammeResponseSchema(
            success=True,
            data=RunProgrammeDataSchema(
                programme={"id": programme.id, "name": programme.name},
                status="running",
                actions=actions,
                mpv_status=MPVStatusSchema(
                    paused=mpv_status.get("pause", False),
                    position=mpv_status.get("playlist_pos", 0),
                    playlist_count=mpv_status.get("playlist_count", 0),
                    time_pos=mpv_status.get("time_pos", 0),
                    duration=mpv_status.get("duration", 0),
                ),
            ),
        ),
    )


class PreshowCueInfoSchema(Schema):
    command: int = Field(..., description="Command ID")
    name: str = Field(..., description="Command name")
    lead: int = Field(..., description="Seconds before scheduled start it fires (0 = at start)")


class PreshowDataSchema(Schema):
    count: int = Field(..., description="Number of configured pre-show cues")
    cues: list[PreshowCueInfoSchema] = Field(default_factory=list, description="Configured cues, in order")


class PreshowResponseSchema(SuccessResponseSchema):
    data: PreshowDataSchema


class PreshowRunDataSchema(Schema):
    fired: int = Field(..., description="How many commands were fired")


class PreshowRunResponseSchema(SuccessResponseSchema):
    data: PreshowRunDataSchema


@playout_api.get("/preshow", response={200: PreshowResponseSchema})
def get_preshow(request: HttpRequest):
    """The configured pre-show cues (for the remote's manual trigger)."""
    from cinefin.api.models import Command
    from cinefin.api.services import preshow

    cue_list = preshow.cues()
    names = dict(Command.objects.filter(id__in=[c for c, _ in cue_list]).values_list("id", "name"))
    cues = [
        PreshowCueInfoSchema(command=cid, name=names.get(cid, f"Command {cid}"), lead=lead)
        for cid, lead in cue_list
        if cid in names
    ]
    return Status(200, PreshowResponseSchema(data=PreshowDataSchema(count=len(cues), cues=cues)))


@playout_api.post("/preshow/run", response={200: PreshowRunResponseSchema})
def run_preshow(request: HttpRequest):
    """Fire the whole pre-show sequence now, in order — independent of starting a programme."""
    from cinefin.api.services import preshow

    fired = preshow.fire_all()
    return Status(
        200,
        PreshowRunResponseSchema(message=f"Fired {fired} pre-show command(s)", data=PreshowRunDataSchema(fired=fired)),
    )


@playout_api.get(
    "/status", response={200: PlayoutStatusResponseSchema, 422: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def get_playout_status(request: HttpRequest):
    return Status(
        200, PlayoutStatusResponseSchema(message="Playout status retrieved successfully", data=_playout_status_data())
    )


def _playout_status_data() -> "PlayoutStatusDataSchema":
    """Full playout status payload — shared by GET /playout/status and the WebSocket so their wire shapes can't drift."""
    enhanced_status = mpv_service.get_enhanced_status()
    mpv_status = mpv_service.get_status() or {}

    response_data = PlayoutStatusDataSchema(
        programme=None,
        playlist=None,
        current_item=None,
        next_item=None,
        playback=None,
        executing_command=mpv_service.executing_command,
    )

    if mpv_service.current_programme:
        programme = mpv_service.current_programme

        response_data.programme = ProgrammeInfoSchema(
            id=programme.id,
            name=programme.name,
            description=programme.description,
            runtime_minutes=programme.get_total_runtime_minutes(),
            runtime_formatted=programme.get_formatted_runtime(),
            block_count=programme.blocks.count(),
            state=enhanced_status["programme"]["state"],
            created_at=programme.created_at.isoformat(),
            features=_programme_features(programme),
        )

    if mpv_service.current_playlist:
        playlist = mpv_service.current_playlist
        mpv_position = mpv_status.get("playlist_pos", 0)
        programme_position = None

        if mpv_position >= mpv_service.playlist_offset:
            programme_position = mpv_position - mpv_service.playlist_offset

        total_items = playlist.items.count()
        progress_percentage = 0
        if programme_position is not None and total_items > 0:
            progress_percentage = round((programme_position / total_items) * 100, 1)

        timing = PlayoutService.calculate_programme_timing(
            playlist, programme_position, mpv_status.get("time_pos", 0) or 0
        )

        response_data.playlist = PlaylistStatusSchema(
            current_position=programme_position,
            total_items=total_items,
            progress_percentage=progress_percentage,
            programme_total_duration=timing["total_duration"],
            programme_elapsed_time=timing["elapsed_time"],
            programme_remaining_time=timing["remaining_time"],
            programme_time_percentage=timing["time_percentage"],
            mpv_info={"mpv_position": mpv_position, "offset": mpv_service.playlist_offset},
        )

        # During pre-show there is no programme item yet (opening title card /
        # System Ident is on screen) — describe that instead.
        if mpv_service.in_preshow(mpv_status):
            opening_file = mpv_status.get("file_path") or ""
            response_data.current_item = CurrentItemSchema(
                type="title" if "/stream/title/" in opening_file else "ident",
                position=-1,  # outside the programme; the SPA's "no position" sentinel
                file=opening_file,
                title=mpv_service._preshow_title(opening_file),
                details={},
            )
        elif programme_position is not None and programme_position >= 0:
            try:
                current_item = playlist.items.get(order=programme_position)
                item_info = CurrentItemSchema(
                    type=current_item.content_type, position=programme_position, file=current_item.file, details={}
                )

                if current_item.content_type == "movie":
                    movie_playback = current_item.content_object
                    movie = movie_playback.movie
                    item_info.title = movie.title
                    item_info.details = {
                        "movie_id": movie.id,
                        "year": movie.year,
                        "certification": movie.certification,
                        "director": movie.director,
                        "runtime_minutes": movie.runtime,
                        "thumbnail_url": movie.thumbnail_url,
                        "audio_track": movie_playback.audio_track_index,
                        "subtitle_track": movie_playback.subtitle_track_index,
                    }
                elif current_item.content_type == "command":
                    command = current_item.content_object
                    item_info.title = command.name
                    item_info.details = {"provider": command.provider}
                elif current_item.content_type == "certification":
                    cert = current_item.content_object
                    item_info.title = f"Certification: {cert.certification}"
                    item_info.details = {
                        "certification": cert.certification,
                        "movie_title": cert.movie_title if hasattr(cert, "movie_title") else None,
                    }
                elif current_item.content_type == "bumper":
                    bumper = current_item.content_object
                    item_info.title = bumper.title
                    item_info.details = {
                        "duration": bumper.duration,
                        "tags": [tag.name for tag in bumper.tags.all()] if bumper.tags.exists() else [],
                    }
                elif current_item.content_type == "trailer":
                    trailer = current_item.content_object
                    item_info.title = trailer.title
                    item_info.details = {
                        "year": trailer.year,
                        "content_rating": trailer.content_rating,
                        "duration": trailer.duration,
                    }
                else:
                    item_info.title = getattr(current_item.content_object, "title", "Unknown")
                    item_info.details = {}

                response_data.current_item = item_info

            except PlaylistItem.DoesNotExist:
                logger.warning(f"Playlist item not found at position {programme_position}")
            except Exception as e:
                logger.error(f"Error getting current playlist item: {e}")

        # During pre-show (position None) the whole programme is still ahead: next is order 0.
        next_order = 0 if programme_position is None else programme_position + 1
        try:
            upcoming = playlist.items.get(order=next_order)
            details = PlaylistUtils.build_playlist_item_details(upcoming)
            response_data.next_item = NextItemSchema(
                type=details["type"], title=details["title"], duration=details["duration"]
            )
        except PlaylistItem.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Error getting next playlist item: {e}")

    if enhanced_status["playback"]:
        playback = enhanced_status["playback"]
        position = playback.get("position", 0) or 0
        duration = playback.get("duration", 0) or 0

        # Player state only (playing/paused/stopped). Pre-show is a programme
        # state reported above; mixing it in here wedged the footer's play/pause.
        if mpv_service.programme_state == "not_loaded":
            state = "stopped"
        else:
            state = playback.get("state", "stopped")

        percentage = 0
        if duration > 0:
            percentage = round((position / duration) * 100, 1)

        response_data.playback = PlaybackStatusSchema(
            state=state,
            position=float(position),
            duration=float(duration),
            remaining=float(playback.get("remaining") or 0),
            percentage=float(percentage),
        )

    return response_data


@playout_api.post("/stop", response={200: StopPlayoutResponseSchema, 500: ErrorResponseSchema})
def stop_playout(request: HttpRequest, data: StopPlayoutSchema):
    actions = []

    if mpv_service.running:
        mpv_service.stop_programme()
        actions.append("playback_stopped")

    if data.reset:
        try:
            mpv_service.reset()
            actions.append("reset_complete")
        except Exception as e:
            logger.error(f"Failed to reset: {e}")
            actions.append("reset_failed")

    return Status(200, StopPlayoutResponseSchema(success=True, data=StopPlayoutDataSchema(actions=actions)))


@playout_api.post("/reset", response={200: MessageResponseSchema, 422: ErrorResponseSchema})
def reset_playout(request: HttpRequest):
    """Return the player to its idle state: clear any loaded programme and show the paused ident."""
    if not mpv_service.reset():
        raise UnprocessableEntityError("Could not reach the player", error_code="PLAYER_UNREACHABLE")
    return Status(200, MessageResponseSchema(message="Player reset to the idle ident"))


@playout_api.post(
    "/control",
    response={
        200: ControlPlayoutResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def control_playout(request: HttpRequest, data: ControlPlayoutSchema):
    success = False

    if data.action == "play":
        success = mpv_service.play()
    elif data.action == "pause":
        success = mpv_service.pause()
    elif data.action == "toggle":
        success = mpv_service.toggle_pause()
    elif data.action == "next":
        success = mpv_service.next()
    elif data.action == "previous":
        success = mpv_service.previous()
    elif data.action == "seek":
        if data.position is None:
            raise ValidationError("position is required for seek action")
        success = mpv_service.seek(data.position)

    if not success:
        raise UnprocessableEntityError(f"Failed to execute action: {data.action}")

    mpv_status = mpv_service.get_status() or {}

    return Status(
        200,
        ControlPlayoutResponseSchema(
            success=True,
            data=ControlPlayoutDataSchema(
                action=data.action,
                status={
                    "state": "paused" if mpv_status.get("pause", True) else "playing",
                    "position": mpv_status.get("time_pos", 0),
                    "duration": mpv_status.get("duration", 0),
                    "playlist_pos": mpv_status.get("playlist_pos", 0),
                },
            ),
        ),
    )


@playout_api.get(
    "/playlist",
    operation_id="playout_get_playlist",
    response={200: PlayoutPlaylistResponseSchema, 500: ErrorResponseSchema},
)
@playout_api.post(
    "/playlist",
    operation_id="playout_jump_playlist",
    response={
        200: JumpPlayoutPlaylistResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def control_playlist(request: HttpRequest, data: JumpPlaylistSchema = None):
    """GET: current playlist. POST: jump to playlist item."""
    if request.method == "GET":
        playlist_info = mpv_service.get_playlist_info()
        raw_playlist = playlist_info.get("playlist", [])
        current_index = playlist_info.get("current_index", 0)
        programme_offset = playlist_info.get("programme_offset", 0)

        enhanced_playlist = []
        current_playlist = mpv_service.current_playlist

        for item in raw_playlist:
            enhanced_item = PlaylistUtils.enhance_mpv_playlist_item(item, current_playlist)
            enhanced_playlist.append(enhanced_item)

        timing_info = {"total_duration": 0.0, "elapsed_time": 0.0, "remaining_time": 0.0}

        if current_playlist and current_index >= programme_offset:
            try:
                current_programme_position = current_index - programme_offset
                current_time_pos = mpv_service.get_status().get("time", 0) or 0

                playlist_items = current_playlist.items.all().order_by("order")
                timing_info = PlaylistUtils.calculate_playlist_timing(
                    playlist_items, current_programme_position, current_time_pos
                )
            except Exception as e:
                logger.warning(f"Could not calculate timing information: {e}")

        return Status(
            200,
            PlayoutPlaylistResponseSchema(
                success=True,
                data=PlaylistDataSchema(
                    playlist=enhanced_playlist,
                    current_index=current_index,
                    total_items=playlist_info.get("total_items", 0),
                    programme_offset=programme_offset,
                    total_duration=timing_info["total_duration"],
                    elapsed_time=timing_info["elapsed_time"],
                    remaining_time=timing_info["remaining_time"],
                ),
            ),
        )

    else:  # POST
        if not data:
            raise ValidationError("Request body is required for POST")

        mpv_index = data.index
        programme_position = data.programme_position

        if mpv_index is None and programme_position is None:
            raise ValidationError("Either index or programme_position is required")

        if programme_position is not None:
            if not isinstance(programme_position, int) or programme_position < 0:
                raise ValidationError("programme_position must be a non-negative integer")

            mpv_index = programme_position + mpv_service.playlist_offset

        if not isinstance(mpv_index, int) or mpv_index < 0:
            raise ValidationError("index must be a non-negative integer")

        success = mpv_service.playlist_jump(mpv_index)

        if not success:
            raise UnprocessableEntityError(f"Failed to jump to playlist item {mpv_index}")

        item_info = {}
        actual_programme_position = None

        if mpv_index >= mpv_service.playlist_offset:
            actual_programme_position = mpv_index - mpv_service.playlist_offset

        try:
            playlist_info = mpv_service.get_playlist_info()
            playlist = playlist_info.get("playlist", [])
            if mpv_index < len(playlist):
                item_info = playlist[mpv_index]
        except Exception:
            pass

        return Status(
            200,
            JumpPlayoutPlaylistResponseSchema(
                success=True,
                data=JumpPlaylistDataSchema(
                    index=mpv_index, programme_position=actual_programme_position, item=item_info
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Playout agent (cinefin-playout) — manages the MPV *process* on the playout
# host. Playback control stays on the IPC socket; these endpoints only start,
# stop and inspect the player instance itself.
# ---------------------------------------------------------------------------


class AgentStatusDataSchema(Schema):
    enabled: bool = Field(description="Whether agent management is enabled in settings")
    reachable: bool = Field(description="Whether the agent answered")
    agent_version: str | None = Field(default=None, description="Agent version")
    mpv_running: bool = Field(default=False, description="Whether an MPV instance is up")
    mpv_mode: str | None = Field(default=None, description="child, external or stopped")
    mpv_pid: int | None = Field(default=None, description="MPV process ID (child mode)")
    uptime_seconds: float | None = Field(default=None, description="MPV uptime in seconds")
    restarts: int = Field(default=0, description="Crash-restarts performed by the agent")
    socket_responding: bool = Field(default=False, description="MPV answering on the IPC socket")
    autostart: bool | None = Field(default=None, description="Agent launches MPV at its own boot")
    config_pushed_at: float | None = Field(default=None, description="Unix time of the last config push")
    error: str | None = Field(default=None, description="Why the agent is unreachable, if it is")


class AgentStatusResponseSchema(SuccessResponseSchema):
    data: AgentStatusDataSchema = Field(..., description="Playout agent status")


class AgentActionDataSchema(Schema):
    ok: bool = Field(description="Whether the action succeeded")
    action_message: str = Field(description="Agent's description of what happened")
    mpv_running: bool = Field(description="Whether MPV is running after the action")


class AgentActionResponseSchema(SuccessResponseSchema):
    data: AgentActionDataSchema = Field(..., description="Agent action result")


@playout_api.get("/agent/status", response={200: AgentStatusResponseSchema, 500: ErrorResponseSchema})
def get_agent_status(request: HttpRequest):
    """Status of the playout agent and its MPV process (unreachable/disabled is a result, always 200)."""
    active = PlayoutHost.get_active()
    if active is not None and active.kind == PlayoutHost.KIND_LOCAL_SOCKET:
        # No agent to poll — reachability is "is a local mpv answering on the
        # socket". There is no separate process query, so mpv_running == reachable.
        from cinefin.api.mpv_socket import probe_socket

        reachable, err = probe_socket(active.socket_path)
        return Status(
            200,
            AgentStatusResponseSchema(
                message="Local mpv reachable" if reachable else "Local mpv unreachable",
                data=AgentStatusDataSchema(
                    enabled=True,
                    reachable=reachable,
                    mpv_running=reachable,
                    socket_responding=reachable,
                    error=None if reachable else (err or "mpv is not answering on the socket"),
                ),
            ),
        )
    if not playout_agent_service.is_configured():
        return Status(
            200,
            AgentStatusResponseSchema(
                message="No playout host configured",
                data=AgentStatusDataSchema(enabled=False, reachable=False),
            ),
        )
    try:
        status = playout_agent_service.get_status()
    except UnprocessableEntityError as e:
        return Status(
            200,
            AgentStatusResponseSchema(
                message="Playout agent unreachable",
                data=AgentStatusDataSchema(enabled=True, reachable=False, error=e.message),
            ),
        )
    mpv = status.get("mpv", {})
    return Status(
        200,
        AgentStatusResponseSchema(
            message="Playout agent status retrieved",
            data=AgentStatusDataSchema(
                enabled=True,
                reachable=True,
                agent_version=status.get("agent_version"),
                mpv_running=bool(mpv.get("running")),
                mpv_mode=mpv.get("mode"),
                mpv_pid=mpv.get("pid"),
                uptime_seconds=mpv.get("uptime_seconds"),
                restarts=mpv.get("restarts", 0),
                socket_responding=bool(mpv.get("socket_responding")),
                autostart=status.get("autostart"),
                config_pushed_at=status.get("config_pushed_at"),
            ),
        ),
    )


def _agent_action(action: str) -> AgentActionResponseSchema:
    active = PlayoutHost.get_active()
    if active is not None and active.kind == PlayoutHost.KIND_LOCAL_SOCKET:
        raise UnprocessableEntityError(
            "Starting, stopping and restarting the player needs the playout agent — "
            "a local mpv host is run and stopped by you.",
            error_code="AGENT_REQUIRED",
        )
    if not playout_agent_service.is_configured():
        raise UnprocessableEntityError(
            "No playout host is configured — add one on the Playout settings page", error_code="AGENT_DISABLED"
        )
    operations = {
        "start": playout_agent_service.start_mpv,
        "stop": playout_agent_service.stop_mpv,
        "restart": playout_agent_service.restart_mpv,
    }
    result = operations[action]()
    return AgentActionResponseSchema(
        message=f"MPV {action} requested",
        data=AgentActionDataSchema(
            ok=bool(result.get("ok")),
            action_message=result.get("message", ""),
            mpv_running=bool(result.get("status", {}).get("running")),
        ),
    )


@playout_api.post("/agent/start", response={200: AgentActionResponseSchema, 422: ErrorResponseSchema})
def agent_start_mpv(request: HttpRequest):
    """Start MPV via the playout agent (pushes the current launch config)."""
    result = _agent_action("start")
    # The player just came up — show the idle ident straight away.
    mpv_service.show_idle()
    return Status(200, result)


@playout_api.post("/agent/stop", response={200: AgentActionResponseSchema, 422: ErrorResponseSchema})
def agent_stop_mpv(request: HttpRequest):
    """Stop MPV via the playout agent (graceful quit, then terminate)."""
    return Status(200, _agent_action("stop"))


@playout_api.post("/agent/restart", response={200: AgentActionResponseSchema, 422: ErrorResponseSchema})
def agent_restart_mpv(request: HttpRequest):
    """Restart MPV via the playout agent (pushes the current launch config)."""
    return Status(200, _agent_action("restart"))


# Playout hosts — manage cinefin-playout agent host(s) and proxy their
# host-owned graphics/audio config + hardware enumeration.
from cinefin.api.schemas.base import MessageResponseSchema  # noqa: E402
from cinefin.api.services.playout_host_service import playout_host_service  # noqa: E402


class PlayoutHostSchema(Schema):
    id: int
    name: str
    kind: str = Field(default="agent", description="'agent' (WebSocket) or 'local_socket' (local mpv JSON-IPC)")
    base_url: str
    socket_path: str = ""
    has_token: bool = Field(description="Whether a bearer token is set (the token itself is never returned)")
    enabled: bool
    is_active: bool
    last_seen_at: str | None = None
    agent_version: str = ""
    os: str = ""
    arch: str = ""


class PlayoutHostListResponse(SuccessResponseSchema):
    data: list[PlayoutHostSchema]


class PlayoutHostResponse(SuccessResponseSchema):
    data: PlayoutHostSchema


class HostConfigResponse(SuccessResponseSchema):
    data: dict  # proxied opaquely — the agent owns the schema


class HostGraphicsSchema(Schema):
    mode: str = Field("desktop", description='"desktop" (X/Wayland session) or "drm" (headless KMS)')
    vo: str = Field("gpu-next", description="mpv video output driver")
    gpu_api: str = Field("", description='"" = mpv default; e.g. "d3d11", "vulkan"')
    gpu_context: str = Field("", description='"" = auto; e.g. "displayvk", "drm"')
    hwdec: str = Field("auto", description="hardware decoding: auto / auto-safe / no / nvdec / vaapi / …")
    screen: int = Field(0, description="desktop mode: which display index to fullscreen on")
    drm_connector: str = Field("", description='drm mode: e.g. "HDMI-A-1" (required in drm mode)')
    drm_mode: str = Field("", description='drm mode: optional pinned mode, e.g. "1920x1080@60"')
    fullscreen: bool = True
    hdr_passthrough: bool = Field(True, description="send HDR to the display instead of tone-mapping to SDR")
    osc: bool = Field(False, description="mpv's own on-screen controller")
    display: str = Field("", description='desktop mode: X display, e.g. ":0"; empty for drm')
    idle_media: str = Field("", description="Cinefin-owned: the System Ident stream URL")


class HostAudioSchema(Schema):
    device: str = Field("", description='"" = mpv default; else a device id from /hardware')
    channels: str = Field("auto", description="auto / stereo / 5.1 / 7.1")
    spdif_passthrough: list[str] = Field(
        default_factory=list, description='codecs bitstreamed untouched, e.g. ["ac3", "dts"]'
    )
    max_volume: int = Field(130, ge=0, description="mpv volume-max (percent)")


class HostLaunchConfigSchema(Schema):
    autostart: bool = Field(True, description="launch mpv when the agent boots")
    graphics: HostGraphicsSchema = Field(default_factory=HostGraphicsSchema)
    audio: HostAudioSchema = Field(default_factory=HostAudioSchema)


class HostLaunchConfigResponse(SuccessResponseSchema):
    data: HostLaunchConfigSchema


class HostConfigSavedSchema(Schema):
    restart_required: bool = Field(False, description="the change applies on the next player restart")


class HostConfigSavedResponse(SuccessResponseSchema):
    data: HostConfigSavedSchema


class HostScreenSchema(Schema):
    index: int
    name: str = ""
    w: int = 0
    h: int = 0
    hz: float = 0.0


class HostAudioDeviceSchema(Schema):
    name: str
    description: str = ""


class HostMPVInfoSchema(Schema):
    version: str = ""
    vo: list[str] = Field(default_factory=list)
    gpu_apis: list[str] = Field(default_factory=list)


class HostHardwareSchema(Schema):
    audio_devices: list[HostAudioDeviceSchema] = Field(default_factory=list)
    drm_connectors: list[str] = Field(default_factory=list)
    screens: list[HostScreenSchema] = Field(default_factory=list)
    mpv: HostMPVInfoSchema = Field(default_factory=HostMPVInfoSchema)
    note: str = Field("", description="why a list is empty, e.g. no mpv binary found")


class HostHardwareResponse(SuccessResponseSchema):
    data: HostHardwareSchema


class IdleMediaInput(Schema):
    # A Schema (not a bare dict param) so the JSON body maps here rather than the query string.
    idle_media: str = ""


class PlayoutHostInput(Schema):
    name: str | None = None
    kind: str | None = Field(default=None, description="'agent' or 'local_socket' (defaults to 'agent' on create)")
    base_url: str | None = None
    socket_path: str | None = None
    token: str | None = Field(default=None, description="Bearer token; omit to leave unchanged, '' to clear")
    enabled: bool | None = None
    is_active: bool | None = None


def _host_schema(host: PlayoutHost) -> PlayoutHostSchema:
    return PlayoutHostSchema(
        id=host.id,
        name=host.name,
        kind=host.kind,
        base_url=host.base_url,
        socket_path=host.socket_path or "",
        has_token=bool(host.token),
        enabled=host.enabled,
        is_active=host.is_active,
        last_seen_at=host.last_seen_at.isoformat() if host.last_seen_at else None,
        agent_version=host.agent_version or "",
        os=host.os or "",
        arch=host.arch or "",
    )


@playout_api.get("/hosts", response={200: PlayoutHostListResponse})
def list_playout_hosts(request: HttpRequest):
    return Status(
        200, PlayoutHostListResponse(message="Playout hosts", data=[_host_schema(h) for h in PlayoutHost.objects.all()])
    )


@playout_api.post("/hosts", response={200: PlayoutHostResponse, 400: ErrorResponseSchema})
def create_playout_host(request: HttpRequest, data: PlayoutHostInput):
    name = (data.name or "").strip()
    kind = (data.kind or PlayoutHost.KIND_AGENT).strip()
    if kind not in {PlayoutHost.KIND_AGENT, PlayoutHost.KIND_LOCAL_SOCKET}:
        raise ValidationError("Unknown host kind", details={"field": "kind"})
    base_url = (data.base_url or "").strip()
    socket_path = (data.socket_path or "").strip()
    if not name:
        raise ValidationError("Name is required", details={"field": "name"})
    if kind == PlayoutHost.KIND_LOCAL_SOCKET:
        if not socket_path:
            raise ValidationError("A local mpv host needs a socket path", details={"field": "socket_path"})
    else:
        if not base_url:
            raise ValidationError("Name and agent URL are required", details={"field": "base_url"})
        if not re.match(r"^https?://", base_url):
            raise ValidationError("Agent URL must start with http:// or https://", details={"field": "base_url"})
    # Activate the new host when nothing is active yet — covers a fresh box
    # (whose seeded loopback host is inactive) so playout works immediately.
    activate = bool(data.is_active) or PlayoutHost.get_active() is None
    host = PlayoutHost.objects.create(
        name=name,
        kind=kind,
        base_url=base_url or PlayoutHost._meta.get_field("base_url").default,
        socket_path=socket_path,
        token=data.token or "",
        enabled=data.enabled if data.enabled is not None else True,
        is_active=activate,
    )
    if activate:
        # Push the streamed cinema ident as the idle screen so the host needs no
        # local ident file (best-effort; agent may be down).
        playout_agent_service.resync_idle_media()
    return Status(200, PlayoutHostResponse(message="Playout host added", data=_host_schema(host)))


@playout_api.patch(
    "/hosts/{host_id}", response={200: PlayoutHostResponse, 400: ErrorResponseSchema, 404: ErrorResponseSchema}
)
def update_playout_host(request: HttpRequest, host_id: int, data: PlayoutHostInput):
    try:
        host = PlayoutHost.objects.get(pk=host_id)
    except PlayoutHost.DoesNotExist:
        raise NotFoundError("Playout host not found") from None
    if data.name is not None:
        host.name = data.name.strip() or host.name
    if data.kind is not None:
        if data.kind not in {PlayoutHost.KIND_AGENT, PlayoutHost.KIND_LOCAL_SOCKET}:
            raise ValidationError("Unknown host kind", details={"field": "kind"})
        host.kind = data.kind
    if data.base_url is not None:
        base_url = data.base_url.strip()
        if base_url and not re.match(r"^https?://", base_url):
            raise ValidationError("Agent URL must start with http:// or https://", details={"field": "base_url"})
        host.base_url = base_url
    if data.socket_path is not None:
        host.socket_path = data.socket_path.strip()
    if data.token is not None:
        host.token = data.token
    if data.enabled is not None:
        host.enabled = data.enabled
    if data.is_active:
        host.is_active = True  # save() clears the flag on the others
    # A local mpv host needs a socket path to be usable.
    if host.kind == PlayoutHost.KIND_LOCAL_SOCKET and not (host.socket_path or "").strip():
        raise ValidationError("A local mpv host needs a socket path", details={"field": "socket_path"})
    host.save()
    return Status(200, PlayoutHostResponse(message="Playout host updated", data=_host_schema(host)))


@playout_api.post("/hosts/{host_id}/activate", response={200: PlayoutHostResponse, 404: ErrorResponseSchema})
def activate_playout_host(request: HttpRequest, host_id: int):
    try:
        host = PlayoutHost.objects.get(pk=host_id)
    except PlayoutHost.DoesNotExist:
        raise NotFoundError("Playout host not found") from None
    # Switching hosts: unload the programme (it belongs to the old host's player)
    # and drop the control link, while the controller still points at the old host.
    current = PlayoutHost.get_active()
    if current is not None and current.id != host.id:
        mpv_service.unload_for_host_switch()
    host.is_active = True
    host.save()
    playout_agent_service.resync_idle_media()
    # Connecting a player shows the idle ident straight away, rather than
    # waiting for the next status poll to lazily connect.
    mpv_service.show_idle()
    return Status(200, PlayoutHostResponse(message="Playout host activated", data=_host_schema(host)))


@playout_api.post("/hosts/{host_id}/refresh", response={200: PlayoutHostResponse, 404: ErrorResponseSchema})
def refresh_playout_host(request: HttpRequest, host_id: int):
    try:
        host = PlayoutHost.objects.get(pk=host_id)
    except PlayoutHost.DoesNotExist:
        raise NotFoundError("Playout host not found") from None
    playout_host_service.refresh(host)
    host.refresh_from_db()
    return Status(200, PlayoutHostResponse(message="Playout host refreshed", data=_host_schema(host)))


@playout_api.delete("/hosts/{host_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema})
def delete_playout_host(request: HttpRequest, host_id: int):
    try:
        host = PlayoutHost.objects.get(pk=host_id)
    except PlayoutHost.DoesNotExist:
        raise NotFoundError("Playout host not found") from None
    was_active = host.is_active
    name = host.name
    host.delete()
    if was_active:
        nxt = PlayoutHost.objects.first()
        if nxt:
            nxt.is_active = True
            nxt.save()
    return Status(200, MessageResponseSchema(message=f"Playout host '{name}' removed"))


# Host-owned graphics/audio config: addressed per host (belongs to the machine),
# validated + persisted by the agent to its own config.toml (the source of truth).
def _host_or_404(host_id: int) -> PlayoutHost:
    host = PlayoutHost.objects.filter(pk=host_id).first()
    if host is None:
        raise NotFoundError("Playout host not found", error_code="HOST_NOT_FOUND")
    return host


@playout_api.get(
    "/hosts/{host_id}/config",
    response={200: HostLaunchConfigResponse, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def get_host_launch_config(request: HttpRequest, host_id: int):
    """One host's launch config (autostart, graphics, audio), read from that machine's agent."""
    data = playout_agent_service.get_host_config(_host_or_404(host_id))
    return Status(200, HostLaunchConfigResponse(message="Host launch config", data=data))


@playout_api.put(
    "/hosts/{host_id}/config",
    response={200: HostConfigSavedResponse, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def put_host_launch_config(request: HttpRequest, host_id: int, body: HostLaunchConfigSchema):
    """Replace one host's launch config; the agent validates it and writes its config.toml (applies on next restart)."""
    host = _host_or_404(host_id)
    saved = playout_agent_service.put_host_config(host, body.dict())
    return Status(200, HostConfigSavedResponse(message="Host config saved", data=saved))


@playout_api.get(
    "/hosts/{host_id}/hardware",
    response={200: HostHardwareResponse, 404: ErrorResponseSchema, 422: ErrorResponseSchema},
)
def get_host_hardware(request: HttpRequest, host_id: int):
    """What one host actually has (audio devices, DRM connectors, screens, mpv caps), enumerated on demand."""
    data = playout_agent_service.get_hardware(_host_or_404(host_id))
    return Status(200, HostHardwareResponse(message="Host hardware", data=data))


@playout_api.get("/host/config", response={200: HostConfigResponse, 422: ErrorResponseSchema})
def get_host_config(request: HttpRequest):
    return Status(200, HostConfigResponse(message="Host config", data=playout_agent_service.get_hostconfig()))


@playout_api.put("/host/idle-media", response={200: HostConfigResponse, 422: ErrorResponseSchema})
def put_host_idle_media(request: HttpRequest, body: IdleMediaInput):
    """Push only the idle-screen media (the cinema ident)."""
    return Status(
        200,
        HostConfigResponse(message="Idle media saved", data=playout_agent_service.put_idle_media(body.idle_media)),
    )
