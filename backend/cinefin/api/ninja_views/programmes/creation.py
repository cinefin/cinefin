from typing import Any

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema
from cinefin.api.services import ProgrammeService


class CreateProgrammeSchema(Schema):
    name: str
    description: str | None = ""
    preview: bool | None = False
    items: list[dict[str, Any]]


class CreateFromTemplateSchema(Schema):
    name: str
    description: str | None = ""
    template_id: int
    movies: dict[str, Any] = Field(
        ..., description="Features mapped by feature number (can be movies or random_movie configs)"
    )
    preview: bool | None = False


class ProgrammeBlockDetailSchema(Schema):
    order: int
    type: str
    duration_seconds: float = Field(..., description="Seconds (an estimate for blocks resolved at generation)")
    title: str
    details: dict[str, Any]


class ProgrammePreviewSchema(Schema):
    name: str
    description: str
    total_runtime: float = Field(..., description="Minutes")
    total_blocks: int
    blocks: list[ProgrammeBlockDetailSchema]
    preview: bool
    template_id: int | None = None
    template_name: str | None = None


class ProgrammeCreateResponseDataSchema(Schema):
    id: int
    name: str
    programme: ProgrammePreviewSchema
    playlist_generated: bool | None = None
    playlist_items: int | None = None
    certifications_generated: int | None = None


class ProgrammeCreateResponseSchema(MessageResponseSchema):
    data: ProgrammeCreateResponseDataSchema


class ProgrammePreviewResponseDataSchema(Schema):
    programme: ProgrammePreviewSchema


class ProgrammePreviewResponseSchema(MessageResponseSchema):
    data: ProgrammePreviewResponseDataSchema


creation_api = Router()

_RESPONSES = {
    200: ProgrammePreviewResponseSchema,
    201: ProgrammeCreateResponseSchema,
    400: ErrorResponseSchema,
    404: ErrorResponseSchema,
    500: ErrorResponseSchema,
}


def _respond(programme, preview_data: dict, preview: bool, how: str = "") -> Status:
    """The preview (200), or the created programme (201)."""
    schema = ProgrammePreviewSchema(
        **{k: preview_data.get(k) for k in ("name", "description", "total_runtime", "total_blocks", "preview")},
        blocks=[ProgrammeBlockDetailSchema(**block) for block in preview_data["blocks"]],
        template_id=preview_data.get("template_id"),
        template_name=preview_data.get("template_name"),
    )
    if preview:
        return Status(
            200,
            ProgrammePreviewResponseSchema(
                message=f"Programme preview {how}generated successfully",
                data=ProgrammePreviewResponseDataSchema(programme=schema),
            ),
        )
    return Status(
        201,
        ProgrammeCreateResponseSchema(
            message=f"Programme '{programme.name}' created {how}successfully",
            data=ProgrammeCreateResponseDataSchema(
                id=programme.id,
                name=programme.name,
                programme=schema,
                playlist_generated=preview_data.get("playlist_generated", False),
                playlist_items=preview_data.get("playlist_items", 0),
                certifications_generated=0,
            ),
        ),
    )


@creation_api.post("/create", response=_RESPONSES)
def create_programme(request: HttpRequest, data: CreateProgrammeSchema):
    programme, preview_data = ProgrammeService.create_programme(
        name=data.name, description=data.description or "", items=data.items, preview=data.preview or False
    )
    return _respond(programme, preview_data, bool(data.preview))


_RANDOM_MOVIE_KEYS = ("certification", "year_from", "year_to", "runtime_from", "runtime_to")


@creation_api.post("/create-from-template", response=_RESPONSES)
def create_programme_from_template(request: HttpRequest, data: CreateFromTemplateSchema):
    movies = {}
    for feature_key, movie in data.movies.items():
        if movie.get("type") == "random_movie":
            movies[feature_key] = {
                "type": "random_movie",
                "genre_ids": movie.get("genre_ids") or [],
                **{k: movie.get(k) for k in _RANDOM_MOVIE_KEYS},
            }
        else:
            movies[feature_key] = {
                "id": movie.get("id"),
                "title": movie.get("title"),
                "audio_track_index": movie.get("audio_track_index", 0),
                "subtitle_track_index": movie.get("subtitle_track_index"),
                "credits_command_id": movie.get("credits_command_id"),
            }
    programme, preview_data = ProgrammeService.create_programme_from_template(
        name=data.name,
        template_id=data.template_id,
        movies=movies,
        description=data.description or "",
        preview=data.preview or False,
    )
    return _respond(programme, preview_data, bool(data.preview), "from template ")
