import logging
from typing import Any

from django.db.models import Q
from django.http import HttpRequest
from ninja import Field, Query, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError, ValidationError
from cinefin.api.models import (
    Programme,
    ProgrammeBlock,
    TrailerRule,
)
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.schemas.movies import MovieInfoSchema
from cinefin.api.services import ProgrammeService
from cinefin.api.services.certification_service import CertificationService
from cinefin.api.utils.programme_utils import build_filter_description_from_block, build_random_movie_query

logger = logging.getLogger(__name__)


class ProgrammeItemDetailSchema(Schema):
    id: int = Field(..., description="Programme block ID")
    order: int = Field(..., description="Item order in programme")
    type: str = Field(..., description="Item type")
    title: str = Field(..., description="Item title")
    runtime: float = Field(..., description="Runtime in seconds")
    details: dict[str, Any] = Field(..., description="Item-specific details")


class ProgrammeDetailDataSchema(Schema):
    programme: "ProgrammeDetailSchema" = Field(..., description="Programme details")


class ProgrammeDetailSchema(Schema):
    id: int = Field(..., description="Programme ID")
    name: str = Field(..., description="Programme name")
    description: str = Field(..., description="Programme description")
    total_runtime: float = Field(..., description="Total runtime in minutes")
    created_at: str = Field(..., description="Creation timestamp in ISO format")
    updated_at: str = Field(..., description="Last update timestamp in ISO format")
    template_id: int | None = Field(None, description="Template ID if created from template")
    template_name: str | None = Field(None, description="Template name if created from template")
    total_blocks: int = Field(..., description="Total number of blocks")
    playlist_stale: bool = Field(..., description="True only when automatic playlist regeneration failed after an edit")
    title_template_id: int | None = Field(None, description="Title template ID for the programme title card")
    title_duration: int | None = Field(
        None, description="Title card duration override in seconds (null = template default)"
    )
    title_background_type: str = Field(..., description="Title card background type: color, image, or video")
    title_background_color: str = Field(..., description="Title card background color (hex)")
    title_background_file: str = Field(..., description="Title card background image/video path")
    title_fade_in: float = Field(..., description="Title card fade in duration in seconds")
    title_fade_out: float = Field(..., description="Title card fade out duration in seconds")
    title_file_generated: bool = Field(..., description="Whether a title card file has been generated")
    items: list[ProgrammeItemDetailSchema] = Field(..., description="List of programme items")


class ProgrammeDetailResponseSchema(SuccessResponseSchema):
    data: ProgrammeDetailDataSchema = Field(..., description="Programme detail data")


class ProgrammeListItemSchema(Schema):
    id: int = Field(..., description="Programme ID")
    name: str = Field(..., description="Programme name")
    description: str = Field(..., description="Programme description")
    total_runtime: float = Field(..., description="Total runtime in minutes")
    total_blocks: int = Field(..., description="Total number of blocks")
    created_at: str = Field(..., description="Creation timestamp in ISO format")
    last_played_at: str | None = Field(None, description="When playback last started, ISO format (null = never)")
    template_name: str | None = Field(None, description="Template name if created from template")
    playlist_stale: bool = Field(..., description="True only when automatic playlist regeneration failed after an edit")
    movies: list[MovieInfoSchema] = Field(..., description="Featured movies in this programme")
    composition: dict[str, int] = Field(
        ..., description="Block count per item type (content_type -> count), for the list's type chips"
    )


class ProgrammeListResponseDataSchema(Schema):
    programmes: list[ProgrammeListItemSchema] = Field(..., description="List of programmes")
    total: int = Field(..., description="Total number of programmes")


class ProgrammeListResponseSchema(SuccessResponseSchema):
    data: ProgrammeListResponseDataSchema = Field(..., description="Programme list data")


class ActiveProgrammeResponseDataSchema(Schema):
    active_programme: ProgrammeListItemSchema | None = Field(None, description="Currently active programme")


class ActiveProgrammeResponseSchema(SuccessResponseSchema):
    data: ActiveProgrammeResponseDataSchema = Field(..., description="Active programme data")


class ProgrammeListFilters(Schema):
    search: str | None = Field(None, description="Search term for programme name or description")


