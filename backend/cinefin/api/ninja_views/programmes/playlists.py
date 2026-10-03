"""Programme playlists: read one (generating it if missing) and the manual regenerate."""

import logging
from typing import Any

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import UnprocessableEntityError, get_or_404
from cinefin.api.models import Playlist, Programme
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import ProgrammeService
from cinefin.api.services.playlist_utils import PlaylistUtils

logger = logging.getLogger(__name__)


class PlaylistItemSchema(Schema):
    order: int
    file_path: str
    duration: float | None = None
    title: str
    type: str = Field(..., description="Item type (movie, trailer, bumper, etc.)")
    details: dict[str, Any]


class PlaylistDetailSchema(Schema):
    programme_id: int
    programme_name: str
    total_items: int
    total_duration: float
    items: list[PlaylistItemSchema]


class PlaylistResponseDataSchema(Schema):
    playlist: PlaylistDetailSchema


class PlaylistResponseSchema(SuccessResponseSchema):
    data: PlaylistResponseDataSchema


playlists_api = Router()


@playlists_api.post(
    "/{programme_id}/regenerate-playlist",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def regenerate_playlist(request: HttpRequest, programme_id: int):
    """The manual retry for a failed automatic regeneration; also re-rolls trailer-rule and random picks."""
    programme = get_or_404(Programme, programme_id, "Programme not found", "PROGRAMME_NOT_FOUND")
    item_count = ProgrammeService.refresh_playlist(programme)
    if item_count is None:
        raise UnprocessableEntityError("Playlist regeneration failed — check the application logs")

    return Status(
        200,
        MessageResponseSchema(
            message=f"Playlist regenerated successfully for '{programme.name}' with {item_count} items"
        ),
    )


@playlists_api.get(
    "/{programme_id}/playlist",
    response={200: PlaylistResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def get_programme_playlist(request: HttpRequest, programme_id: int):
    programme = get_or_404(Programme, programme_id, "Programme not found", "PROGRAMME_NOT_FOUND")
    playlist = Playlist.objects.filter(programme=programme).first()
    if playlist is None:
        logger.info(f"No saved playlist found for programme '{programme.name}', generating new playlist")
        if ProgrammeService.refresh_playlist(programme) is None:
            raise UnprocessableEntityError("Failed to generate playlist — check the application logs")
        playlist = Playlist.objects.get(programme=programme)

    playlist_items = []
    total_duration = 0.0
    for playlist_item in playlist.items.all().order_by("order"):
        item_data = PlaylistUtils.build_playlist_item_details(playlist_item)
        total_duration += item_data["duration"]
        playlist_items.append(
            PlaylistItemSchema(
                order=item_data["order"],
                file_path=item_data["file_path"],
                duration=item_data["duration"],
                title=item_data["title"],
                type=item_data["type"],
                details={
                    "programme_block_id": item_data["programme_block_id"],
                    "content_id": item_data["content_id"],
                    "audio_track": item_data["audio_track"],
                    "subtitle_track": item_data["subtitle_track"],
                    "metadata": item_data["metadata"],
                },
            )
        )

    return Status(
        200,
        PlaylistResponseSchema(
            message=f"Playlist retrieved successfully for '{programme.name}'",
            data=PlaylistResponseDataSchema(
                playlist=PlaylistDetailSchema(
                    programme_id=programme.id,
                    programme_name=programme.name,
                    total_items=len(playlist_items),
                    total_duration=total_duration,
                    items=playlist_items,
                )
            ),
        ),
    )
