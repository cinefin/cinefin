import logging
import os
from pathlib import Path

from django.http import FileResponse, HttpRequest
from ninja import Router

from cinefin.api.exceptions import NotFoundError
from cinefin.api.models import Bumper
from cinefin.api.schemas.base import ErrorResponseSchema
from cinefin.api.utils.media_paths import usermedia_abs_path

logger = logging.getLogger(__name__)

movies_api = Router()


@movies_api.get("/{media_id}/download", response={200: None, 404: ErrorResponseSchema, 500: ErrorResponseSchema})
def download_media(request: HttpRequest, media_id: int, inline: bool = False):
    try:
        media = Bumper.objects.get(pk=media_id)
    except Bumper.DoesNotExist:
        raise NotFoundError("Media not found", error_code="MEDIA_NOT_FOUND") from None

    # Traversal guard — a poisoned row must not walk the filesystem.
    abs_path = usermedia_abs_path(media.file_path)
    if not abs_path or not os.path.isabs(abs_path) or ".." in media.file_path.split(os.sep):
        raise NotFoundError("Media file not found on disk", error_code="FILE_NOT_FOUND")
    if not os.path.exists(abs_path):
        raise NotFoundError("Media file not found on disk", error_code="FILE_NOT_FOUND")

    file_path = Path(abs_path)
    file_size = os.path.getsize(abs_path)

    content_type = (media.mime_type or "video/mp4") if inline else "application/octet-stream"
    disposition = "inline" if inline else "attachment"

    response = FileResponse(open(abs_path, "rb"), content_type=content_type, filename=file_path.name)

    response["Content-Length"] = str(file_size)
    response["Accept-Ranges"] = "bytes"
    response["Content-Disposition"] = f'{disposition}; filename="{file_path.name}"'

    logger.info(f"Serving media file: {media.title} ({file_path.name})")

    return response


@movies_api.get("/{media_id}/screenshot", response={200: None, 404: ErrorResponseSchema, 500: ErrorResponseSchema})
def get_media_screenshot(request: HttpRequest, media_id: int):
    try:
        media = Bumper.objects.get(pk=media_id)
    except Bumper.DoesNotExist:
        raise NotFoundError("Media not found", error_code="MEDIA_NOT_FOUND") from None

    if not media.screenshot:
        raise NotFoundError("Screenshot not available for this media", error_code="SCREENSHOT_NOT_FOUND")

    # Refuse anything resolving outside MEDIA_ROOT.
    from django.conf import settings

    from cinefin.api.utils.paths import contained_in

    screenshot_path = os.path.realpath(os.path.join(settings.MEDIA_ROOT, media.screenshot))
    if not contained_in(screenshot_path, settings.MEDIA_ROOT):
        raise NotFoundError("Screenshot file not found on disk", error_code="SCREENSHOT_FILE_NOT_FOUND")

    if not os.path.exists(screenshot_path):
        raise NotFoundError("Screenshot file not found on disk", error_code="SCREENSHOT_FILE_NOT_FOUND")

    response = FileResponse(
        open(screenshot_path, "rb"), content_type="image/jpeg", filename=f"{media.title}_screenshot.jpg"
    )

    logger.debug(f"Serving screenshot: {media.title}")

    return response
