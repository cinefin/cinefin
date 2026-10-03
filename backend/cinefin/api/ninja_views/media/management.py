"""Media API — the user-media library (bumpers, idents, intros): items, tags, uploads and downloads."""

import logging
import os
import re
from pathlib import Path

from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.db import IntegrityError
from django.db.models import Count
from django.http import FileResponse, HttpRequest
from django.utils import timezone
from ninja import File, Form, Query, Router, Status, UploadedFile

from cinefin.api.exceptions import ConflictError, NotFoundError, ValidationError
from cinefin.api.models import AUDIO_FORMATS, Bumper, Settings, Tag
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema
from cinefin.api.services import media_service, standby
from cinefin.api.utils.media_paths import to_usermedia_relative, usermedia_abs_path
from cinefin.api.utils.paths import contained_in

from .schemas import (
    BulkTagResponseSchema,
    BulkTagSchema,
    CreateMediaSchema,
    MediaCreateResponseSchema,
    MediaDetailSchema,
    MediaListFilters,
    MediaListResponseSchema,
    TagCreateSchema,
    TagListFilters,
    TagListResponseSchema,
    TagResponseSchema,
    TagUpdateSchema,
    UpdateMediaSchema,
    YouTubeDownloadSchema,
    YouTubeProgressSchema,
    YouTubeTaskResponseSchema,
)
from .utils import generate_screenshot, get_file_mime_type, get_media_duration, validate_video_file

logger = logging.getLogger(__name__)

# One router: the literal and /{media_id}/… paths are registered before the /{media_id} catch-all.
media_api = Router()

E400 = {400: ErrorResponseSchema}
E404 = {404: ErrorResponseSchema}
E500 = {500: ErrorResponseSchema}
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def normalize_color(raw: str | None) -> str:
    """Validate and normalise a #RRGGBB colour. '' / None clear it."""
    if not raw:
        return ""
    value = raw.strip()
    if not _HEX_COLOR_RE.match(value):
        raise ValidationError("Colour must be a #RRGGBB hex value", error_code="INVALID_COLOR")
    return value.lower()


def tag_schema(tag: Tag, count: int | None = None) -> dict:
    return {"id": tag.id, "name": tag.name, "color": tag.color or None, "count": count}


def _get_media(media_id: int, queryset=Bumper.objects) -> Bumper:
    try:
        return queryset.get(pk=media_id)
    except Bumper.DoesNotExist:
        raise NotFoundError("Media not found", error_code="MEDIA_NOT_FOUND") from None


def _get_tag(tag_id: int) -> Tag:
    try:
        return Tag.objects.get(pk=tag_id)
    except Tag.DoesNotExist:
        raise NotFoundError("Tag not found", error_code="TAG_NOT_FOUND") from None


def _clean_tag_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValidationError("Tag name cannot be empty", error_code="EMPTY_TAG_NAME")
    return name


def _paginate(queryset, page: int, per_page: int):
    """(page, pagination dict); an out-of-range page clamps to the last one."""
    paginator = Paginator(queryset, per_page)
    try:
        current = paginator.page(page)
    except EmptyPage:
        current = paginator.page(paginator.num_pages)
    return current, {
        "page": current.number,
        "per_page": per_page,
        "total": paginator.count,
        "total_pages": paginator.num_pages,
        "has_previous": current.has_previous(),
        "has_next": current.has_next(),
    }


def serialize_media_item(media: Bumper, request: HttpRequest) -> dict:
    file_url = None
    file_exists = False
    file_size = media.file_size or None
    mime_type = media.mime_type or None

    abs_path = usermedia_abs_path(media.file_path)
    if abs_path and os.path.exists(abs_path):
        file_exists = True
        file_size = file_size or os.path.getsize(abs_path)
        mime_type = mime_type or get_file_mime_type(abs_path)
        file_url = request.build_absolute_uri(f"/api/v2/media/{media.id}/download")

    return {
        "id": media.id,
        "title": media.title,
        "duration": media.duration,
        "file_path": media.file_path,
        "file_url": file_url,
        "screenshot_url": request.build_absolute_uri(media.screenshot_url) if media.screenshot_url else None,
        "file_info": {"size": file_size, "mime_type": mime_type, "exists": file_exists},
        "tags": [{"id": tag.id, "name": tag.name, "color": tag.color or None} for tag in media.tags.all()],
        "upload_date": media.upload_date.isoformat() if media.upload_date else None,
        "audio_format": media.audio_format or None,
        "hold_point": media.hold_point,
    }


