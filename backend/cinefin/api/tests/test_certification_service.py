import shutil
import subprocess

import pytest
from PIL import Image

from cinefin.api.services.certification_service import CertificationService

from .factories import MovieFactory


def _background(tmp_path, size=(1744, 981)):
    path = tmp_path / "bg.jpg"
    Image.new("RGB", size, (180, 20, 20)).save(path)
    return str(path)


def test_frame_has_title_bar_and_text(tmp_path):
    frame = CertificationService._compose_card_frame(
        background_path=_background(tmp_path),
        title="CLOCKERS",
    )

    assert frame.size == (1744, 981)
    assert frame.getpixel((1600, 485)) == (0, 0, 0)
    text_region = frame.crop((125, 455, 900, 515))
    assert any(pixel != (0, 0, 0) for pixel in text_region.getdata())


def test_no_title_leaves_the_background_untouched(tmp_path):
    # Title-less systems (MPAA-style) get the plain background — no title bar burnt in.
    frame = CertificationService._compose_card_frame(background_path=_background(tmp_path))
    assert frame.getpixel((1600, 485)) == (180, 20, 20)


class TestVideoEncode:
    def test_ffmpeg_command_matches_output_contract(self, tmp_path, monkeypatch):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            with open(cmd[-1], "wb") as f:
                f.write(b"mp4")
            return subprocess.CompletedProcess(cmd, 0)

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/ffmpeg")

        frame_png = tmp_path / "frame.png"
        Image.new("RGB", (1920, 1080), (0, 0, 0)).save(frame_png)
        out = tmp_path / "card.mp4"

        CertificationService._encode_still_to_video(str(frame_png), str(out), duration=5)

        assert len(calls) == 1
        cmd = calls[0]
        assert cmd[0] == "/usr/bin/ffmpeg"
        assert cmd[cmd.index("-loop") + 1] == "1"
        assert cmd[cmd.index("-i") + 1] == str(frame_png)
        assert cmd[cmd.index("-t") + 1] == "5"
        assert cmd[cmd.index("-r") + 1] == "24"
        assert cmd[cmd.index("-c:v") + 1] == "libx264"
        assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
        assert cmd[cmd.index("-movflags") + 1] == "+faststart"
        assert out.exists()


@pytest.mark.django_db
class TestStaticCards:
    """User-supplied MEDIA_ROOT/ratings/<system>/<cert>.mp4 wins over generation."""

    def _static(self, tmp_path, cert="PG", system="BBFC"):
        path = tmp_path / "ratings" / system / f"{cert}.mp4"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not really video")
        return str(path)

    def test_static_video_short_circuits_generation(self, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        self._static(tmp_path)
        movie = MovieFactory(certification="PG")

        cert = CertificationService.get_or_create_certification(movie)

        assert cert is not None
        assert cert.file_path == "ratings/BBFC/PG.mp4"
        assert cert.ratings_system == "BBFC"

    def test_no_certificate_returns_none(self, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        movie = MovieFactory(certification="")

        assert CertificationService.get_or_create_certification(movie) is None

    def test_mpaa_is_static_only_and_skips_generation(self, tmp_path, settings):
        # MPAA cards don't name the film, so there's nothing to compose: without a
        # static card there's no card, and generation must not run.
        from cinefin.api.models import Settings

        settings.MEDIA_ROOT = str(tmp_path)
        Settings.set("cinema.ratings_system", "MPAA")
        movie = MovieFactory(certification="PG-13")

        assert CertificationService.get_or_create_certification(movie) is None
