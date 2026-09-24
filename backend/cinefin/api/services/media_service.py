"""Media upload, processing, and management."""

import logging
import os
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

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
from cinefin.api.utils.media_paths import to_usermedia_relative, usermedia_abs_path
from cinefin.api.utils.paths import contained_in

try:
    import yt_dlp

    YT_DLP_AVAILABLE = True
except ImportError:
    yt_dlp = None
    YT_DLP_AVAILABLE = False

logger = logging.getLogger(__name__)


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
        os.makedirs(media_directory, exist_ok=True)

        file_ext = Path(file.name).suffix.lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            raise ValidationError(
                f"Invalid file extension. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
                error_code="INVALID_FILE_EXTENSION",
            )

        max_size_bytes = max_size_mb * 1024 * 1024
        if file.size > max_size_bytes:
            raise ValidationError(f"File too large. Maximum size: {max_size_mb}MB", error_code="FILE_TOO_LARGE")

        safe_filename = sanitize_filename(file.name)
        final_filename = cls._generate_unique_filename(media_directory, safe_filename)
        final_path = os.path.join(media_directory, final_filename)

        # Containment backstop behind sanitize_filename(): the destination
        # must resolve inside the media directory whatever the name contained.
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

            # Store the path relative to MEDIA_ROOT so the library survives a
            # moved/restored usermedia volume.
            media = Bumper.objects.create(
                title=title.strip(),
                file_path=to_usermedia_relative(final_path),
                duration=int(duration or 0),
                upload_date=timezone.now(),
            )

            tag_objects = cls._process_tags(media, tag_names or [])

            # video only — audio clips have no frame
            if is_audio_file(final_path):
                screenshot_info = {"generated": False}
            else:
                screenshot_info = cls._generate_screenshot_for_media(media, duration)

            processing_info = {
                "filename": final_filename,
                "file_path": final_path,
                "duration": duration,
                "tags": tag_objects,
                "screenshot_generated": screenshot_info["generated"],
                "screenshot_path": screenshot_info.get("path"),
            }

            logger.info(f"Processed media upload: {media.title} ({final_filename})")
            return media, processing_info

        except Exception as e:
            if temp_file and os.path.exists(temp_file.name):
                try:
                    os.unlink(temp_file.name)
                except Exception:
                    pass

            if os.path.exists(final_path):
                try:
                    os.unlink(final_path)
                except Exception:
                    pass

            if isinstance(e, ValidationError):
                raise
            else:
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

        duration = get_media_duration(file_path)

        # Relative to MEDIA_ROOT when under it; an external add-by-path stays absolute.
        media = Bumper.objects.create(
            title=title.strip(),
            file_path=to_usermedia_relative(file_path),
            duration=int(duration or 0),
            upload_date=timezone.now(),
        )

        tag_objects = cls._process_tags(media, tag_names or [])

        screenshot_info = cls._generate_screenshot_for_media(media, duration)

        processing_info = {
            "file_path": file_path,
            "duration": duration,
            "tags": tag_objects,
            "screenshot_generated": screenshot_info["generated"],
            "screenshot_path": screenshot_info.get("path"),
        }

        logger.info(f"Created media from existing file: {media.title}")
        return media, processing_info

    @staticmethod
    def _generate_unique_filename(directory: str, filename: str) -> str:
        base_name = Path(filename).stem
        extension = Path(filename).suffix
        counter = 1
        final_filename = filename

        while os.path.exists(os.path.join(directory, final_filename)):
            final_filename = f"{base_name}_{counter}{extension}"
            counter += 1

        return final_filename

    @staticmethod
    def _process_tags(media: Bumper, tag_names: list[str]) -> list[Tag]:
        tag_objects = []
        for tag_name in tag_names:
            if tag_name.strip():
                tag, created = Tag.objects.get_or_create(name=tag_name.strip())
                media.tags.add(tag)
                tag_objects.append(tag)
        return tag_objects

    @staticmethod
    def _generate_screenshot_for_media(media: Bumper, duration: float | None) -> dict[str, Any]:
        screenshot_info = {"generated": False}

        if duration and duration > 0 and media.file_path:
            screenshots_dir = os.path.join(settings.MEDIA_ROOT, "screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)

            file_stem = Path(media.file_path).stem
            screenshot_filename = f"{file_stem}_screenshot.jpg"
            screenshot_path = os.path.join(screenshots_dir, screenshot_filename)

            # relative to MEDIA_ROOT for DB storage
            screenshot_relative = os.path.join("screenshots", screenshot_filename)

            try:
                logger.info(f"Attempting to generate screenshot for media: {media.title} at {media.file_path}")
                success = generate_screenshot(usermedia_abs_path(media.file_path), screenshot_path, duration=duration)
                if success:
                    logger.info(f"Screenshot generated successfully for {media.title}: {screenshot_path}")
                    media.screenshot = screenshot_relative
                    media.save(update_fields=["screenshot"])
                    screenshot_info.update({"generated": True, "path": screenshot_relative})
                else:
                    logger.warning(f"Screenshot generation failed for {media.title}")
            except Exception as e:
                logger.warning(f"Failed to generate screenshot for {media.title}: {e}")
        else:
            logger.info(
                f"Skipping screenshot generation for {media.title}: duration={duration}, file_path={media.file_path}"
            )

        return screenshot_info

    @classmethod
    def regenerate_thumbnails(cls, media_id: int | None = None) -> dict[str, int]:
        """Re-extract screenshots (one item, or all video items). Synchronous;
        skipped covers audio clips and missing files."""
        queryset = Bumper.objects.filter(pk=media_id) if media_id else Bumper.objects.all()
        counts = {"regenerated": 0, "skipped": 0, "failed": 0}

        for media in queryset.order_by("title"):
            abs_path = usermedia_abs_path(media.file_path)
            if not abs_path or not os.path.exists(abs_path) or is_audio_file(abs_path):
                counts["skipped"] += 1
                continue
            info = cls._generate_screenshot_for_media(media, media.duration or 1)
            counts["regenerated" if info["generated"] else "failed"] += 1

        return counts

    @classmethod
    def start_youtube_download(cls, url: str, title: str | None = None, tag_names: list[str] | None = None) -> str:
        if not YT_DLP_AVAILABLE:
            raise ValidationError(
                "YouTube download not available. yt-dlp package not installed.", error_code="YT_DLP_NOT_AVAILABLE"
            )

        if not validate_youtube_url(url):
            raise ValidationError("Invalid YouTube URL provided", error_code="INVALID_YOUTUBE_URL")

        task_id = str(uuid.uuid4())

        thread = threading.Thread(
            target=cls._youtube_download_worker, args=(task_id, url, title, tag_names or []), daemon=True
        )
        thread.start()

        cache.set(
            f"youtube_task_{task_id}",
            {"task_id": task_id, "status": "starting", "progress": 0.0, "filename": None, "error": None},
            timeout=3600,
        )

        return task_id

    @classmethod
    def get_youtube_download_progress(cls, task_id: str) -> dict[str, Any] | None:
        return cache.get(f"youtube_task_{task_id}")

    @classmethod
    def _youtube_download_worker(cls, task_id: str, url: str, title: str | None, tag_names: list[str]):
        try:
            cache.set(
                f"youtube_task_{task_id}",
                {"task_id": task_id, "status": "downloading", "progress": 0.0, "filename": None, "error": None},
                timeout=3600,
            )

            download_directory = cls.get_media_directory()
            os.makedirs(download_directory, exist_ok=True)

            def progress_hook(d):
                if d["status"] == "downloading":
                    try:
                        progress = None
                        if "total_bytes" in d and d["total_bytes"]:
                            progress = (d["downloaded_bytes"] / d["total_bytes"]) * 100
                        elif "_percent_str" in d:
                            percent_str = d["_percent_str"].replace("%", "").strip()
                            progress = float(percent_str)

                        if progress is not None:
                            cache.set(
                                f"youtube_task_{task_id}",
                                {
                                    "task_id": task_id,
                                    "status": "downloading",
                                    "progress": min(progress, 99.0),
                                    "filename": None,
                                    "error": None,
                                },
                                timeout=3600,
                            )
                    except Exception:
                        pass

            ydl_opts = {
                # Prefer merged bestvideo+bestaudio: YouTube mostly serves separate
                # streams now, so a pre-muxed "best[ext=mp4]" often fails with
                # "Requested format is not available". Cap at 1080p, fall back to any
                # single file. Merging needs ffmpeg (the file finder below accepts
                # whatever container results).
                "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
                "outtmpl": os.path.join(download_directory, "%(title)s.%(ext)s"),
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
                        test_path = base_path + ext
                        if os.path.exists(test_path):
                            downloaded_file = test_path
                            break
                    else:
                        raise Exception(f"Downloaded file not found: {downloaded_file}")

                media, processing_info = cls.create_media_from_existing_file(downloaded_file, video_title, tag_names)

                cache.set(
                    f"youtube_task_{task_id}",
                    {
                        "task_id": task_id,
                        "status": "completed",
                        "progress": 100.0,
                        "filename": os.path.basename(downloaded_file),
                        "media_id": media.id,
                        "error": None,
                    },
                    timeout=3600,
                )

                logger.info(f"YouTube download completed: {video_title}")

        except Exception as e:
            error_msg = str(e)
            logger.exception(f"YouTube download failed for task {task_id}: {error_msg}")

            cache.set(
                f"youtube_task_{task_id}",
                {"task_id": task_id, "status": "failed", "progress": 0.0, "filename": None, "error": error_msg},
                timeout=3600,
            )