@media_api.post("/upload", response={201: MediaCreateResponseSchema, **E400, **E500})
def upload_media(
    request: HttpRequest,
    title: str = Form(..., description="Media title"),
    file: UploadedFile = File(..., description="Video file to upload"),
    tag_names: str | None = Form(None, description="Comma-separated tag names"),
):
    tag_list = [tag.strip() for tag in (tag_names or "").split(",") if tag.strip()]
    media, info = media_service.MediaService.process_file_upload(
        file=file,
        title=title,
        tag_names=tag_list,
        max_size_mb=getattr(settings, "MAX_MEDIA_UPLOAD_SIZE_MB", 500),
    )
    screenshot_url = None
    if info["screenshot_generated"]:
        screenshot_url = request.build_absolute_uri(f"/api/v2/media/{media.id}/screenshot")
    return Status(
        201,
        {
            "success": True,
            "message": f"Media '{media.title}' uploaded successfully",
            "data": {
                "id": media.id,
                "title": media.title,
                "duration": info["duration"],
                "file_path": info["file_path"],
                "file_url": request.build_absolute_uri(f"/api/v2/media/{media.id}/download"),
                "screenshot_url": screenshot_url,
                "screenshot_generated": info["screenshot_generated"],
                "tags": [{"id": tag.id, "name": tag.name} for tag in info["tags"]],
            },
        },
    )


@media_api.post("/youtube-download", response={202: YouTubeTaskResponseSchema, **E400, **E500})
def youtube_download(request: HttpRequest, data: YouTubeDownloadSchema):
    task_id = media_service.MediaService.start_youtube_download(
        url=data.url, title=data.title, tag_names=data.tag_names or []
    )
    return Status(202, {"success": True, "message": "YouTube download task started", "data": {"task_id": task_id}})


@media_api.get("/youtube-progress/{task_id}", response={200: YouTubeProgressSchema, **E404, **E500})
def youtube_progress(request: HttpRequest, task_id: str):
    task_data = media_service.MediaService.get_youtube_download_progress(task_id)
    if not task_data:
        raise NotFoundError("Download task not found or expired", error_code="TASK_NOT_FOUND")
    return {
        "success": True,
        "message": f"Download task status: {task_data['status']}",
        "data": task_data,
    }


@media_api.get("/{media_id}/download", response={200: None, **E404, **E500})
def download_media(request: HttpRequest, media_id: int, inline: bool = False):
    media = _get_media(media_id)

    # Traversal guard — a poisoned row must not walk the filesystem.
    abs_path = usermedia_abs_path(media.file_path)
    if (
        not abs_path
        or not os.path.isabs(abs_path)
        or ".." in media.file_path.split(os.sep)
        or not os.path.exists(abs_path)
    ):
        raise NotFoundError("Media file not found on disk", error_code="FILE_NOT_FOUND")

    name = Path(abs_path).name
    content_type = (media.mime_type or "video/mp4") if inline else "application/octet-stream"
    response = FileResponse(open(abs_path, "rb"), content_type=content_type, filename=name)
    response["Content-Length"] = str(os.path.getsize(abs_path))
    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = f'{"inline" if inline else "attachment"}; filename="{name}"'
    logger.info(f"Serving media file: {media.title} ({name})")
    return response


@media_api.get("/{media_id}/screenshot", response={200: None, **E404, **E500})
def get_media_screenshot(request: HttpRequest, media_id: int):
    media = _get_media(media_id)
    if not media.screenshot:
        raise NotFoundError("Screenshot not available for this media", error_code="SCREENSHOT_NOT_FOUND")

    # Refuse anything resolving outside MEDIA_ROOT.
    path = os.path.realpath(os.path.join(settings.MEDIA_ROOT, media.screenshot))
    if not contained_in(path, settings.MEDIA_ROOT) or not os.path.exists(path):
        raise NotFoundError("Screenshot file not found on disk", error_code="SCREENSHOT_FILE_NOT_FOUND")
    return FileResponse(open(path, "rb"), content_type="image/jpeg", filename=f"{media.title}_screenshot.jpg")


