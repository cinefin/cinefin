import shutil
import subprocess

import pytest
from PIL import Image

from cinefin.api.models import Settings
from cinefin.api.services.certification_service import CertificationService

from .factories import MovieFactory


def _background(tmp_path):
    path = tmp_path / "bg.jpg"
    Image.new("RGB", (1744, 981), (180, 20, 20)).save(path)
    return str(path)


def test_ffmpeg_command_matches_output_contract(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        with open(cmd[-1], "wb") as f:
            f.write(b"mp4")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")
    frame_png = tmp_path / "frame.png"
    Image.new("RGB", (1920, 1080)).save(frame_png)

    CertificationService._encode_still_to_video(str(frame_png), str(tmp_path / "card.mp4"), duration=5)
    (cmd,) = calls
    args = dict(zip(cmd, cmd[1:], strict=False))
    assert cmd[0] == "/usr/bin/ffmpeg"
    assert (args["-loop"], args["-i"], args["-t"], args["-r"]) == ("1", str(frame_png), "5", "24")
    assert (args["-c:v"], args["-pix_fmt"], args["-movflags"]) == ("libx264", "yuv420p", "+faststart")


@pytest.mark.django_db
def test_static_cards(tmp_path, settings):
    """A user-supplied MEDIA_ROOT/ratings/<system>/<cert>.mp4 wins over generation."""
    settings.MEDIA_ROOT = str(tmp_path)
    static = tmp_path / "ratings" / "BBFC" / "PG.mp4"
    static.parent.mkdir(parents=True)
    static.write_bytes(b"not really video")

    cert = CertificationService.get_or_create_certification(MovieFactory(certification="PG"))
    assert (cert.file_path, cert.ratings_system) == ("ratings/BBFC/PG.mp4", "BBFC")
    assert CertificationService.get_or_create_certification(MovieFactory(certification="")) is None

    # MPAA cards don't name the film: without a static card there's no card, and no generation.
    Settings.set("cinema.ratings_system", "MPAA")
    assert CertificationService.get_or_create_certification(MovieFactory(certification="PG-13")) is None
