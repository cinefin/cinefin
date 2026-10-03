"""Media upload, processing, and management."""

import logging
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import yt_dlp
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from cinefin.api.exceptions import InternalServerError, ValidationError
from cinefin.api.models import Bumper, Tag
from cinefin.api.ninja_views.media.utils import (
    ALLOWED_EXTENSIONS,
    generate_screenshot,
    get_media_duration,
    is_audio_file,
    sanitize_filename,
    validate_video_file,
    validate_youtube_url,
)
from cinefin.api.utils import ytdlp
from cinefin.api.utils.media_paths import to_usermedia_relative, usermedia_abs_path
from cinefin.api.utils.paths import contained_in

logger = logging.getLogger(__name__)


def _set_task(task_id: str, status: str, progress: float = 0.0, **extra) -> None:
    state = {"task_id": task_id, "status": status, "progress": progress, "filename": None, "error": None, **extra}
    cache.set(f"youtube_task_{task_id}", state, timeout=3600)


class MediaService:
    @staticmethod
    def get_media_directory() -> str:
        media_dir = os.path.join(settings.MEDIA_ROOT, "media")
        os.makedirs(media_dir, exist_ok=True)
        return media_dir

    @classmethod
    def process_file_upload(
        cls, file, title: str, tag_names: list[str] | None = None, max_size_mb: int = 500
    ) -> tuple[Bumper, dict[str, Any]]:
        media_directory = cls.get_media_directory()

        file_ext = Path(file.name).suffix.lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Invalid file extension. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
                error_code="INVALID_FILE_EXTENSION",
            )
        if file.size > max_size_mb * 1024 * 1024:
            raise ValidationError(f"File too large. Maximum size: {max_size_mb}MB", error_code="FILE_TOO_LARGE")

        final_filename = cls._generate_unique_filename(media_directory, sanitize_filename(file.name))
        final_path = os.path.join(media_directory, final_filename)
        # Containment backstop behind sanitize_filename(): the destination must resolve inside the media directory.
        if not contained_in(final_path, media_directory):
            raise ValidationError("Invalid file name", error_code="INVALID_FILE_NAME")

        temp_file = None
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=file_ext)
            for chunk in file.chunks():
                temp_file.write(chunk)
            temp_file.close()

            is_valid, error_msg = validate_video_file(temp_file.name, max_size_mb)
            if not is_valid:
                raise ValidationError(error_msg, error_code="INVALID_VIDEO_FILE")

            duration = get_media_duration(temp_file.name)
            if duration is None:
                logger.warning(f"Could not determine duration for {final_filename}")

            shutil.move(temp_file.name, final_path)
            temp_file = None

            media, info = cls._create(final_path, title, tag_names, duration, screenshot=not is_audio_file(final_path))
            logger.info(f"Processed media upload: {media.title} ({final_filename})")
            return media, info

        except Exception as e:
            for leftover in (temp_file.name if temp_file else None, final_path):
                if leftover and os.path.exists(leftover):
                    try:
                        os.unlink(leftover)
                    except Exception:
                        pass
            if isinstance(e, ValidationError):
                raise
            logger.exception(f"Error processing upload: {e}")
            raise InternalServerError(
                f"Failed to process upload: {str(e)}", error_code="UPLOAD_PROCESSING_FAILED"
            ) from e

    @classmethod
    def create_media_from_existing_file(
        cls, file_path: str, title: str, tag_names: list[str] | None = None
    ) -> tuple[Bumper, dict[str, Any]]:
        if not os.path.exists(file_path):
            raise ValidationError(f"File not found: {file_path}", error_code="FILE_NOT_FOUND")
        is_valid, error_msg = validate_video_file(file_path)
        if not is_valid:
            raise ValidationError(error_msg, error_code="INVALID_VIDEO_FILE")
        media, info = cls._create(file_path, title, tag_names, get_media_duration(file_path))
        logger.info(f"Created media from existing file: {media.title}")
        return media, info

    @classmethod
    def _create(cls, path: str, title: str, tag_names, duration, screenshot: bool = True):
        # Relative to MEDIA_ROOT when under it (survives a moved usermedia volume); an external path stays absolute.
        media = Bumper.objects.create(
            title=title.strip(),
            file_path=to_usermedia_relative(path),
            duration=int(duration or 0),
            upload_date=timezone.now(),
        )
        tags = []
        for name in filter(None, (n.strip() for n in tag_names or [])):
            tag, _ = Tag.objects.get_or_create(name=name)
            media.tags.add(tag)
            tags.append(tag)
        generated = cls._generate_screenshot_for_media(media, duration) if screenshot else False
        return media, {"file_path": path, "duration": duration, "tags": tags, "screenshot_generated": generated}

    @staticmethod
    def _generate_unique_filename(directory: str, filename: str) -> str:
        base_name, extension = Path(filename).stem, Path(filename).suffix
        counter = 1
        final_filename = filename
        while os.path.exists(os.path.join(directory, final_filename)):
            final_filename = f"{base_name}_{counter}{extension}"
            counter += 1
        return final_filename

    @staticmethod
    def _generate_screenshot_for_media(media: Bumper, duration: float | None) -> bool:
        if not (duration and duration > 0 and media.file_path):
            logger.info(
                f"Skipping screenshot generation for {media.title}: duration={duration}, file_path={media.file_path}"
            )
            return False

        screenshots_dir = os.path.join(settings.MEDIA_ROOT, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)
        screenshot_filename = f"{Path(media.file_path).stem}_screenshot.jpg"
        screenshot_path = os.path.join(screenshots_dir, screenshot_filename)
        try:
            if generate_screenshot(usermedia_abs_path(media.file_path), screenshot_path, duration=duration):
                media.screenshot = os.path.join("screenshots", screenshot_filename)  # relative to MEDIA_ROOT
                media.save(update_fields=["screenshot"])
                return True
            logger.warning(f"Screenshot generation failed for {media.title}")
        except Exception as e:
            logger.warning(f"Failed to generate screenshot for {media.title}: {e}")
        return False

    @classmethod
    def regenerate_thumbnails(cls, media_id: int | None = None) -> dict[str, int]:
        """Re-extract screenshots (one item, or all video items); skipped covers audio clips and missing files."""
        queryset = Bumper.objects.filter(pk=media_id) if media_id else Bumper.objects.all()
        counts = {"regenerated": 0, "skipped": 0, "failed": 0}
        for media in queryset.order_by("title"):
            abs_path = usermedia_abs_path(media.file_path)
            if not abs_path or not os.path.exists(abs_path) or is_audio_file(abs_path):
                counts["skipped"] += 1
                continue
            generated = cls._generate_screenshot_for_media(media, media.duration or 1)
            counts["regenerated" if generated else "failed"] += 1
        return counts

    @classmethod
    def start_youtube_download(cls, url: str, title: str | None = None, tag_names: list[str] | None = None) -> str:
        if not validate_youtube_url(url):
            raise ValidationError("Invalid YouTube URL provided", error_code="INVALID_YOUTUBE_URL")
        task_id = str(uuid.uuid4())
        threading.Thread(
            target=cls._youtube_download_worker, args=(task_id, url, title, tag_names or []), daemon=True
        ).start()
        _set_task(task_id, "starting")
        return task_id

    @classmethod
    def get_youtube_download_progress(cls, task_id: str) -> dict[str, Any] | None:
        return cache.get(f"youtube_task_{task_id}")

    @classmethod
    def _youtube_download_worker(cls, task_id: str, url: str, title: str | None, tag_names: list[str]):
        try:
            _set_task(task_id, "downloading")

            def progress_hook(d):
                if d["status"] != "downloading":
                    return
                try:
                    progress = None
                    if d.get("total_bytes"):
                        progress = (d["downloaded_bytes"] / d["total_bytes"]) * 100
                    elif "_percent_str" in d:
                        progress = float(d["_percent_str"].replace("%", "").strip())
                    if progress is not None:
                        _set_task(task_id, "downloading", min(progress, 99.0))
                except Exception:
                    pass

            ydl_opts = {
                # Prefer merged bestvideo+bestaudio: YouTube mostly serves separate streams, so a pre-muxed
                # "best[ext=mp4]" often fails. Cap at 1080p, fall back to any single file. Merging needs ffmpeg
                # (the file finder below accepts whatever container results). H.264 where there is one.
                "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo+bestaudio/best",
                "format_sort": ytdlp.FORMAT_SORT,
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(cls.get_media_directory(), "%(title)s.%(ext)s"),
                "progress_hooks": [progress_hook],
                "restrictfilenames": True,
                "ignoreerrors": False,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                video_title = title or info.get("title", "Downloaded Video")
                ydl.download([url])

                downloaded_file = ydl.prepare_filename(info)
                if not os.path.exists(downloaded_file):
                    base_path = os.path.splitext(downloaded_file)[0]
                    for ext in [".mp4", ".mkv", ".webm", ".avi"]:
                        if os.path.exists(base_path + ext):
                            downloaded_file = base_path + ext
                            break
                    else:
                        raise Exception(f"Downloaded file not found: {downloaded_file}")

                media, _ = cls.create_media_from_existing_file(downloaded_file, video_title, tag_names)
                _set_task(task_id, "completed", 100.0, filename=os.path.basename(downloaded_file), media_id=media.id)
                logger.info(f"YouTube download completed: {video_title}")

        except Exception as e:
            logger.exception(f"YouTube download failed for task {task_id}: {e}")
            _set_task(task_id, "failed", error=str(e))