@media_api.get("/list", response={200: MediaListResponseSchema, **E500})
def list_media(request: HttpRequest, filters: MediaListFilters = Query(...)):
    per_page = min(filters.per_page, 100)
    media_query = Bumper.objects.all()
    if filters.search:
        media_query = media_query.filter(title__icontains=filters.search)
    # ANY (OR) semantics: an item carrying any selected tag matches.
    tag_names = [name.strip() for name in (filters.tags or "").split(",") if name.strip()]
    if tag_names:
        media_query = media_query.filter(tags__name__in=tag_names).distinct()

    sort_field = (
        filters.sort
        if filters.sort in {"title", "duration", "file_size", "upload_date", "audio_format"}
        else "upload_date"
    )
    prefix = "" if (filters.order or "desc").lower() == "asc" else "-"
    media_page, pagination = _paginate(
        media_query.prefetch_related("tags").order_by(f"{prefix}{sort_field}", "id"), filters.page, per_page
    )

    # Counts span the whole library, not the filtered page.
    tags_with_counts = Tag.objects.annotate(item_count=Count("bumper")).order_by("name")
    return {
        "success": True,
        "message": "Media list retrieved successfully",
        "data": {
            "media": [serialize_media_item(media, request) for media in media_page],
            "pagination": pagination,
            "filters": {
                "tags": [tag.name for tag in tags_with_counts],
                "tag_facets": [tag_schema(tag, count=tag.item_count) for tag in tags_with_counts],
            },
        },
    }


@media_api.get("/tags", response={200: TagListResponseSchema, **E500})
def list_tags(request: HttpRequest, filters: TagListFilters = Query(...)):
    tags_query = Tag.objects.annotate(item_count=Count("bumper"))
    if filters.search:
        tags_query = tags_query.filter(name__icontains=filters.search)
    tags_page, pagination = _paginate(tags_query.order_by("name"), filters.page, min(filters.per_page, 100))
    return {
        "success": True,
        "message": "Tags retrieved successfully",
        "data": {"tags": [tag_schema(tag, count=tag.item_count) for tag in tags_page], "pagination": pagination},
    }


@media_api.post("/tags", response={201: TagResponseSchema, **E400, 409: ErrorResponseSchema, **E500})
def create_tag(request: HttpRequest, data: TagCreateSchema):
    """Create a tag (optionally with a colour). Names are unique."""
    name = _clean_tag_name(data.name)
    color = normalize_color(data.color)
    if Tag.objects.filter(name=name).exists():
        raise ConflictError(f"A tag named '{name}' already exists", error_code="TAG_EXISTS")
    tag = Tag.objects.create(name=name, color=color)
    return Status(201, {"success": True, "message": f"Tag '{name}' created", "data": tag_schema(tag, count=0)})


@media_api.put("/tags/{tag_id}", response={200: TagResponseSchema, **E400, **E404, 409: ErrorResponseSchema})
def update_tag(request: HttpRequest, tag_id: int, data: TagUpdateSchema):
    tag = _get_tag(tag_id)
    if data.name is not None:
        name = _clean_tag_name(data.name)
        if Tag.objects.filter(name=name).exclude(pk=tag.pk).exists():
            raise ConflictError(f"A tag named '{name}' already exists", error_code="TAG_EXISTS")
        tag.name = name
    if data.color is not None:
        tag.color = normalize_color(data.color)
    try:
        tag.save()
    except IntegrityError:
        raise ConflictError("A tag with that name already exists", error_code="TAG_EXISTS") from None
    return {
        "success": True,
        "message": f"Tag '{tag.name}' updated",
        "data": tag_schema(tag, tag.bumper_set.count()),
    }


@media_api.delete("/tags/{tag_id}", response={200: MessageResponseSchema, **E404, **E500})
def delete_tag(request: HttpRequest, tag_id: int):
    """Delete a tag, untagging (not deleting) every media item that carries it."""
    tag = _get_tag(tag_id)
    tag.delete()
    return {"success": True, "message": f"Tag '{tag.name}' deleted"}


@media_api.post("/bulk-tag", response={200: BulkTagResponseSchema, **E400, **E500})
def bulk_tag(request: HttpRequest, data: BulkTagSchema):
    ids = list(dict.fromkeys(data.ids))
    if not ids:
        raise ValidationError("No media IDs provided", error_code="NO_IDS")
    if len(ids) > 500:
        raise ValidationError("Too many media IDs (maximum 500 per request)", error_code="TOO_MANY_IDS")
    action = (data.action or "add").lower()
    if action not in ("add", "remove"):
        raise ValidationError("action must be 'add' or 'remove'", error_code="INVALID_ACTION")
    tag_name = _clean_tag_name(data.tag)

    items = list(Bumper.objects.filter(id__in=ids))
    found_ids = {item.id for item in items}
    missing = [i for i in ids if i not in found_ids]

    if action == "add":
        tag_obj, _ = Tag.objects.get_or_create(name=tag_name)
    else:
        tag_obj = Tag.objects.filter(name=tag_name).first()
    updated = 0
    if tag_obj is not None:
        for item in items:
            (item.tags.add if action == "add" else item.tags.remove)(tag_obj)
        updated = len(items)

    verb = "tagged" if action == "add" else "untagged"
    noun = "item" if updated == 1 else "items"
    return {
        "success": True,
        "message": f"{updated} {noun} {verb} '{tag_name}'",
        "data": {
            "updated": updated,
            "missing": missing,
            "action": action,
            "tag": tag_schema(tag_obj, count=tag_obj.bumper_set.count()) if tag_obj else None,
        },
    }


