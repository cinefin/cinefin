from types import SimpleNamespace

import pytest

from cinefin.api.ninja_views.media import utils
from cinefin.api.ninja_views.media.utils import validate_video_file


@pytest.mark.parametrize(
    ("name", "mime", "max_mb", "error"),
    [
        ("clip.mkv", None, None, None),  # undetectable MIME: the extension decides
        ("clip.mkv", "application/octet-stream", None, None),  # bare codec
        ("clip.mkv", "video/x-matroska", None, None),
        ("clip.mkv", "text/plain", None, "invalid file type"),
        ("notes.txt", None, None, "extension"),
        ("clip.mkv", None, 0, "too large"),
    ],
)
def test_validate_video_file(tmp_path, monkeypatch, name, mime, max_mb, error):
    monkeypatch.setattr(utils, "get_file_mime_type", lambda _p: mime)
    path = tmp_path / name
    path.write_bytes(b"\x00" * 1024)
    kwargs = {} if max_mb is None else {"max_size_mb": max_mb}
    ok, msg = validate_video_file(str(path), **kwargs)
    assert ok is (error is None), msg
    if error:
        assert error in msg.lower()


@pytest.mark.parametrize(("stdout", "duration"), [("142.5\n", 142.5), ("", None)])
def test_duration_falls_back_to_ffprobe(monkeypatch, stdout, duration):
    monkeypatch.setattr(utils.MediaInfo, "parse", lambda _p: SimpleNamespace(tracks=[]))
    monkeypatch.setattr(utils.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=stdout))
    assert utils.get_media_duration("/whatever/clip.mkv") == duration
