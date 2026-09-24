import os

from cinefin.api.utils.media_paths import to_usermedia_relative, usermedia_abs_path


class TestUsermediaAbsPath:
    def test_relative_joins_media_root(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        assert usermedia_abs_path("media/clip.mp4") == os.path.join(str(tmp_path), "media/clip.mp4")

    def test_absolute_passes_through(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        assert usermedia_abs_path("/opt/movies/film.mkv") == "/opt/movies/film.mkv"

    def test_empty_passthrough(self):
        assert usermedia_abs_path("") == ""


class TestToUsermediaRelative:
    def test_under_media_root_becomes_relative(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        assert to_usermedia_relative(os.path.join(str(tmp_path), "media", "x.mp4")) == os.path.join("media", "x.mp4")

    def test_external_absolute_kept(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        assert to_usermedia_relative("/opt/movies/film.mkv") == "/opt/movies/film.mkv"

    def test_already_relative_kept(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        assert to_usermedia_relative("media/x.mp4") == "media/x.mp4"

    def test_round_trip(self, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        abs_in = os.path.join(str(tmp_path), "media", "clip.mp4")
        assert usermedia_abs_path(to_usermedia_relative(abs_in)) == abs_in