class ProgrammeDuplicateDataSchema(Schema):
    id: int = Field(..., description="ID of the new programme")
    name: str = Field(..., description="Name of the new programme")


class ProgrammeDuplicateResponseSchema(SuccessResponseSchema):
    data: ProgrammeDuplicateDataSchema = Field(..., description="New programme data")


class BulkProgrammeIdsSchema(Schema):
    ids: list[int] = Field(description="Programme IDs to act on")


class BulkDeleteDataSchema(Schema):
    deleted: int = Field(description="Number of programmes deleted")
    missing: list[int] = Field(description="Requested IDs that were not found")


class BulkDeleteResponseSchema(SuccessResponseSchema):
    data: BulkDeleteDataSchema


# Focused endpoint on purpose: PUT /programmes/{id} round-trips every block through
# update_programme, which can't express a trailer rule bound to a random movie, so
# saving a track choice that way risks dropping blocks.
class BlockTracksUpdateSchema(Schema):
    audio_track_index: int | None = Field(
        None, ge=0, description="0-based audio track index (null = the file's default track)"
    )
    subtitle_track_index: int | None = Field(
        None, ge=0, description="0-based subtitle track index (null = subtitles off)"
    )


class BlockTracksDataSchema(Schema):
    block_id: int = Field(..., description="Programme block that was updated")
    audio_track_index: int | None = Field(None, description="Audio track index now stored on the block")
    subtitle_track_index: int | None = Field(None, description="Subtitle track index now stored on the block")
    playlist_items_updated: int = Field(
        ..., description="Generated playlist items whose MoviePlayback was updated in step with the block"
    )


class BlockTracksResponseSchema(SuccessResponseSchema):
    data: BlockTracksDataSchema = Field(..., description="The stored track selection")


class UpdateProgrammeSchema(Schema):
    name: str | None = Field(None, description="Updated programme name")
    description: str | None = Field(None, description="Updated programme description")
    items: list[dict[str, Any]] | None = Field(None, description="Updated list of programme items")
    title_template_id: int | None = Field(None, description="Title template ID for programme title card")
    title_duration: int | None = Field(None, description="Override duration for title card in seconds")
    title_background_type: str | None = Field(None, description="Background type: color, image, or video")
    title_background_color: str | None = Field(None, description="Background color (hex format)")
    title_background_file: str | None = Field(None, description="Path to background image or video file")
    title_fade_in: float | None = Field(None, description="Fade in duration in seconds (0 = no fade)", ge=0, le=10)
    title_fade_out: float | None = Field(None, description="Fade out duration in seconds (0 = no fade)", ge=0, le=10)


management_api = Router()


@management_api.get("/list", response={200: ProgrammeListResponseSchema, 500: ErrorResponseSchema})
def list_programmes(request: HttpRequest, filters: ProgrammeListFilters = Query(...)):
    programmes = Programme.objects.all()

    if filters.search:
        programmes = programmes.filter(Q(name__icontains=filters.search) | Q(description__icontains=filters.search))

    programmes = programmes.select_related("template").prefetch_related("blocks").order_by("-created_at")

    programmes_data = []
    for programme in programmes:
        # Walk prefetched blocks in Python: .filter()/.count() would bypass the prefetch cache.
        blocks = list(programme.blocks.all())
        composition: dict[str, int] = {}
        for block in blocks:
            key = block.content_type or "system"
            composition[key] = composition.get(key, 0) + 1

        movies_info = []
        for block in (b for b in blocks if b.content_type == "movie"):
            movie = block.content_object
            if movie and hasattr(movie, "title"):
                movie_info = MovieInfoSchema(
                    id=movie.id,
                    title=movie.title,
                    year=getattr(movie, "year", None),
                    certification=getattr(movie, "certification", None),
                    # MovieInfoSchema runtime is in MINUTES (Movie.runtime), not seconds.
                    runtime=getattr(movie, "runtime", None),
                    thumbnail_url=getattr(movie, "thumbnail_url", None),
                )
                movies_info.append(movie_info)

        programme_data = ProgrammeListItemSchema(
            id=programme.id,
            name=programme.name,
            description=programme.description or "",
            total_runtime=programme.get_total_runtime_minutes() or 0.0,
            total_blocks=len(blocks),
            created_at=programme.created_at.isoformat(),
            last_played_at=programme.last_played_at.isoformat() if programme.last_played_at else None,
            template_name=programme.template.name if programme.template else None,
            playlist_stale=programme.playlist_stale,
            movies=movies_info,
            composition=composition,
        )
        programmes_data.append(programme_data)

    return Status(
        200,
        ProgrammeListResponseSchema(
            message="Programmes retrieved successfully",
            data=ProgrammeListResponseDataSchema(programmes=programmes_data, total=len(programmes_data)),
        ),
    )


