"""MPV Control API: raw player settings (volume, speed, tracks, properties).

What plays, and every transport action, is playout_ninja.py (GET /playout/status,
POST /playout/control); both drive mpv_service directly.
"""

import logging
from typing import Any, Literal

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.mpv_service import mpv_service
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema

logger = logging.getLogger(__name__)


class TrackSchema(Schema):
    id: int = Field(..., description="Track ID")
    language: str | None = Field(None, description="Track language code")
    title: str | None = Field(None, description="Track title/name")
    codec: str | None = Field(None, description="Track codec")
    selected: bool = Field(..., description="Whether this track is currently selected")


class MPVStatusSchema(Schema):
    volume: int | None = Field(None, description="Current volume level (0-100)")
    muted: bool | None = Field(None, description="Whether audio is muted")
    speed: float | None = Field(None, description="Playback speed multiplier")
    fullscreen: bool | None = Field(None, description="Whether MPV is in fullscreen mode")
    panscan: float | None = Field(
        None, description="mpv panscan: 0 fits the whole picture, 1 zooms to fill the screen (crops wide films)"
    )


class TracksInfoSchema(Schema):
    audio_tracks: list[TrackSchema] = Field(..., description="Available audio tracks")
    sub_tracks: list[TrackSchema] = Field(..., description="Available subtitle tracks")
    video_tracks: list[TrackSchema] = Field(..., description="Available video tracks")


class VideoTechInfoSchema(Schema):
    width: int | None = Field(None, description="Video width in pixels")
    height: int | None = Field(None, description="Video height in pixels")
    fps: float | None = Field(None, description="Frame rate")
    codec: str | None = Field(None, description="Video codec")
    pixelformat: str | None = Field(None, description="Pixel format")
    colormatrix: str | None = Field(None, description="Color matrix/space")
    colorlevels: str | None = Field(None, description="Color levels")
    primaries: str | None = Field(None, description="Color primaries")
    gamma: str | None = Field(None, description="Gamma/transfer function")
    hw_decoding: str | None = Field(None, description="Hardware decoding method in use")


class AudioTechInfoSchema(Schema):
    codec: str | None = Field(None, description="Audio codec")
    channels: str | None = Field(None, description="Audio channel layout (e.g., 'stereo', '5.1')")
    samplerate: int | None = Field(None, description="Audio sample rate in Hz")


class MPVStatusDataSchema(Schema):
    """Raw player settings the programme status doesn't carry (what plays, and whether it is
    paused, is GET /playout/status)."""

    status: MPVStatusSchema | None = Field(None, description="Volume, mute, speed and fullscreen")
    tracks: TracksInfoSchema = Field(..., description="Available media tracks")
    connected: bool = Field(..., description="Whether MPV is connected")
    video: VideoTechInfoSchema | None = Field(None, description="Video technical information")
    audio: AudioTechInfoSchema | None = Field(None, description="Audio technical information")


class MPVStatusResponseSchema(SuccessResponseSchema):
    data: MPVStatusDataSchema = Field(..., description="MPV status data")


class PlaybackControlSchema(Schema):
    action: Literal["play", "pause", "stop", "toggle"] = Field(..., description="Playback control action")


class SeekControlSchema(Schema):
    position: float = Field(..., description="Seek position (seconds for absolute/relative, 0-100 for percentage)")
    type: Literal["absolute", "relative", "percentage"] = Field("absolute", description="Type of seek operation")


class VolumeControlSchema(Schema):
    action: Literal["set", "up", "down", "mute"] = Field(..., description="Volume control action")
    volume: int | None = Field(None, description="Volume level (0-100) for 'set' action")


class TrackControlSchema(Schema):
    type: Literal["audio", "sub"] = Field(..., description="Track type to control")
    track_id: str | int = Field(..., description="Track ID or 'no' to disable subtitles")


