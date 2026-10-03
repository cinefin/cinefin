import os

import pytest

from cinefin.api.utils.media_paths import to_usermedia_relative, usermedia_abs_path


@pytest.fixture
def root(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    return str(tmp_path)


def test_usermedia_abs_path(root):
    assert usermedia_abs_path("media/clip.mp4") == os.path.join(root, "media/clip.mp4")
    assert usermedia_abs_path("/opt/movies/film.mkv") == "/opt/movies/film.mkv"
    assert usermedia_abs_path("") == ""


def test_to_usermedia_relative_round_trips(root):
    abs_in = os.path.join(root, "media", "clip.mp4")
    assert to_usermedia_relative(abs_in) == os.path.join("media", "clip.mp4")
    assert usermedia_abs_path(to_usermedia_relative(abs_in)) == abs_in
    assert to_usermedia_relative("/opt/movies/film.mkv") == "/opt/movies/film.mkv"
    assert to_usermedia_relative("media/x.mp4") == "media/x.mp4"