@management_api.get("/active", response={200: ActiveProgrammeResponseSchema, 500: ErrorResponseSchema})
def get_active_programme(request: HttpRequest):
    # Stub: no active-programme tracking implemented yet.
    return Status(
        200,
        ActiveProgrammeResponseSchema(
            message="Active programme status retrieved successfully",
            data=ActiveProgrammeResponseDataSchema(active_programme=None),
        ),
    )


# Bulk route must be registered before /{programme_id} routes or it gets shadowed.
BULK_MAX_IDS = 500


def _validate_bulk_ids(ids: list[int]) -> list[int]:
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        raise ValidationError("No programme IDs provided")
    if len(unique_ids) > BULK_MAX_IDS:
        raise ValidationError(f"Too many programme IDs (maximum {BULK_MAX_IDS} per request)")
    return unique_ids


@management_api.post(
    "/bulk-delete",
    response={200: BulkDeleteResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def bulk_delete_programmes(request: HttpRequest, payload: BulkProgrammeIdsSchema):
    ids = _validate_bulk_ids(payload.ids)
    existing = set(Programme.objects.filter(id__in=ids).values_list("id", flat=True))
    missing = [programme_id for programme_id in ids if programme_id not in existing]

    if existing:
        Programme.objects.filter(id__in=existing).delete()
        logger.info(f"Bulk deleted {len(existing)} programmes: {sorted(existing)}")

    deleted = len(existing)
    noun = "programme" if deleted == 1 else "programmes"
    return Status(
        200,
        BulkDeleteResponseSchema(
            message=f"{deleted} {noun} deleted",
            data=BulkDeleteDataSchema(deleted=deleted, missing=missing),
        ),
    )


@management_api.get(
    "/{programme_id}", response={200: ProgrammeDetailResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def get_programme_detail(request: HttpRequest, programme_id: int):
    try:
        programme = Programme.objects.select_related("template").get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

    blocks = programme.blocks.all().order_by("order")

    items_data = []
    for block in blocks:
        block_title = f"Block {block.order}"
        block_runtime = 0.0
        block_details = {}

        if block.content_type == "movie":
            movie = block.movie
            if movie is not None:
                block_title = movie.title
                block_runtime = movie.duration or 0.0
                # Resolve chosen track indices to stored rows so the page can label them.
                selected_audio_track = None
                if block.audio_track_index is not None:
                    track = movie.audio_tracks.filter(index=block.audio_track_index).first()
                    if track:
                        selected_audio_track = {
                            "language": track.language,
                            "codec": track.codec,
                            "channels": track.channels,
                        }
                selected_subtitle_track = None
                if block.subtitle_track_index is not None:
                    track = movie.subtitle_tracks.filter(index=block.subtitle_track_index).first()
                    if track:
                        selected_subtitle_track = {
                            "language": track.language,
                            "forced": track.forced,
                            "sdh": track.sdh,
                        }
                block_details = {
                    "movie_id": movie.id,
                    "year": movie.year,
                    "certification": movie.certification,
                    "audio_track": block.audio_track_index,
                    "subtitle_track": block.subtitle_track_index,
                    "credits_command_id": block.credits_command_id,
                    "thumbnail_url": movie.thumbnail_url,
                    "director": movie.director or None,
                    "synopsis": movie.description or None,
                    "resolution": movie.resolution or None,
                    "file_size": movie.file_size or None,
                    "file_path": movie.file_path or None,
                    "selected_audio_track": selected_audio_track,
                    "selected_subtitle_track": selected_subtitle_track,
                }
            else:
                # Movie removed from library — describe from the block's cached snapshot.
                block_title = block.cached_title or "Movie no longer in library"
                block_runtime = 0.0
                block_details = {
                    "missing": True,
                    # FK is SET_NULL on deletion; no consumer reads this, kept for wire compatibility.
                    "orphan_movie_id": None,
                    "year": block.cached_year,
                    "audio_track": block.audio_track_index,
                    "subtitle_track": block.subtitle_track_index,
                }
        elif block.content_type == "trailer" and block.content_object:
            trailer = block.content_object
            block_title = trailer.title
            block_runtime = trailer.duration or 0.0
            block_details = {"trailer_id": trailer.id}
        elif block.content_type == "bumper":
            # A tag = random pick, else a specific clip.
            if block.random_tag:
                block_title = f"Random user media: {block.random_tag.name}"
                block_details = {
                    "tag_id": block.random_tag.id,
                    "tag_name": block.random_tag.name,
                    "count": block.random_count,
                }
            elif block.bumper:
                bumper = block.bumper
                block_title = bumper.title
                block_runtime = bumper.duration or 0.0
                block_details = {"bumper_id": bumper.id}
            else:
                block_title = "User media"
                block_details = {}
        elif block.content_type == "command" and block.content_object:
            command = block.content_object
            block_title = command.name
            block_runtime = (command.duration or 0.0) if block.hold_black else 0.0
            block_details = {
                "command_id": command.id,
                "command_name": command.name,
                "provider": command.provider,
                "duration": command.duration,
                "hold_black": block.hold_black,
            }
        elif block.content_type == "audio_bumper":
            block_runtime = 0.25
            if block.bumper:
                block_title = f"Audio intro: {block.bumper.title}"
            elif block.movie:
                block_title = f"Audio intro for {block.movie.title}"
            else:
                block_title = "Audio bumper"
            block_details = {
                "reference_movie_id": block.movie_id,
                "reference_movie_title": block.movie.title if block.movie else None,
                "bumper_id": block.bumper_id,
                "bumper_title": block.bumper.title if block.bumper else None,
            }
        elif block.content_type == "trailer_rule":
            if block.trailer_rule:
                rule = block.trailer_rule
                ref = rule.reference_movie
                block_title = f"Trailers: {ref.title if ref else 'by criteria'}"
                block_details = {
                    "rule_id": rule.id,
                    "reference_movie_id": ref.id if ref else None,
                    "reference_movie_title": ref.title if ref else None,
                    "count": rule.number_of_trailers or TrailerRule.DEFAULT_COUNT,
                    "genre_ids": list(rule.genres.values_list("id", flat=True)),
                    "certificate_ceiling": rule.certificate_ceiling or "",
                    "year_from": rule.year_from,
                    "year_to": rule.year_to,
                    "trailer_tag_id": rule.trailer_tag_id,
                    "trailer_tag_name": rule.trailer_tag.name if rule.trailer_tag else None,
                }
                if rule.trailer_tag:
                    block_title += f" (tag: {rule.trailer_tag.name})"
            elif block.bound_to_block_order is not None:
                block_title = "Trailers for random movie"
                if block.trailer_tag:
                    block_title += f" (tag: {block.trailer_tag.name})"
                block_details = {
                    "bound_to_block_order": block.bound_to_block_order,
                    "count": block.random_count or TrailerRule.DEFAULT_COUNT,
                    "match_genres": block.trailer_match_genres,
                    "match_certification": block.trailer_match_certification,
                    "year_delta": block.trailer_year_delta or 5,
                    "trailer_tag_id": block.trailer_tag_id,
                    "trailer_tag_name": block.trailer_tag.name if block.trailer_tag else None,
                }
            else:
                block_title = "Trailer Rule"
                block_details = {}
        elif block.content_type == "certification" and block.content_object:
            cert_obj = block.content_object
            # Cards are a fixed length; the reference movie's duration is irrelevant.
            block_runtime = float(CertificationService.CARD_SECONDS)
            block_title = f"{cert_obj.certification} Certificate"
            if hasattr(cert_obj, "movie"):  # Certification object
                block_details = {
                    "certification_id": cert_obj.id,
                    "reference_movie_id": cert_obj.movie.id,
                    "reference_movie_title": cert_obj.movie.title,
                    "certification": cert_obj.certification,
                }
            else:  # Movie object used for certification
                block_details = {
                    "certification_id": cert_obj.id,
                    "reference_movie_id": cert_obj.id,
                    "reference_movie_title": cert_obj.title,
                    "certification": cert_obj.certification,
                }
        elif block.content_type == "certification" and not block.content_object:
            # Certification for a random movie (no specific movie linked yet).
            filter_text = build_filter_description_from_block(block)
            genres = block.random_movie_genres.all()
            block_title = f"Certification (Random: {filter_text})"
            block_runtime = float(CertificationService.CARD_SECONDS)
            block_details = {
                "for_random_movie": True,
                "genre_ids": [g.id for g in genres],
                "genre_names": [g.name for g in genres],
                "certification": block.random_movie_certification or None,
                "year_from": block.random_movie_year_from,
                "year_to": block.random_movie_year_to,
                "runtime_from": block.random_movie_runtime_from,
                "runtime_to": block.random_movie_runtime_to,
            }
        elif block.content_type == "random_movie":
            filter_text = build_filter_description_from_block(block)
            genres = block.random_movie_genres.all()
            block_title = f"Random Movie ({filter_text})"
            block_runtime = 7200.0  # ~2h estimate for runtime display
            block_details = {
                "genre_ids": [g.id for g in genres],
                "genre_names": [g.name for g in genres],
                "certification": block.random_movie_certification or None,
                "year_from": block.random_movie_year_from,
                "year_to": block.random_movie_year_to,
                "runtime_from": block.random_movie_runtime_from,
                "runtime_to": block.random_movie_runtime_to,
                "count": block.random_count or 1,
                "matching_count": build_random_movie_query(block, exclude_empty_paths=True).count(),
                "filter_text": filter_text,
            }

        item_data = ProgrammeItemDetailSchema(
            id=block.id,
            order=block.order,
            type=block.content_type,
            title=block_title,
            runtime=block_runtime,
            details=block_details,
        )
        items_data.append(item_data)

    programme_detail = ProgrammeDetailSchema(
        id=programme.id,
        name=programme.name,
        description=programme.description or "",
        total_runtime=programme.get_total_runtime_minutes() or 0.0,
        created_at=programme.created_at.isoformat(),
        updated_at=programme.updated_at.isoformat(),
        template_id=programme.template.id if programme.template else None,
        template_name=programme.template.name if programme.template else None,
        total_blocks=len(items_data),
        playlist_stale=programme.playlist_stale,
        title_template_id=programme.title_template_id,
        title_duration=programme.title_duration,
        title_background_type=programme.title_background_type,
        title_background_color=programme.title_background_color or "#000000",
        title_background_file=programme.title_background_file or "",
        title_fade_in=programme.title_fade_in or 0.0,
        title_fade_out=programme.title_fade_out or 0.0,
        title_file_generated=bool(programme.title_file),
        items=items_data,
    )

    return Status(
        200,
        ProgrammeDetailResponseSchema(
            message=f"Programme '{programme.name}' retrieved successfully",
            data=ProgrammeDetailDataSchema(programme=programme_detail),
        ),
    )


@management_api.put(
    "/{programme_id}",
    response={
        200: ProgrammeDetailResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def update_programme(request: HttpRequest, programme_id: int, data: UpdateProgrammeSchema):
    ProgrammeService.update_programme(
        programme_id=programme_id,
        name=data.name,
        description=data.description,
        items=data.items,
        title_template_id=data.title_template_id,
        title_duration=data.title_duration,
        title_background_type=data.title_background_type,
        title_background_color=data.title_background_color,
        title_background_file=data.title_background_file,
        title_fade_in=data.title_fade_in,
        title_fade_out=data.title_fade_out,
    )

    return get_programme_detail(request, programme_id)


@management_api.patch(
    "/{programme_id}/blocks/{block_id}/tracks",
    response={
        200: BlockTracksResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def update_block_tracks(request: HttpRequest, programme_id: int, block_id: int, data: BlockTracksUpdateSchema):
    """Set the audio/subtitle track for a feature block; only fields present in the body change."""
    try:
        block = ProgrammeBlock.objects.select_related("movie", "programme").get(pk=block_id, programme_id=programme_id)
    except ProgrammeBlock.DoesNotExist:
        raise NotFoundError("Programme block not found", error_code="BLOCK_NOT_FOUND") from None

    if block.content_type != "movie":
        raise ValidationError("Track selection applies to feature blocks only", error_code="BLOCK_NOT_A_FEATURE")

    movie = block.movie
    if movie is None:
        raise ValidationError("This block's film is no longer in the library", error_code="BLOCK_MOVIE_MISSING")

    fields = data.model_fields_set
    if not fields:
        raise ValidationError("No track selection given", error_code="NO_TRACKS_GIVEN")

    if "audio_track_index" in fields and data.audio_track_index is not None:
        count = movie.audio_tracks.count()
        # A film with no track data still accepts index 0 (what "default" resolves to).
        limit = count or 1
        if data.audio_track_index >= limit:
            raise ValidationError(
                f"Audio track {data.audio_track_index} does not exist "
                f"({movie.title} has {count} audio track{'' if count == 1 else 's'})",
                error_code="AUDIO_TRACK_OUT_OF_RANGE",
            )
        block.audio_track_index = data.audio_track_index
    elif "audio_track_index" in fields:
        block.audio_track_index = None

    if "subtitle_track_index" in fields and data.subtitle_track_index is not None:
        count = movie.subtitle_tracks.count()
        if data.subtitle_track_index >= count:
            raise ValidationError(
                f"Subtitle track {data.subtitle_track_index} does not exist "
                f"({movie.title} has {count} subtitle track{'' if count == 1 else 's'})",
                error_code="SUBTITLE_TRACK_OUT_OF_RANGE",
            )
        block.subtitle_track_index = data.subtitle_track_index
    elif "subtitle_track_index" in fields:
        block.subtitle_track_index = None

    update_fields = [f for f in ("audio_track_index", "subtitle_track_index") if f in fields]
    block.save(update_fields=update_fields)

    # The generated playlist points at MoviePlayback wrappers, and that is what
    # mpv_service reads when the item loads — keep them in step so the change
    # takes effect on the next play without a regeneration.
    playbacks_updated = 0
    for item in block.playlist_items.filter(content_type="movie").select_related("movie_playback"):
        playback = item.movie_playback
        if playback is None:
            continue
        if "audio_track_index" in fields:
            playback.audio_track_index = block.audio_track_index
        if "subtitle_track_index" in fields:
            playback.subtitle_track_index = block.subtitle_track_index
        playback.save(update_fields=update_fields)
        playbacks_updated += 1

    logger.info(
        f"Block {block.id} ({movie.title}) tracks set to audio={block.audio_track_index} "
        f"subtitle={block.subtitle_track_index}; {playbacks_updated} playlist item(s) updated"
    )

    return Status(
        200,
        BlockTracksResponseSchema(
            message="Track selection saved",
            data=BlockTracksDataSchema(
                block_id=block.id,
                audio_track_index=block.audio_track_index,
                subtitle_track_index=block.subtitle_track_index,
                playlist_items_updated=playbacks_updated,
            ),
        ),
    )


@management_api.post(
    "/{programme_id}/run",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 422: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def run_programme(request: HttpRequest, programme_id: int):
    """
    Run a programme via the MPV service.

    This will start playback of the programme's playlist.
    """
    # Use service layer for business logic
    result = ProgrammeService.run_programme(programme_id)

    return Status(200, MessageResponseSchema(message=result["message"]))


@management_api.post(
    "/{programme_id}/duplicate",
    response={201: ProgrammeDuplicateResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def duplicate_programme(request: HttpRequest, programme_id: int):
    """
    Create a copy of an existing programme, including all of its blocks.

    The copy is named "<name> (copy)" and gets its own freshly generated
    playlist.
    """
    copy = ProgrammeService.duplicate_programme(programme_id)

    return Status(
        201,
        ProgrammeDuplicateResponseSchema(
            message="Programme duplicated successfully",
            data=ProgrammeDuplicateDataSchema(id=copy.id, name=copy.name),
        ),
    )


@management_api.delete(
    "/{programme_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def delete_programme(request: HttpRequest, programme_id: int):
    """
    Delete a programme and all its associated blocks.
    """
    # Use service layer for business logic
    result = ProgrammeService.delete_programme(programme_id)

    return Status(200, MessageResponseSchema(message=result["message"]))
