"""Shared block content-type fetch/validation helpers."""

from dataclasses import dataclass

from cinefin.api.exceptions import NotFoundError
from cinefin.api.models import Bumper, Command, Movie, Trailer
from cinefin.api.services import streaming_service


@dataclass(frozen=True)
class BlockEntityType:
    model: type
    label: str
    error_code: str


BLOCK_ENTITY_TYPES: dict[str, BlockEntityType] = {
    "movie": BlockEntityType(Movie, "Movie", "MOVIE_NOT_FOUND"),
    "trailer": BlockEntityType(Trailer, "Trailer", "TRAILER_NOT_FOUND"),
    "bumper": BlockEntityType(Bumper, "User media item", "BUMPER_NOT_FOUND"),
    "command": BlockEntityType(Command, "Command", "COMMAND_NOT_FOUND"),
}


def fetch_block_entity(content_type: str, entity_id):
    spec = BLOCK_ENTITY_TYPES[content_type]
    try:
        return spec.model.objects.get(pk=entity_id)
    except spec.model.DoesNotExist:
        raise NotFoundError(f"{spec.label} {entity_id} not found", error_code=spec.error_code) from None


def resolve_block_entity(block, content_type: str | None = None):
    """Return the validated content_object for a ProgrammeBlock, or None if missing/wrong type."""
    spec = BLOCK_ENTITY_TYPES.get(content_type or block.content_type)
    if spec and isinstance(block.content_object, spec.model):
        return block.content_object
    return None


def resolve_media_path(obj) -> str | None:
    """Resolve the HTTP streaming URL for a media object (None if none could be built)."""
    result = streaming_service.get_movie_stream_url(obj) if isinstance(obj, Movie) else obj.get_stream_url()
    return result.get("stream_url")
