"""
Programme Playlists API - Endpoints for playlist generation and management
"""

import logging
from typing import Any

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError
from cinefin.api.models import Playlist, Programme
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import ProgrammeService
from cinefin.api.services.playlist_utils import PlaylistUtils

logger = logging.getLogger(__name__)


# Playlist schemas
class PlaylistItemSchema(Schema):
    order: int = Field(..., description="Item order in playlist")
    file_path: str = Field(..., description="Path to media file")
    duration: float | None = Field(None, description="Item duration in seconds")
    title: str = Field(..., description="Item title")
    type: str = Field(..., description="Item type (movie, trailer, bumper, etc.)")
    details: dict[str, Any] = Field(..., description="Additional item details")


class PlaylistDetailSchema(Schema):
    programme_id: int = Field(..., description="Programme ID")
    programme_name: str = Field(..., description="Programme name")
    total_items: int = Field(..., description="Total number of playlist items")
    total_duration: float = Field(..., description="Total playlist duration in seconds")
    items: list[PlaylistItemSchema] = Field(..., description="List of playlist items in playback order")


class PlaylistResponseDataSchema(Schema):
    """Data schema for playlist response"""

    playlist: PlaylistDetailSchema = Field(..., description="Playlist details")


class PlaylistResponseSchema(SuccessResponseSchema):
    """Response schema for playlist endpoints"""

    data: PlaylistResponseDataSchema = Field(..., description="Playlist data")


# Create the playlists router
playlists_api = Router()


@playlists_api.post(
    "/{programme_id}/regenerate-playlist",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def regenerate_playlist(request: HttpRequest, programme_id: int):
    """
    Regenerate the playlist for a programme.

    Playlists are rebuilt automatically when a programme is saved and when it is
    loaded for playout; this endpoint is the manual retry for a failed automatic
    regeneration, and also re-rolls trailer-rule and random-movie selections.
    """
    try:
        programme = Programme.objects.get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

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
    """
    Get the current playlist for a programme with detailed item information.

    Returns the complete playlist in playback order with file paths and metadata.
    """
    try:
        programme = Programme.objects.get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

    # Get the saved playlist, generating it first if it doesn't exist yet —
    # either way the response is serialized from the same DB rows.
    try:
        playlist = Playlist.objects.get(programme=programme)
    except Playlist.DoesNotExist:
        logger.info(f"No saved playlist found for programme '{programme.name}', generating new playlist")
        if ProgrammeService.refresh_playlist(programme) is None:
            raise UnprocessableEntityError("Failed to generate playlist — check the application logs") from None
        playlist = Playlist.objects.get(programme=programme)

    playlist_items = []
    total_duration = 0.0

    for playlist_item in playlist.items.all().order_by("order"):
        # Use shared utility to build detailed item information
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

    # Create playlist detail
    playlist_detail = PlaylistDetailSchema(
        programme_id=programme.id,
        programme_name=programme.name,
        total_items=len(playlist_items),
        total_duration=total_duration,
        items=playlist_items,
    )

    return Status(
        200,
        PlaylistResponseSchema(
            message=f"Playlist retrieved successfully for '{programme.name}'",
            data=PlaylistResponseDataSchema(playlist=playlist_detail),
        ),
    )
