import logging
from typing import Any, Literal

from django.http import HttpRequest
from ninja import Field, Router, Schema, Status

from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema
from cinefin.api.services import ProgrammeService

logger = logging.getLogger(__name__)


class CreateMovieItemSchema(Schema):
    type: Literal["movie"] = Field(..., description="Item type identifier")
    movie_id: int = Field(..., description="ID of the movie to add")
    audio_track: int | None = Field(0, description="Audio track index to use")
    subtitle_track: int | None = Field(None, description="Subtitle track index to use")
    credits_command_id: int | None = Field(None, description="Command ID to execute when credits begin")


class CreateTrailerItemSchema(Schema):
    type: Literal["trailer"] = Field(..., description="Item type identifier")
    trailer_id: int = Field(..., description="ID of the trailer to add")


class CreateBumperItemSchema(Schema):
    # Two modes: specific clip (bumper_id) or random pick from a tag (a tag set = random).
    type: Literal["bumper"] = Field(..., description="Item type identifier")
    bumper_id: int | None = Field(None, description="ID of a specific clip to play (specific mode)")
    tag_id: int | None = Field(None, description="Tag ID for a random pick (random mode)")
    tag_name: str | None = Field(None, description="Tag name for a random pick (random mode)")
    count: int | None = Field(1, description="Number of random clips to select (random mode)")


class CreateRandomMovieItemSchema(Schema):
    type: Literal["random_movie"] = Field(..., description="Item type identifier")
    genre_ids: list[int] | None = Field(None, description="Genre IDs for filtering (movies must match ALL)")
    certification: str | None = Field(None, description="Certification for filtering (e.g., PG-13, R)")
    year_from: int | None = Field(None, description="Minimum release year")
    year_to: int | None = Field(None, description="Maximum release year")
    runtime_from: int | None = Field(None, description="Minimum runtime in minutes")
    runtime_to: int | None = Field(None, description="Maximum runtime in minutes")
    count: int | None = Field(1, description="Number of random movies to select")


class CreateCommandItemSchema(Schema):
    type: Literal["command"] = Field(..., description="Item type identifier")
    command_id: int = Field(..., description="ID of the command to add")
    hold_black: bool | None = Field(
        False, description="Show a black screen for the command's duration (otherwise fires instantly)"
    )


class CreateTrailerRuleItemSchema(Schema):
    type: Literal["trailer_rule"] = Field(..., description="Item type identifier")
    reference_movie_id: int | None = Field(None, description="Optional reference movie (seeds/ranks, not a filter)")
    bound_to_block_order: int | None = Field(None, description="Bind to a random-movie block by its order")
    count: int | None = Field(3, description="Number of trailers to select")
    genre_ids: list[int] | None = Field(
        None, description="Best-effort genres — a trailer must share at least one; more matches rank first"
    )
    certificate_ceiling: str | None = Field(None, description="Never pick a trailer rated above this certificate")
    year_from: int | None = Field(None, description="Earliest trailer release year (inclusive)")
    year_to: int | None = Field(None, description="Latest trailer release year (inclusive)")
    trailer_tag_id: int | None = Field(None, description="Only pick trailers carrying this trailer tag")


class CreateCertificationItemSchema(Schema):
    type: Literal["certification"] = Field(..., description="Item type identifier")
    movie_id: int = Field(..., description="ID of the movie for certification")
    certification: str | None = Field(None, description="Certification type")


class CreateAudioBumperItemSchema(Schema):
    type: Literal["audio_bumper"] = Field(..., description="Item type identifier")
    reference_movie_id: int | None = Field(
        None, description="Feature (movie) whose audio format the intro matches — chosen in the editor"
    )
    bumper_id: int | None = Field(None, description="Explicit user-media override (skips format matching)")


ProgrammeItemSchema = (
    CreateMovieItemSchema
    | CreateTrailerItemSchema
    | CreateBumperItemSchema
    | CreateRandomMovieItemSchema
    | CreateCommandItemSchema
    | CreateTrailerRuleItemSchema
    | CreateCertificationItemSchema
    | CreateAudioBumperItemSchema
)


