import logging
import os
import re
from typing import Any

from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.db import IntegrityError
from django.db.models import Count
from django.http import HttpRequest
from django.utils import timezone
from ninja import Query, Router, Status

from cinefin.api.exceptions import ConflictError, NotFoundError, ValidationError
from cinefin.api.models import AUDIO_FORMATS, Bumper, Tag
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema
from cinefin.api.utils.media_paths import to_usermedia_relative, usermedia_abs_path

from .schemas import (
    BulkTagDataSchema,
    BulkTagResponseSchema,
    BulkTagSchema,
    CreateMediaSchema,
    MediaCreateDataSchema,
    MediaCreateResponseSchema,
    MediaDetailDataSchema,
    MediaDetailSchema,
    MediaFiltersSchema,
    MediaItemSchema,
    MediaListDataSchema,
    MediaListFilters,
    MediaListResponseSchema,
    MediaPaginationSchema,
    TagCreateSchema,
    TagListDataSchema,
    TagListFilters,
    TagListResponseSchema,
    TagResponseSchema,
    TagSchema,
    TagUpdateSchema,
    UpdateMediaSchema,
)
from .utils import generate_screenshot, get_file_mime_type, get_media_duration, validate_video_file

logger = logging.getLogger(__name__)

management_api = Router()

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_color(raw: str | None) -> str:
    """Validate and normalise a #RRGGBB colour. '' / None clear it."""
    if not raw:
        return ""
    value = raw.strip()
    if not _HEX_COLOR_RE.match(value):
        raise ValidationError("Colour must be a #RRGGBB hex value", error_code="INVALID_COLOR")
    return value.lower()


def tag_schema(tag: Tag, count: int | None = None) -> TagSchema:
    """Serialise a Tag, optionally carrying its item count."""
    return TagSchema(id=tag.id, name=tag.name, color=tag.color or None, count=count)


def serialize_media_item(media: Bumper, request: HttpRequest) -> dict[str, Any]:
    file_url = None
    screenshot_url = None
    file_exists = False
    file_size = media.file_size or None
    mime_type = media.mime_type or None

    abs_path = usermedia_abs_path(media.file_path)
    if abs_path and os.path.exists(abs_path):
        file_exists = True
        if not file_size:
            file_size = os.path.getsize(abs_path)
        if not mime_type:
            mime_type = get_file_mime_type(abs_path)

        file_url = request.build_absolute_uri(f"/api/v2/media/{media.id}/download")

    if media.screenshot_url:
        screenshot_url = request.build_absolute_uri(media.screenshot_url)

    return {
        "id": media.id,
        "title": media.title,
        "duration": media.duration,
        "file_path": media.file_path,
        "file_url": file_url,
        "screenshot_url": screenshot_url,
        "file_info": {"size": file_size, "mime_type": mime_type, "exists": file_exists},
        "tags": [{"id": tag.id, "name": tag.name, "color": tag.color or None} for tag in media.tags.all()],
        "upload_date": media.upload_date.isoformat() if media.upload_date else None,
        "audio_format": media.audio_format or None,
    }


