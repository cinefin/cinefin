"""Trailer downloads: the yt-dlp options that decide which file arrives."""

from unittest.mock import MagicMock, patch

import pytest

from cinefin.api.models import Settings
from cinefin.api.services.trailer_service import TrailerService
from cinefin.api.utils import ytdlp

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("quality", "fmt"),
    [
        ("1080", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/bestvideo+bestaudio/best"),
        ("best", "bestvideo+bestaudio/best"),
    ],
)
def test_downloads_prefer_h264_within_the_quality_cap(quality, fmt):
    Settings.set("trailers", {"download_quality": quality})
    with patch("cinefin.api.services.trailer_service.yt_dlp.YoutubeDL") as ydl:
        ydl.return_value.__enter__.return_value = MagicMock()
        TrailerService()._ytdlp_fetch("abc123", "/tmp/trailer.mp4")
    opts = ydl.call_args.args[0]
    assert opts["format"] == fmt
    # Resolution first, then H.264 over VP9/AV1: a 1080p cap gets H.264.
    assert opts["format_sort"] == ytdlp.FORMAT_SORT == ["res", "vcodec:h264"]
    assert opts["merge_output_format"] == "mp4"