class CreateProgrammeSchema(Schema):
    name: str = Field(..., description="Programme name")
    description: str | None = Field("", description="Programme description")
    preview: bool | None = Field(False, description="Whether to preview without creating")
    items: list[dict[str, Any]] = Field(..., description="List of programme items")


class UpdateProgrammeSchema(Schema):
    name: str | None = Field(None, description="Updated programme name")
    description: str | None = Field(None, description="Updated programme description")
    items: list[dict[str, Any]] | None = Field(None, description="Updated list of programme items")


class CreateFromTemplateMovieSchema(Schema):
    id: int = Field(..., description="Movie ID")
    title: str = Field(..., description="Movie title")
    audio_track_index: int | None = Field(0, description="Audio track index to use")
    subtitle_track_index: int | None = Field(None, description="Subtitle track index to use")
    credits_command_id: int | None = Field(None, description="Command ID to execute when credits begin")


class CreateFromTemplateRandomMovieSchema(Schema):
    type: Literal["random_movie"] = Field(..., description="Item type identifier")
    genre_ids: list[int] | None = Field(None, description="Genre IDs for filtering (movies must match ALL)")
    certification: str | None = Field(None, description="Certification for filtering")
    year_from: int | None = Field(None, description="Minimum release year")
    year_to: int | None = Field(None, description="Maximum release year")
    runtime_from: int | None = Field(None, description="Minimum runtime in minutes")
    runtime_to: int | None = Field(None, description="Maximum runtime in minutes")


class CreateFromTemplateSchema(Schema):
    name: str = Field(..., description="Programme name")
    description: str | None = Field("", description="Programme description")
    template_id: int = Field(..., description="Template ID to use")
    movies: dict[str, Any] = Field(
        ..., description="Features mapped by feature number (can be movies or random_movie configs)"
    )
    preview: bool | None = Field(False, description="Whether to preview without creating")


class ProgrammeBlockDetailSchema(Schema):
    order: int = Field(..., description="Block order in programme")
    type: str = Field(..., description="Block type")
    runtime: float = Field(..., description="Runtime in minutes")
    title: str = Field(..., description="Block title")
    details: dict[str, Any] = Field(..., description="Block-specific details")


class ProgrammePreviewSchema(Schema):
    name: str = Field(..., description="Programme name")
    description: str = Field(..., description="Programme description")
    total_runtime: float = Field(..., description="Total runtime in minutes")
    total_blocks: int = Field(..., description="Total number of blocks")
    blocks: list[ProgrammeBlockDetailSchema] = Field(..., description="List of programme blocks")
    preview: bool = Field(..., description="Whether this is a preview")
    template_id: int | None = Field(None, description="Template ID if created from template")
    template_name: str | None = Field(None, description="Template name if created from template")


class ProgrammeCreateResponseDataSchema(Schema):
    id: int = Field(..., description="Created programme ID")
    name: str = Field(..., description="Programme name")
    programme: ProgrammePreviewSchema = Field(..., description="Programme details")
    playlist_generated: bool | None = Field(None, description="Whether playlist was generated")
    playlist_items: int | None = Field(None, description="Number of playlist items")
    certifications_generated: int | None = Field(None, description="Number of certifications generated")


class ProgrammeCreateResponseSchema(MessageResponseSchema):
    data: ProgrammeCreateResponseDataSchema = Field(..., description="Created programme data")


class ProgrammePreviewResponseDataSchema(Schema):
    programme: ProgrammePreviewSchema = Field(..., description="Programme preview details")


class ProgrammePreviewResponseSchema(MessageResponseSchema):
    data: ProgrammePreviewResponseDataSchema = Field(..., description="Programme preview data")


creation_api = Router()


