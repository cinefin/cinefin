"""MPV Control API: raw player settings (volume, speed, tracks, properties).

What plays, and every transport action, is playout_ninja.py (GET /playout/status,
POST /playout/control); both drive mpv_service directly.
"""

import logging
from typing import Any

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import UnprocessableEntityError
from cinefin.api.mpv_service import mpv_service
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema

logger = logging.getLogger(__name__)


class TrackSchema(Schema):
    id: int
    language: str | None = None
    title: str | None = None
    codec: str | None = None
    selected: bool


class MPVStatusSchema(Schema):
    volume: int | None = Field(None, description="0-100")
    muted: bool | None = None
    speed: float | None = None
    fullscreen: bool | None = None
    panscan: float | None = Field(
        None, description="mpv panscan: 0 fits the whole picture, 1 zooms to fill the screen (crops wide films)"
    )


class TracksInfoSchema(Schema):
    audio_tracks: list[TrackSchema]
    sub_tracks: list[TrackSchema]
    video_tracks: list[TrackSchema]


class VideoTechInfoSchema(Schema):
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str | None = None
    pixelformat: str | None = None
    colormatrix: str | None = None
    colorlevels: str | None = None
    primaries: str | None = None
    gamma: str | None = None
    hw_decoding: str | None = None


class AudioTechInfoSchema(Schema):
    codec: str | None = None
    channels: str | None = Field(None, description="Channel layout, e.g. 'stereo', '5.1'")
    samplerate: int | None = None


class MPVStatusDataSchema(Schema):
    """Raw player settings the programme status doesn't carry (what plays, and whether it is
    paused, is GET /playout/status)."""

    status: MPVStatusSchema | None = None
    tracks: TracksInfoSchema
    connected: bool
    video: VideoTechInfoSchema | None = None
    audio: AudioTechInfoSchema | None = None


class MPVStatusResponseSchema(SuccessResponseSchema):
    data: MPVStatusDataSchema


class MPVCommandSchema(Schema):
    command: str
    args: list[Any] | None = []


class PropertySchema(Schema):
    value: Any


mpv_api = Router()

_ERRORS = {400: ErrorResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema, 500: ErrorResponseSchema}


def _track(track: dict, **extra) -> TrackSchema:
    return TrackSchema(id=track.get("id", 0), selected=track.get("selected", False), **extra)


def _lang_track(track: dict) -> TrackSchema:
    return _track(track, language=track.get("lang") or track.get("language"), title=track.get("title"))


@mpv_api.get("/status", response={200: MPVStatusResponseSchema, **_ERRORS})
def get_mpv_status(request: HttpRequest):
    mpv_status = mpv_service.get_status() or {"connected": False}
    connected = mpv_status.get("connected", True)
    tracks = (mpv_service.get_track_list() if connected else None) or {}
    video = mpv_status.get("video") or {}
    audio = mpv_status.get("audio") or {}
    return Status(
        200,
        MPVStatusResponseSchema(
            message="MPV status retrieved successfully",
            data=MPVStatusDataSchema(
                status=MPVStatusSchema(
                    **{k: mpv_status.get(k) for k in ("volume", "muted", "speed", "fullscreen", "panscan")}
                ),
                tracks=TracksInfoSchema(
                    audio_tracks=[_lang_track(t) for t in tracks.get("audio_tracks", [])],
                    sub_tracks=[_lang_track(t) for t in tracks.get("sub_tracks", [])],
                    video_tracks=[_track(t, codec=t.get("codec")) for t in tracks.get("video_tracks", [])],
                ),
                connected=connected,
                video=VideoTechInfoSchema(**{k: video.get(k) for k in VideoTechInfoSchema.model_fields})
                if video.get("width")
                else None,
                audio=AudioTechInfoSchema(**{k: audio.get(k) for k in AudioTechInfoSchema.model_fields})
                if audio.get("codec")
                else None,
            ),
        ),
    )


@mpv_api.post("/command", operation_id="mpv_send_command", response={200: MessageResponseSchema, **_ERRORS})
def send_mpv_command(request: HttpRequest, data: MPVCommandSchema):
    try:
        success = mpv_service._mpv_command(data.command, *(data.args or ()))
    except Exception as e:
        logger.error(f"MPV command error: {e}")
        raise UnprocessableEntityError(f'MPV command "{data.command}" failed: {str(e)}') from e
    if not success:
        raise UnprocessableEntityError(f'MPV command "{data.command}" failed')
    return Status(200, MessageResponseSchema(success=True, message=f'Command "{data.command}" executed successfully'))


@mpv_api.post("/property/{property_name}", response={200: MessageResponseSchema, **_ERRORS})
def set_mpv_property(request: HttpRequest, property_name: str, data: PropertySchema):
    try:
        success = mpv_service._mpv_command("set_property", property_name, data.value)
    except Exception as e:
        logger.error(f"Failed to set property {property_name}: {e}")
        raise UnprocessableEntityError(f'Failed to set property "{property_name}": {str(e)}') from e
    if not success:
        raise UnprocessableEntityError(f'Failed to set property "{property_name}"')
    return Status(200, MessageResponseSchema(success=True, message=f'Property "{property_name}" set to {data.value}'))