@media_api.post("/create", response={201: MediaCreateResponseSchema, **E400, **E404, **E500})
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
    for tag_name in data.tag_names or []:
        media.tags.add(Tag.objects.get_or_create(name=tag_name.strip())[0])

    screenshot_generated = False
    if duration:
        screenshot_filename = f"{media.id}_screenshot.jpg"
        screenshot_path = os.path.join(settings.MEDIA_ROOT, "screenshots", screenshot_filename)
        os.makedirs(os.path.dirname(screenshot_path), exist_ok=True)
        screenshot_generated = generate_screenshot(data.file_path, screenshot_path, duration=duration)
        if screenshot_generated:
            media.screenshot = f"screenshots/{screenshot_filename}"
            media.save()

    logger.info(f"Created media: {media.title}")
    return Status(
        201,
        {
            "success": True,
            "message": f"Media '{media.title}' created successfully",
            "data": {
                "id": media.id,
                "title": media.title,
                "duration": duration,
                "file_path": data.file_path,
                "file_url": request.build_absolute_uri(f"/api/v2/media/{media.id}/download"),
                "screenshot_url": request.build_absolute_uri(media.screenshot_url) if media.screenshot_url else None,
                "screenshot_generated": screenshot_generated,
                "tags": [{"id": tag.id, "name": tag.name} for tag in media.tags.all()],
                "upload_date": media.upload_date.isoformat() if media.upload_date else None,
            },
        },
    )


@media_api.get("/{media_id}", response={200: MediaDetailSchema, **E404, **E500})
def get_media_detail(request: HttpRequest, media_id: int):
    media = _get_media(media_id, Bumper.objects.prefetch_related("tags"))
    return {
        "success": True,
        "message": f"Media '{media.title}' retrieved successfully",
        "data": serialize_media_item(media, request),
    }


@media_api.put("/{media_id}", response={200: MediaDetailSchema, **E400, **E404, **E500})
def update_media(request: HttpRequest, media_id: int, data: UpdateMediaSchema):
    media = _get_media(media_id)
    if data.title is not None:
        if not data.title.strip():
            raise ValidationError("Title cannot be empty", error_code="EMPTY_TITLE")
        media.title = data.title.strip()
    if data.tag_names is not None:
        media.tags.clear()
        for tag_name in data.tag_names:
            if tag_name.strip():
                media.tags.add(Tag.objects.get_or_create(name=tag_name.strip())[0])
    if data.audio_format is not None:  # '' clears it
        media.audio_format = data.audio_format if data.audio_format in {key for key, _ in AUDIO_FORMATS} else ""

    hold_changed = "hold_point" in data.model_fields_set and data.hold_point != media.hold_point
    if hold_changed:  # sent as null: back to the last frame
        media.hold_point = data.hold_point
    media.save()
    if hold_changed and Settings.get("cinema.default_ident_id") == media.id:
        standby.push()  # the ident's hold is in the players' standby spec
    return get_media_detail(request, media_id)


@media_api.delete("/{media_id}", response={200: MessageResponseSchema, **E404, **E500})
def delete_media(request: HttpRequest, media_id: int):
    """Delete the DB entry only, not the file on disk."""
    media = _get_media(media_id)
    media.delete()
    if Settings.get("cinema.default_ident_id") == media_id:
        standby.push()  # standby falls back to the System Ident
    logger.info(f"Deleted media: {media.title}")
    return {"success": True, "message": f"Media '{media.title}' deleted successfully"}


@media_api.post("/thumbnails/regenerate", response={200: MessageResponseSchema, **E404})
def regenerate_thumbnails(request: HttpRequest, media_id: int | None = None):
    if media_id is not None and not Bumper.objects.filter(pk=media_id).exists():
        raise NotFoundError("Media not found", error_code="MEDIA_NOT_FOUND")
    counts = media_service.MediaService.regenerate_thumbnails(media_id)
    bits = [f"{counts['regenerated']} regenerated"]
    bits += [f"{counts[k]} {k}" for k in ("skipped", "failed") if counts[k]]
    return {"success": True, "message": "Thumbnails: " + ", ".join(bits)}