@creation_api.post(
    "/create",
    response={
        200: ProgrammePreviewResponseSchema,
        201: ProgrammeCreateResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def create_programme(request: HttpRequest, data: CreateProgrammeSchema):
    programme, preview_data = ProgrammeService.create_programme(
        name=data.name, description=data.description or "", items=data.items, preview=data.preview or False
    )

    preview_schema = ProgrammePreviewSchema(
        name=preview_data["name"],
        description=preview_data["description"],
        total_runtime=preview_data["total_runtime"],
        total_blocks=preview_data["total_blocks"],
        blocks=[ProgrammeBlockDetailSchema(**block) for block in preview_data["blocks"]],
        preview=preview_data["preview"],
    )

    if data.preview:
        return Status(
            200,
            ProgrammePreviewResponseSchema(
                message="Programme preview generated successfully",
                data=ProgrammePreviewResponseDataSchema(programme=preview_schema),
            ),
        )

    return Status(
        201,
        ProgrammeCreateResponseSchema(
            message=f"Programme '{programme.name}' created successfully",
            data=ProgrammeCreateResponseDataSchema(
                id=programme.id,
                name=programme.name,
                programme=preview_schema,
                playlist_generated=preview_data.get("playlist_generated", False),
                playlist_items=preview_data.get("playlist_items", 0),
                certifications_generated=0,
            ),
        ),
    )


@creation_api.post(
    "/create-from-template",
    response={
        200: ProgrammePreviewResponseSchema,
        201: ProgrammeCreateResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def create_programme_from_template(request: HttpRequest, data: CreateFromTemplateSchema):
    movies_dict = {}
    for feature_key, movie_data in data.movies.items():
        if isinstance(movie_data, dict) and movie_data.get("type") == "random_movie":
            movies_dict[feature_key] = {
                "type": "random_movie",
                "genre_ids": movie_data.get("genre_ids") or [],
                "certification": movie_data.get("certification"),
                "year_from": movie_data.get("year_from"),
                "year_to": movie_data.get("year_to"),
                "runtime_from": movie_data.get("runtime_from"),
                "runtime_to": movie_data.get("runtime_to"),
            }
        elif isinstance(movie_data, dict):
            movies_dict[feature_key] = {
                "id": movie_data.get("id"),
                "title": movie_data.get("title"),
                "audio_track_index": movie_data.get("audio_track_index", 0),
                "subtitle_track_index": movie_data.get("subtitle_track_index"),
                "credits_command_id": movie_data.get("credits_command_id"),
            }
        else:
            movies_dict[feature_key] = {
                "id": movie_data.id,
                "title": movie_data.title,
                "audio_track_index": movie_data.audio_track_index,
                "subtitle_track_index": movie_data.subtitle_track_index,
                "credits_command_id": movie_data.credits_command_id,
            }

    programme, preview_data = ProgrammeService.create_programme_from_template(
        name=data.name,
        template_id=data.template_id,
        movies=movies_dict,
        description=data.description or "",
        preview=data.preview or False,
    )

    preview_schema = ProgrammePreviewSchema(
        name=preview_data["name"],
        description=preview_data["description"],
        total_runtime=preview_data["total_runtime"],
        total_blocks=preview_data["total_blocks"],
        blocks=[ProgrammeBlockDetailSchema(**block) for block in preview_data["blocks"]],
        preview=preview_data["preview"],
        template_id=preview_data.get("template_id"),
        template_name=preview_data.get("template_name"),
    )

    if data.preview:
        return Status(
            200,
            ProgrammePreviewResponseSchema(
                message="Programme preview from template generated successfully",
                data=ProgrammePreviewResponseDataSchema(programme=preview_schema),
            ),
        )

    return Status(
        201,
        ProgrammeCreateResponseSchema(
            message=f"Programme '{programme.name}' created from template successfully",
            data=ProgrammeCreateResponseDataSchema(
                id=programme.id,
                name=programme.name,
                programme=preview_schema,
                playlist_generated=preview_data.get("playlist_generated", False),
                playlist_items=preview_data.get("playlist_items", 0),
                certifications_generated=0,
            ),
        ),
    )