@management_api.get("/list", response={200: MediaListResponseSchema, 500: ErrorResponseSchema})
def list_media(request: HttpRequest, filters: MediaListFilters = Query(...)):
    per_page = min(filters.per_page, 100)

    media_query = Bumper.objects.all()

    if filters.search:
        media_query = media_query.filter(title__icontains=filters.search)

    # ANY (OR) semantics: an item carrying any selected tag matches.
    if filters.tags:
        tag_names = [name.strip() for name in filters.tags.split(",") if name.strip()]
        if tag_names:
            media_query = media_query.filter(tags__name__in=tag_names).distinct()

    media_query = media_query.prefetch_related("tags")

    _sortable = {"title", "duration", "file_size", "upload_date", "audio_format"}
    sort_field = filters.sort if filters.sort in _sortable else "upload_date"
    prefix = "" if (filters.order or "desc").lower() == "asc" else "-"
    ordering = f"{prefix}{sort_field}"

    try:
        paginator = Paginator(media_query.order_by(ordering, "id"), per_page)
        media_page = paginator.page(filters.page)
    except EmptyPage:
        media_page = paginator.page(paginator.num_pages)

    media_items = []
    for media in media_page:
        media_data = serialize_media_item(media, request)
        media_items.append(MediaItemSchema(**media_data))

    # Counts span the whole library, not the filtered page.
    tags_with_counts = Tag.objects.annotate(item_count=Count("bumper")).order_by("name")
    available_tags = [tag.name for tag in tags_with_counts]
    tag_facets = [tag_schema(tag, count=tag.item_count) for tag in tags_with_counts]

    pagination = MediaPaginationSchema(
        page=media_page.number,
        per_page=per_page,
        total=paginator.count,
        total_pages=paginator.num_pages,
        has_previous=media_page.has_previous(),
        has_next=media_page.has_next(),
    )

    filters_info = MediaFiltersSchema(tags=available_tags, tag_facets=tag_facets)

    return Status(
        200,
        MediaListResponseSchema(
            success=True,
            message="Media list retrieved successfully",
            data=MediaListDataSchema(media=media_items, pagination=pagination, filters=filters_info),
        ),
    )


@management_api.get("/tags", response={200: TagListResponseSchema, 500: ErrorResponseSchema})
def list_tags(request: HttpRequest, filters: TagListFilters = Query(...)):
    per_page = min(filters.per_page, 100)

    tags_query = Tag.objects.annotate(item_count=Count("bumper"))

    if filters.search:
        tags_query = tags_query.filter(name__icontains=filters.search)

    try:
        paginator = Paginator(tags_query.order_by("name"), per_page)
        tags_page = paginator.page(filters.page)
    except EmptyPage:
        tags_page = paginator.page(paginator.num_pages)

    tag_items = [tag_schema(tag, count=tag.item_count) for tag in tags_page]

    pagination = MediaPaginationSchema(
        page=tags_page.number,
        per_page=per_page,
        total=paginator.count,
        total_pages=paginator.num_pages,
        has_previous=tags_page.has_previous(),
        has_next=tags_page.has_next(),
    )

    return Status(
        200,
        TagListResponseSchema(
            success=True,
            message="Tags retrieved successfully",
            data=TagListDataSchema(tags=tag_items, pagination=pagination),
        ),
    )


