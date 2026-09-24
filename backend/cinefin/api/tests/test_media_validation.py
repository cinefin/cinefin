from cinefin.api.ninja_views.media import utils
from cinefin.api.ninja_views.media.utils import validate_video_file


def _make(tmp_path, name, size=1024):
    p = tmp_path / name
    p.write_bytes(b"\x00" * size)
    return str(p)


def test_mkv_with_undetectable_mime_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "get_file_mime_type", lambda _p: None)
    ok, msg = validate_video_file(_make(tmp_path, "clip.mkv"))
    assert ok, msg


def test_bare_codec_octet_stream_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "get_file_mime_type", lambda _p: "application/octet-stream")
    ok, msg = validate_video_file(_make(tmp_path, "clip.mkv"))
    assert ok, msg


def test_detected_non_media_mime_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "get_file_mime_type", lambda _p: "text/plain")
    ok, msg = validate_video_file(_make(tmp_path, "clip.mkv"))
    assert not ok
    assert "Invalid file type" in msg


def test_disallowed_extension_is_rejected(tmp_path):
    ok, msg = validate_video_file(_make(tmp_path, "notes.txt"))
    assert not ok
    assert "extension" in msg.lower()


def test_video_mime_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "get_file_mime_type", lambda _p: "video/x-matroska")
    ok, msg = validate_video_file(_make(tmp_path, "clip.mkv"))
    assert ok, msg


def test_too_large_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(utils, "get_file_mime_type", lambda _p: None)
    ok, msg = validate_video_file(_make(tmp_path, "clip.mkv"), max_size_mb=0)
    assert not ok
    assert "too large" in msg.lower()


def test_duration_falls_back_to_ffprobe(monkeypatch):
    class _NoTracks:
        tracks: list = []

    class _Result:
        stdout = "142.5\n"

    monkeypatch.setattr(utils.MediaInfo, "parse", lambda _p: _NoTracks())
    monkeypatch.setattr(utils.subprocess, "run", lambda *a, **k: _Result())
    assert utils.get_media_duration("/whatever/clip.mkv") == 142.5


def test_duration_none_when_both_probes_fail(monkeypatch):
    class _NoTracks:
        tracks: list = []

    class _Result:
        stdout = ""

    monkeypatch.setattr(utils.MediaInfo, "parse", lambda _p: _NoTracks())
    monkeypatch.setattr(utils.subprocess, "run", lambda *a, **k: _Result())
    assert utils.get_media_duration("/whatever/clip.mkv") is None
