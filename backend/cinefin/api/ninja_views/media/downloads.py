import logging

from django.http import HttpRequest
from ninja import Router, Status

from cinefin.api.exceptions import NotFoundError
from cinefin.api.schemas.base import ErrorResponseSchema

from .schemas import (
    YouTubeDownloadSchema,
    YouTubeProgressDataSchema,
    YouTubeProgressSchema,
    YouTubeTaskDataSchema,
    YouTubeTaskResponseSchema,
)

logger = logging.getLogger(__name__)

downloads_api = Router()


@downloads_api.post(
    "/youtube-download", response={202: YouTubeTaskResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def youtube_download(request: HttpRequest, data: YouTubeDownloadSchema):
    from cinefin.api.services.media_service import MediaService

    task_id = MediaService.start_youtube_download(url=data.url, title=data.title, tag_names=data.tag_names or [])

    return Status(
        202,
        YouTubeTaskResponseSchema(
            success=True, message="YouTube download task started", data=YouTubeTaskDataSchema(task_id=task_id)
        ),
    )


@downloads_api.get(
    "/youtube-progress/{task_id}",
    response={200: YouTubeProgressSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def youtube_progress(request: HttpRequest, task_id: str):
    from cinefin.api.services.media_service import MediaService

    task_data = MediaService.get_youtube_download_progress(task_id)

    if not task_data:
        raise NotFoundError("Download task not found or expired", error_code="TASK_NOT_FOUND")

    progress_data = YouTubeProgressDataSchema(
        task_id=task_data["task_id"],
        status=task_data["status"],
        progress=task_data.get("progress"),
        filename=task_data.get("filename"),
        error=task_data.get("error"),
        media_id=task_data.get("media_id"),
    )

    return Status(
        200,
        YouTubeProgressSchema(success=True, message=f"Download task status: {task_data['status']}", data=progress_data),
    )
