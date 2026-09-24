import logging
import mimetypes
import os
import re
import subprocess
from pathlib import Path

from pymediainfo import MediaInfo

logger = logging.getLogger(__name__)

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v"}
ALLOWED_AUDIO_EXTENSIONS = {
    ".wav",
    ".flac",
    ".mp3",
    ".m4a",
    ".aac",
    ".ac3",
    ".eac3",
    ".dts",
    ".thd",
    ".ogg",
    ".opus",
    ".wma",
}
ALLOWED_EXTENSIONS = ALLOWED_VIDEO_EXTENSIONS | ALLOWED_AUDIO_EXTENSIONS
ALLOWED_MIME_TYPES = {
    "video/mp4",
    "video/x-msvideo",
    "video/quicktime",
    "video/x-ms-wmv",
    "video/x-flv",
    "video/webm",
    "video/x-matroska",
}


def is_audio_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in ALLOWED_AUDIO_EXTENSIONS


def sanitize_filename(filename: str) -> str:
    filename = os.path.basename(filename)
    filename = re.sub(r'[<>:"/\\|?*]', "_", filename)
    return filename


def generate_screenshot(
    video_path: str,
    output_path: str,
    timestamp: str | None = None,
    duration: float | None = None,
) -> bool:
    if timestamp is None:
        # Seek to roughly the midpoint, clamped to [1s, 10s] so a two-second
        # sting still lands on a real frame instead of past the end.
        seek_secs = min(10, max(1, int((duration or 2) / 2)))
        timestamp = f"00:00:{seek_secs:02d}"
    try:
        if not os.path.exists(video_path):
            logger.error(f"Video file not found: {video_path}")
            return False

        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        logger.info(f"Generating screenshot from {video_path} at {timestamp}")

        cmd = [
            "ffmpeg",
            "-i",
            video_path,
            "-ss",
            timestamp,
            "-vframes",
            "1",
            "-q:v",
            "2",
            "-y",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        if result.returncode == 0 and os.path.exists(output_path):
            file_size = os.path.getsize(output_path)
            logger.info(f"Generated screenshot: {output_path} ({file_size} bytes)")
            return True
        else:
            logger.error(f"ffmpeg failed (return code {result.returncode}): {result.stderr}")
            if result.stdout:
                logger.debug(f"ffmpeg stdout: {result.stdout}")
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg timeout generating screenshot for {video_path}")
        return False
    except Exception as e:
        logger.exception(f"Error generating screenshot for {video_path}: {e}")
        return False


def get_file_mime_type(file_path: str) -> str | None:
    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type


def get_media_duration(file_path: str) -> float | None:
    try:
        media_info = MediaInfo.parse(file_path)

        # Prefer video, then general, then ANY track with a duration — some
        # containers carry it only on the audio/general track.
        for track_type in ("Video", "General"):
            for track in media_info.tracks:
                if track.track_type == track_type and track.duration:
                    return track.duration / 1000.0
        for track in media_info.tracks:
            if track.duration:
                return track.duration / 1000.0
    except Exception as e:
        logger.error(f"Error getting media duration for {file_path}: {e}")

    # libmediainfo occasionally can't read a file that ffmpeg handles fine.
    return _ffprobe_duration(file_path)


def _ffprobe_duration(file_path: str) -> float | None:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", file_path],
            capture_output=True,
            text=True,
            timeout=30,
        )
        value = (result.stdout or "").strip()
        return float(value) if value else None
    except Exception as e:  # noqa: BLE001 — probe is best-effort
        logger.error(f"ffprobe duration failed for {file_path}: {e}")
        return None


def validate_video_file(file_path: str, max_size_mb: int = 5000) -> tuple[bool, str]:
    if not os.path.exists(file_path):
        return False, "File does not exist"

    file_ext = Path(file_path).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        return False, f"Invalid file extension. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"

    # Lenient: the extension above is the real gate. guess_type is OS-dependent,
    # so an undetectable (empty) type or octet-stream must not reject a valid
    # extension. Only reject a detectable type that's clearly not media.
    mime_type = get_file_mime_type(file_path) or ""
    if mime_type and not (
        mime_type in ALLOWED_MIME_TYPES
        or mime_type.startswith(("video/", "audio/"))
        or mime_type == "application/octet-stream"
    ):
        return False, f"Invalid file type. Got: {mime_type}"

    file_size = os.path.getsize(file_path)
    max_size_bytes = max_size_mb * 1024 * 1024
    if file_size > max_size_bytes:
        return False, f"File too large. Maximum size: {max_size_mb}MB"

    return True, ""


def validate_youtube_url(url: str) -> bool:
    youtube_patterns = [
        r"youtube\.com/watch\?v=",
        r"youtu\.be/",
        r"youtube\.com/embed/",
        r"youtube\.com/v/",
    ]

    return any(re.search(pattern, url, re.IGNORECASE) for pattern in youtube_patterns)