@management_api.post(
    "/tags",
    response={201: TagResponseSchema, 400: ErrorResponseSchema, 409: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def create_tag(request: HttpRequest, data: TagCreateSchema):
    """Create a tag (optionally with a colour). Names are unique."""
    name = data.name.strip()
    if not name:
        raise ValidationError("Tag name cannot be empty", error_code="EMPTY_TAG_NAME")
    color = normalize_color(data.color)
    if Tag.objects.filter(name=name).exists():
        raise ConflictError(f"A tag named '{name}' already exists", error_code="TAG_EXISTS")
    tag = Tag.objects.create(name=name, color=color)
    return Status(201, TagResponseSchema(success=True, message=f"Tag '{name}' created", data=tag_schema(tag, count=0)))


@management_api.put(
    "/tags/{tag_id}",
    response={200: TagResponseSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema, 409: ErrorResponseSchema},
)
def update_tag(request: HttpRequest, tag_id: int, data: TagUpdateSchema):
    try:
        tag = Tag.objects.get(pk=tag_id)
    except Tag.DoesNotExist:
        raise NotFoundError("Tag not found", error_code="TAG_NOT_FOUND") from None

    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise ValidationError("Tag name cannot be empty", error_code="EMPTY_TAG_NAME")
        if Tag.objects.filter(name=name).exclude(pk=tag.pk).exists():
            raise ConflictError(f"A tag named '{name}' already exists", error_code="TAG_EXISTS")
        tag.name = name

    if data.color is not None:
        tag.color = normalize_color(data.color)

    try:
        tag.save()
    except IntegrityError:
        raise ConflictError("A tag with that name already exists", error_code="TAG_EXISTS") from None

    count = tag.bumper_set.count()
    return Status(
        200, TagResponseSchema(success=True, message=f"Tag '{tag.name}' updated", data=tag_schema(tag, count))
    )


@management_api.delete(
    "/tags/{tag_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def delete_tag(request: HttpRequest, tag_id: int):
    """Delete a tag, untagging every media item that carries it."""
    try:
        tag = Tag.objects.get(pk=tag_id)
    except Tag.DoesNotExist:
        raise NotFoundError("Tag not found", error_code="TAG_NOT_FOUND") from None

    name = tag.name
    tag.delete()  # M2M rows cascade, so items are untagged, not deleted
    return Status(200, MessageResponseSchema(success=True, message=f"Tag '{name}' deleted"))


@management_api.post(
    "/bulk-tag",
    response={200: BulkTagResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def bulk_tag(request: HttpRequest, data: BulkTagSchema):
    ids = list(dict.fromkeys(data.ids))
    if not ids:
        raise ValidationError("No media IDs provided", error_code="NO_IDS")
    if len(ids) > 500:
        raise ValidationError("Too many media IDs (maximum 500 per request)", error_code="TOO_MANY_IDS")

    action = (data.action or "add").lower()
    if action not in ("add", "remove"):
        raise ValidationError("action must be 'add' or 'remove'", error_code="INVALID_ACTION")

    tag_name = data.tag.strip()
    if not tag_name:
        raise ValidationError("Tag name cannot be empty", error_code="EMPTY_TAG_NAME")

    items = list(Bumper.objects.filter(id__in=ids))
    found_ids = {item.id for item in items}
    missing = [i for i in ids if i not in found_ids]

    tag_obj: Tag | None = None
    updated = 0
    if action == "add":
        tag_obj, _ = Tag.objects.get_or_create(name=tag_name)
        for item in items:
            item.tags.add(tag_obj)
            updated += 1
    else:
        tag_obj = Tag.objects.filter(name=tag_name).first()
        if tag_obj is not None:
            for item in items:
                item.tags.remove(tag_obj)
                updated += 1

    tag_out = tag_schema(tag_obj, count=tag_obj.bumper_set.count()) if tag_obj else None
    verb = "tagged" if action == "add" else "untagged"
    noun = "item" if updated == 1 else "items"
    return Status(
        200,
        BulkTagResponseSchema(
            success=True,
            message=f"{updated} {noun} {verb} '{tag_name}'",
            data=BulkTagDataSchema(updated=updated, missing=missing, action=action, tag=tag_out),
        ),
    )


@management_api.post(
    "/create",
    response={
        201: MediaCreateResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def create_media(request: HttpRequest, data: CreateMediaSchema):
    if not os.path.exists(data.file_path):
        raise NotFoundError(f"File not found: {data.file_path}", error_code="FILE_NOT_FOUND")

    is_valid, error_msg = validate_video_file(data.file_path)
    if not is_valid:
        raise ValidationError(error_msg, error_code="INVALID_VIDEO_FILE")

    duration = get_media_duration(data.file_path)

    # duration coerced: a failed probe must not violate the NOT NULL column.
    media = Bumper.objects.create(
        title=data.title,
        file_path=to_usermedia_relative(data.file_path),
        duration=int(duration or 0),
        upload_date=timezone.now(),
    )

    if data.tag_names:
        for tag_name in data.tag_names:
            tag, created = Tag.objects.get_or_create(name=tag_name.strip())
            media.tags.add(tag)

    screenshot_generated = False
    if duration:
        screenshot_filename = f"{media.id}_screenshot.jpg"
        screenshot_path = os.path.join(settings.MEDIA_ROOT, "screenshots", screenshot_filename)

        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)

        screenshot_generated = generate_screenshot(data.file_path, screenshot_path, duration=duration)

        if screenshot_generated:
            media.screenshot = f"screenshots/{screenshot_filename}"
            media.save()

    file_url = request.build_absolute_uri(f"/api/v2/media/{media.id}/download")
    screenshot_url = None
    if media.screenshot_url:
        screenshot_url = request.build_absolute_uri(media.screenshot_url)

    response_data = MediaCreateDataSchema(
        id=media.id,
        title=media.title,
        duration=duration,
        file_path=data.file_path,
        file_url=file_url,
        screenshot_url=screenshot_url,
        screenshot_generated=screenshot_generated,
        tags=[TagSchema(id=tag.id, name=tag.name) for tag in media.tags.all()],
        upload_date=media.upload_date.isoformat() if media.upload_date else None,
    )

    logger.info(f"Created media: {media.title}")

    return Status(
        201,
        MediaCreateResponseSchema(
            success=True, message=f"Media '{media.title}' created successfully", data=response_data
        ),
    )


@management_api.get(
    "/{media_id}", response={200: MediaDetailSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def get_media_detail(request: HttpRequest, media_id: int):
    try:
        media = Bumper.objects.prefetch_related("tags").get(pk=media_id)
    except Bumper.DoesNotExist:
        raise NotFoundError("Media not found", error_code="MEDIA_NOT_FOUND") from None

    media_data = serialize_media_item(media, request)

    return Status(
        200,
        MediaDetailSchema(
            success=True,
            message=f"Media '{media.title}' retrieved successfully",
            data=MediaDetailDataSchema(**media_data),
        ),
    )


@management_api.put(
    "/{media_id}",
    response={200: MediaDetailSchema, 400: ErrorResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def update_media(request: HttpRequest, media_id: int, data: UpdateMediaSchema):
    try:
        media = Bumper.objects.get(pk=media_id)
    except Bumper.DoesNotExist:
        raise NotFoundError("Media not found", error_code="MEDIA_NOT_FOUND") from None

    if data.title is not None:
        if not data.title.strip():
            raise ValidationError("Title cannot be empty", error_code="EMPTY_TITLE")
        media.title = data.title.strip()

    if data.tag_names is not None:
        media.tags.clear()
        for tag_name in data.tag_names:
            if tag_name.strip():
                tag, created = Tag.objects.get_or_create(name=tag_name.strip())
                media.tags.add(tag)

    if data.audio_format is not None:  # '' clears it
        valid = {key for key, _ in AUDIO_FORMATS}
        media.audio_format = data.audio_format if data.audio_format in valid else ""

    media.save()

    return get_media_detail(request, media_id)


@management_api.delete(
    "/{media_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def delete_media(request: HttpRequest, media_id: int):
    """Delete the DB entry only, not the file on disk."""
    try:
        media = Bumper.objects.get(pk=media_id)
    except Bumper.DoesNotExist:
        raise NotFoundError("Media not found", error_code="MEDIA_NOT_FOUND") from None

    media_title = media.title
    media.delete()

    logger.info(f"Deleted media: {media_title}")

    return Status(200, MessageResponseSchema(success=True, message=f"Media '{media_title}' deleted successfully"))


@management_api.post("/thumbnails/regenerate", response={200: MessageResponseSchema, 404: ErrorResponseSchema})
def regenerate_thumbnails(request: HttpRequest, media_id: int | None = None):
    from cinefin.api.services.media_service import MediaService

    if media_id is not None and not Bumper.objects.filter(pk=media_id).exists():
        raise NotFoundError("Media not found", error_code="MEDIA_NOT_FOUND")

    counts = MediaService.regenerate_thumbnails(media_id)
    bits = [f"{counts['regenerated']} regenerated"]
    if counts["skipped"]:
        bits.append(f"{counts['skipped']} skipped")
    if counts["failed"]:
        bits.append(f"{counts['failed']} failed")
    return Status(200, MessageResponseSchema(success=True, message="Thumbnails: " + ", ".join(bits)))