class PlaylistControlSchema(Schema):
    action: Literal["next", "prev", "jump"] = Field(..., description="Playlist navigation action")
    index: int | None = Field(None, description="Playlist index for 'jump' action")


class SpeedControlSchema(Schema):
    speed: float = Field(..., description="Playback speed multiplier (e.g., 1.0 for normal, 2.0 for double)")


class ChapterControlSchema(Schema):
    action: Literal["next", "prev", "jump"] = Field(..., description="Chapter navigation action")
    chapter: int | None = Field(None, description="Chapter number for 'jump' action")


class MPVCommandSchema(Schema):
    command: str = Field(..., description="MPV command to execute")
    args: list[Any] | None = Field(default=[], description="Command arguments")


class PropertySchema(Schema):
    value: Any = Field(..., description="Property value to set")


mpv_api = Router()


@mpv_api.get(
    "/status",
    response={
        200: MPVStatusResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def get_mpv_status(request: HttpRequest):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    mpv_status = mpv_service.get_status() or {"connected": False}
    tracks = mpv_service.get_track_list() if mpv_status.get("connected", True) else None
    tracks = tracks or {}

    tracks_info = TracksInfoSchema(
        audio_tracks=[
            TrackSchema(
                id=track.get("id", 0),
                language=track.get("lang") or track.get("language"),
                title=track.get("title"),
                selected=track.get("selected", False),
            )
            for track in tracks.get("audio_tracks", [])
        ],
        sub_tracks=[
            TrackSchema(
                id=track.get("id", 0),
                language=track.get("lang") or track.get("language"),
                title=track.get("title"),
                selected=track.get("selected", False),
            )
            for track in tracks.get("sub_tracks", [])
        ],
        video_tracks=[
            TrackSchema(id=track.get("id", 0), codec=track.get("codec"), selected=track.get("selected", False))
            for track in tracks.get("video_tracks", [])
        ],
    )

    status_info = MPVStatusSchema(
        volume=mpv_status.get("volume"),
        muted=mpv_status.get("muted"),
        speed=mpv_status.get("speed"),
        fullscreen=mpv_status.get("fullscreen"),
        panscan=mpv_status.get("panscan"),
    )

    video_data = mpv_status.get("video", {})
    video_info = None
    if video_data and video_data.get("width"):
        video_info = VideoTechInfoSchema(
            width=video_data.get("width"),
            height=video_data.get("height"),
            fps=video_data.get("fps"),
            codec=video_data.get("codec"),
            pixelformat=video_data.get("pixelformat"),
            colormatrix=video_data.get("colormatrix"),
            colorlevels=video_data.get("colorlevels"),
            primaries=video_data.get("primaries"),
            gamma=video_data.get("gamma"),
            hw_decoding=video_data.get("hw_decoding"),
        )

    audio_data = mpv_status.get("audio", {})
    audio_info = None
    if audio_data and audio_data.get("codec"):
        audio_info = AudioTechInfoSchema(
            codec=audio_data.get("codec"), channels=audio_data.get("channels"), samplerate=audio_data.get("samplerate")
        )

    return Status(
        200,
        MPVStatusResponseSchema(
            message="MPV status retrieved successfully",
            data=MPVStatusDataSchema(
                status=status_info,
                tracks=tracks_info,
                connected=mpv_status.get("connected", True),
                video=video_info,
                audio=audio_info,
            ),
        ),
    )


@mpv_api.post(
    "/playback",
    response={
        200: MessageResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def control_playback(request: HttpRequest, data: PlaybackControlSchema):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    success = False
    message = ""

    if data.action == "play":
        success = mpv_service.play()
        message = "Playback resumed"
    elif data.action == "pause":
        success = mpv_service.pause()
        message = "Playback paused"
    elif data.action == "stop":
        success = mpv_service.stop()
        message = "Playback stopped"
    elif data.action == "toggle":
        success = mpv_service.toggle_pause()
        message = "Playback toggled"

    if not success:
        raise UnprocessableEntityError(f"{data.action.capitalize()} command failed")

    return Status(200, MessageResponseSchema(success=True, message=message))


@mpv_api.post(
    "/seek",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def control_seek(request: HttpRequest, data: SeekControlSchema):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    success = False

    if data.type == "percentage":
        success = mpv_service.seek(data.position)
    elif data.type == "relative":
        current_status = mpv_service.get_status()
        if current_status and current_status.get("time"):
            new_position = current_status["time"] + data.position
            success = (
                mpv_service._mpv_command("set_property", "time-pos", new_position)
                if hasattr(mpv_service, "_mpv_command")
                else mpv_service.seek(new_position)
            )
        else:
            raise UnprocessableEntityError("Unable to get current position for relative seek")
    else:  # absolute
        success = (
            mpv_service._mpv_command("set_property", "time-pos", data.position)
            if hasattr(mpv_service, "_mpv_command")
            else mpv_service.seek(data.position)
        )

    if not success:
        raise UnprocessableEntityError("Seek command failed")

    return Status(200, MessageResponseSchema(success=True, message=f"Seeked to {data.position}"))


@mpv_api.post(
    "/volume",
    response={
        200: MessageResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def control_volume(request: HttpRequest, data: VolumeControlSchema):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    success = False
    message = ""

    if data.action == "set":
        if data.volume is None:
            raise ValidationError("volume is required for set action")
        success = (
            mpv_service._mpv_command("set_property", "volume", data.volume)
            if hasattr(mpv_service, "_mpv_command")
            else False
        )
        message = f"Volume set to {data.volume}%"
    elif data.action == "up":
        success = mpv_service._mpv_command("add", "volume", 5) if hasattr(mpv_service, "_mpv_command") else False
        message = "Volume increased"
    elif data.action == "down":
        success = mpv_service._mpv_command("add", "volume", -5) if hasattr(mpv_service, "_mpv_command") else False
        message = "Volume decreased"
    elif data.action == "mute":
        success = mpv_service._mpv_command("cycle", "mute") if hasattr(mpv_service, "_mpv_command") else False
        message = "Mute toggled"

    if not success:
        raise UnprocessableEntityError(f"{data.action.capitalize()} command failed")

    return Status(200, MessageResponseSchema(success=True, message=message))


@mpv_api.post(
    "/tracks",
    response={
        200: MessageResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def control_tracks(request: HttpRequest, data: TrackControlSchema):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    success = False
    message = ""

    if data.type == "audio":
        success = mpv_service.set_audio_track(data.track_id)
        message = f"Audio track set to {data.track_id}"
    elif data.type == "sub":
        if str(data.track_id) == "no":
            success = mpv_service.set_subtitle_track(0)
            message = "Subtitles disabled"
        else:
            success = mpv_service.set_subtitle_track(data.track_id)
            message = f"Subtitle track set to {data.track_id}"
    else:
        raise ValidationError('Invalid track type. Must be "audio" or "sub"')

    if not success:
        raise UnprocessableEntityError("Track selection failed")

    return Status(200, MessageResponseSchema(success=True, message=message))


@mpv_api.post(
    "/playlist",
    response={
        200: MessageResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def control_playlist(request: HttpRequest, data: PlaylistControlSchema):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    success = False
    message = ""

    if data.action == "next":
        success = mpv_service._mpv_command("playlist-next") if hasattr(mpv_service, "_mpv_command") else False
        message = "Next playlist item"
    elif data.action == "prev":
        success = mpv_service._mpv_command("playlist-prev") if hasattr(mpv_service, "_mpv_command") else False
        message = "Previous playlist item"
    elif data.action == "jump":
        if data.index is None:
            raise ValidationError("index is required for jump action")
        try:
            success = (
                mpv_service._mpv_command("set_property", "playlist-pos", int(data.index))
                if hasattr(mpv_service, "_mpv_command")
                else False
            )
            message = f"Jumped to playlist item {data.index}"
        except ValueError:
            raise ValidationError("Invalid playlist index") from None

    if not success:
        raise UnprocessableEntityError(f"{data.action.capitalize()} command failed")

    return Status(200, MessageResponseSchema(success=True, message=message))


@mpv_api.post(
    "/speed",
    response={
        200: MessageResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def control_speed(request: HttpRequest, data: SpeedControlSchema):
    if data.speed <= 0:
        raise ValidationError("speed must be a positive number")

    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    success = (
        mpv_service._mpv_command("set_property", "speed", data.speed) if hasattr(mpv_service, "_mpv_command") else False
    )

    if not success:
        raise UnprocessableEntityError("Speed change failed")

    return Status(200, MessageResponseSchema(success=True, message=f"Playback speed set to {data.speed}x"))


@mpv_api.post(
    "/fullscreen",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def control_fullscreen(request: HttpRequest):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    success = mpv_service._mpv_command("cycle", "fullscreen") if hasattr(mpv_service, "_mpv_command") else False

    if not success:
        raise UnprocessableEntityError("Fullscreen toggle failed")

    return Status(200, MessageResponseSchema(success=True, message="Fullscreen toggled"))


@mpv_api.post(
    "/chapters",
    # Same handler as /command — distinct operation_ids keep the OpenAPI
    # schema warning-free and generated-client-safe (see playout_ninja /run).
    operation_id="mpv_send_chapter_command",
    response={
        200: MessageResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
@mpv_api.post(
    "/command",
    operation_id="mpv_send_command",
    response={
        200: MessageResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def send_mpv_command(request: HttpRequest, data: MPVCommandSchema):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    if not hasattr(mpv_service, "_mpv_command"):
        raise UnprocessableEntityError("MPV command interface not available")

    try:
        if data.args:
            success = mpv_service._mpv_command(data.command, *data.args)
        else:
            success = mpv_service._mpv_command(data.command)

        if not success:
            raise UnprocessableEntityError(f'MPV command "{data.command}" failed')

        return Status(
            200, MessageResponseSchema(success=True, message=f'Command "{data.command}" executed successfully')
        )
    except Exception as e:
        logger.error(f"MPV command error: {e}")
        raise UnprocessableEntityError(f'MPV command "{data.command}" failed: {str(e)}') from e


@mpv_api.get(
    "/property/{property_name}",
    response={200: SuccessResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def get_mpv_property(request: HttpRequest, property_name: str):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    if hasattr(mpv_service, "controller") and mpv_service.controller:
        try:
            value = mpv_service.controller.get_property(property_name)
            return Status(
                200,
                SuccessResponseSchema(
                    message=f'Property "{property_name}" retrieved successfully', data={"value": value}
                ),
            )
        except Exception as e:
            logger.error(f"Failed to get property {property_name}: {e}")
            raise UnprocessableEntityError(f'Failed to get property "{property_name}": {str(e)}') from e
    else:
        raise UnprocessableEntityError("MPV property interface not available")


@mpv_api.post(
    "/property/{property_name}",
    response={
        200: MessageResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def set_mpv_property(request: HttpRequest, property_name: str, data: PropertySchema):
    if mpv_service is None:
        raise NotFoundError("No MPV handler available")

    if not hasattr(mpv_service, "_mpv_command"):
        raise UnprocessableEntityError("MPV property interface not available")

    try:
        success = mpv_service._mpv_command("set_property", property_name, data.value)

        if not success:
            raise UnprocessableEntityError(f'Failed to set property "{property_name}"')

        return Status(
            200, MessageResponseSchema(success=True, message=f'Property "{property_name}" set to {data.value}')
        )
    except Exception as e:
        logger.error(f"Failed to set property {property_name}: {e}")
        raise UnprocessableEntityError(f'Failed to set property "{property_name}": {str(e)}') from e
