import logging

from django.conf import settings
from django.http import HttpRequest
from ninja import File, Form, Router, Status, UploadedFile

from cinefin.api.schemas.base import ErrorResponseSchema

from .schemas import MediaCreateDataSchema, MediaCreateResponseSchema, TagSchema

logger = logging.getLogger(__name__)

uploads_api = Router()


@uploads_api.post(
    "/upload", response={201: MediaCreateResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def upload_media(
    request: HttpRequest,
    title: str = Form(..., description="Media title"),
    file: UploadedFile = File(..., description="Video file to upload"),
    tag_names: str | None = Form(None, description="Comma-separated tag names"),
):
    tag_list = []
    if tag_names:
        tag_list = [tag.strip() for tag in tag_names.split(",") if tag.strip()]

    max_size_mb = getattr(settings, "MAX_MEDIA_UPLOAD_SIZE_MB", 500)

    from cinefin.api.services.media_service import MediaService

    media, processing_info = MediaService.process_file_upload(
        file=file, title=title, tag_names=tag_list, max_size_mb=max_size_mb
    )

    file_url = request.build_absolute_uri(f"/api/v2/media/{media.id}/download")
    screenshot_url = None
    if processing_info["screenshot_generated"]:
        screenshot_url = request.build_absolute_uri(f"/api/v2/media/{media.id}/screenshot")

    tag_schemas = [TagSchema(id=tag.id, name=tag.name) for tag in processing_info["tags"]]

    response_data = MediaCreateDataSchema(
        id=media.id,
        title=media.title,
        duration=processing_info["duration"],
        file_path=processing_info["file_path"],
        file_url=file_url,
        screenshot_url=screenshot_url,
        screenshot_generated=processing_info["screenshot_generated"],
        tags=tag_schemas,
        created_at=media.upload_date.isoformat() if media.upload_date else None,
    )

    return Status(
        201,
        MediaCreateResponseSchema(
            success=True, message=f"Media '{media.title}' uploaded successfully", data=response_data
        ),
    )
