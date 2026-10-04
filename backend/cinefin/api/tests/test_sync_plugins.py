"""Native sync-plugin (Plex / Jellyfin) and trailer-service tests."""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from plexapi.exceptions import Unauthorized

from cinefin.api.models import Job, Movie, Settings, SyncSource, Trailer
from cinefin.api.ratings import RatingResult
from cinefin.api.services import trailer_service
from cinefin.api.services.trailer_jobs import JobCancelled, JobContext
from cinefin.api.services.trailer_service import TrailerService
from cinefin.api.sync.base import SyncCancelled
from cinefin.api.sync.plugins.common import apply_path_mappings
from cinefin.api.sync.plugins.jellyfin import _PRESENCE_FIELDS, JellyfinSource
from cinefin.api.sync.plugins.plex import PlexSource
from cinefin.api.sync.service import SyncManager
from cinefin.api.tests.factories import MovieFactory, TrailerFactory
from cinefin.api.utils.media_paths import usermedia_abs_path

pytestmark = pytest.mark.django_db


class RecordingCtx:
    def __init__(self, cancel_after=None):
        self.logs, self.progress_calls = [], []
        self.cancel_after, self.checks = cancel_after, 0

    def log(self, level, message):
        self.logs.append(message)

    def info(self, msg):
        self.log("info", msg)

    warn = error = info

    def progress(self, current, total, phase="", item=""):
        self.progress_calls.append((current, total, phase, item))

    def set_phase(self, phase):
        pass

    def is_cancelled(self):
        return False

    def check_cancelled(self):
        self.checks += 1
        if self.cancel_after is not None and self.checks > self.cancel_after:
            raise SyncCancelled("Sync cancelled by user")


def sync(plugin, **params):
    return plugin.apply(RecordingCtx(), "sync", params)


def fake_plex_part(file, channels=6, width=1920, sdh=True):
    audio = [SimpleNamespace(title="Main", language="eng", codec="ac3", channels=channels)]
    subs = [SimpleNamespace(language="eng", forced=False, hearingImpaired=sdh)]
    video = [SimpleNamespace(codec="hevc", width=width, height=1080, frameRate=23.976, bitrate=8000)]
    return SimpleNamespace(
        size=1_000_000, file=file, audioStreams=lambda: audio, videoStreams=lambda: video, subtitleStreams=lambda: subs
    )


def fake_plex_movie(title, tmdbid, with_marker=True):
    part = fake_plex_part(f"/films/{title}.mkv")
    return SimpleNamespace(
        title=title,
        year=2023,
        ratingKey=str(10000 + tmdbid),
        updatedAt=timezone.now().replace(microsecond=0),
        guids=[SimpleNamespace(id=f"tmdb://{tmdbid}")],
        media=[SimpleNamespace(parts=[part], videoResolution="1080")],
        duration=7_200_000,
        contentRating="gb/15",
        directors=[SimpleNamespace(tag="Jane Doe")],
        summary="A film.",
        thumb=None,
        markers=[SimpleNamespace(type="credits", start=5_400_000)] if with_marker else [],
        addedAt=datetime(2026, 4, 5, 21, 38, 27),  # naive, as plexapi gives it
        genres=[SimpleNamespace(tag="Action"), SimpleNamespace(tag="Drama")],
        reload=lambda: None,
    )


class FakePlexServer:
    def __init__(self, movies):
        section = SimpleNamespace(type="movie", title="Films", all=lambda: movies)
        self.library = SimpleNamespace(sections=lambda: [section], section=lambda name: section)


@pytest.fixture
def plex_source():
    return SyncSource.objects.create(
        name="Plex", sync_type="plex", url="http://plex.invalid:32400", token="tok", libraries="Films"
    )


@pytest.fixture
def plex_plugin(plex_source, monkeypatch):
    movies = [fake_plex_movie("Alpha", 501), fake_plex_movie("Beta", 502, with_marker=False)]
    monkeypatch.setattr("cinefin.api.sync.plugins.plex.PlexServer", lambda url, token: FakePlexServer(movies))
    plugin = PlexSource(plex_source)
    plugin.fake_movies = movies
    return plugin


def _touch(movie):
    movie.updatedAt = timezone.now().replace(microsecond=0) + timedelta(minutes=5)


class TestPlexPlugin:
    def test_test_connection(self, plex_plugin, plex_source, monkeypatch):
        assert plex_plugin.test_connection() == (True, "Connection successful")
        assert plex_plugin.get_libraries() == ["Films"]

        def boom(url, token):
            raise Unauthorized("bad token")

        monkeypatch.setattr("cinefin.api.sync.plugins.plex.PlexServer", boom)
        ok, message = PlexSource(plex_source).test_connection()
        assert not ok and "Invalid Plex token" in message

    def test_apply_creates_movies(self, plex_plugin, plex_source):
        counts = sync(plex_plugin)
        assert (counts["added"], counts["removed"], counts["failed"]) == (2, 0, 0)
        assert counts["changes"]["added"] == ["Alpha", "Beta"]

        alpha = Movie.objects.get(tmdbid=501)
        assert (alpha.certification, alpha.duration, alpha.credits_marker) == ("15", 7200, 5400)
        assert (alpha.video_bitrate, alpha.plex_rating_key, alpha.sync_source) == (8_000_000, "10501", plex_source)
        assert sorted(alpha.genres.values_list("name", flat=True)) == ["Action", "Drama"]
        assert alpha.audio_tracks.get().channels == 6
        assert alpha.subtitle_tracks.get().sdh is True
        assert timezone.is_aware(alpha.date_added)
        assert Movie.objects.get(tmdbid=502).credits_marker == 0

    def test_incremental_skips_unchanged_and_updates_changed(self, plex_plugin):
        sync(plex_plugin)
        assert sync(plex_plugin)["skipped"] == 2

        _touch(plex_plugin.fake_movies[0])
        plex_plugin.fake_movies[0].summary = "A better synopsis."
        ctx = RecordingCtx()
        counts = plex_plugin.apply(ctx, "sync", {})
        assert (counts["updated"], counts["skipped"]) == (1, 1)
        assert Movie.objects.get(tmdbid=501).description == "A better synopsis."
        # Skipped items still advance the progress counter.
        assert ctx.progress_calls[-1][:2] == (2, 2)
        assert ctx.progress_calls[-1][3] == "Unchanged: Beta"

    def test_deep_sync_reprocesses_everything(self, plex_plugin):
        sync(plex_plugin)
        counts = sync(plex_plugin, deep=True)
        assert (counts["updated"], counts["skipped"]) == (2, 0)

    def test_orphans_pruned_only_from_this_source(self, plex_plugin, plex_source):
        other = SyncSource.objects.create(name="O", sync_type="jellyfin", url="http://o.invalid", token="t")
        MovieFactory(title="Gone", tmdbid=999, sync_source=plex_source)
        MovieFactory(title="Foreign", tmdbid=998, sync_source=other)
        # A per-film failure must not block pruning of genuinely-absent films.
        plex_plugin.fake_movies[1].reload = lambda: 1 / 0

        counts = sync(plex_plugin)
        assert (counts["removed"], counts["failed"]) == (1, 1)
        assert not Movie.objects.filter(tmdbid=999).exists()
        assert Movie.objects.filter(tmdbid=998).exists()

    def test_cancellation_stops_cleanly(self, plex_plugin):
        with pytest.raises(SyncCancelled):
            plex_plugin.apply(RecordingCtx(cancel_after=1), "sync", {})
        assert Movie.objects.count() < 2

    def test_relinks_moved_file_on_skip(self, plex_plugin):
        sync(plex_plugin)
        plex_plugin.fake_movies[0].media[0].parts[0].file = "/new/Alpha.mkv"
        assert sync(plex_plugin)["skipped"] == 2
        assert Movie.objects.get(tmdbid=501).file_path == "/new/Alpha.mkv"

    def test_tracks_come_from_the_best_version(self, plex_plugin):
        sd = SimpleNamespace(parts=[fake_plex_part("/films/Alpha-sd.mkv", 2, 720, False)], videoResolution="sd")
        uhd = SimpleNamespace(parts=[fake_plex_part("/films/Alpha-4k.mkv", 8, 3840)], videoResolution="4k")
        plex_plugin.fake_movies[0].media = [sd, uhd]
        sync(plex_plugin)
        alpha = Movie.objects.get(tmdbid=501)
        assert (alpha.file_path, alpha.video_width) == ("/films/Alpha-4k.mkv", 3840)
        assert alpha.audio_tracks.get().channels == 8
        assert alpha.subtitle_tracks.get().sdh is True


class TestProbe:
    def test_probe_reuses_saved_token_when_editing(self, plex_source, monkeypatch):
        seen = {}
        monkeypatch.setattr(
            "cinefin.api.sync.plugins.plex.PlexServer",
            lambda url, token: seen.update(token=token) or FakePlexServer([]),
        )
        result = SyncManager.probe(sync_type="plex", url=plex_source.url, token="********", source_id=plex_source.id)
        assert result == {"success": True, "message": "Connection successful", "libraries": ["Films"]}
        assert seen["token"] == "tok"


class FakeResponse:
    def __init__(self, payload):
        self._payload, self.status_code, self.content = payload, 200, b"x"

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def jellyfin_item(title, item_id, tmdbid):
    return {
        "Name": title,
        "Id": item_id,
        "ProviderIds": {"Tmdb": str(tmdbid)},
        "ProductionYear": 2022,
        "People": [{"Type": "Director", "Name": "John Smith"}],
        "Genres": ["Horror"],
        "RunTimeTicks": 60_000_000_000,
        "DateCreated": "2024-03-04T10:00:00.0000000Z",
        "DateLastSaved": "2024-03-05T10:00:00.0000000Z",
        "ImageTags": {},
    }


def jellyfin_detail(path, size=5_000):
    streams = [
        {"Type": "Video", "DisplayTitle": "1080p H264", "Codec": "h264", "Width": 1920, "Height": 1080},
        {"Type": "Audio", "DisplayTitle": "Eng 5.1", "Language": "eng", "Codec": "eac3", "Channels": 6},
        {"Type": "Subtitle", "Language": "swe", "IsForced": True, "IsHearingImpaired": False},
    ]
    return {"MediaSources": [{"Size": size, "Path": path, "MediaStreams": streams}]}


@pytest.fixture
def jellyfin_source():
    return SyncSource.objects.create(
        name="Jellyfin", sync_type="jellyfin", url="http://jf.invalid:8096", token="tok", libraries="Films"
    )


@pytest.fixture
def jellyfin_plugin(jellyfin_source, monkeypatch):
    items = [jellyfin_item("Gamma", "i1", 601), jellyfin_item("Delta", "i2", 602)]
    details = {"i1": jellyfin_detail("/films/gamma.mkv"), "i2": jellyfin_detail("/films/delta.mkv", 6_000)}

    def _light(item, params):
        row = {"Id": item["Id"], "ProviderIds": item.get("ProviderIds", {}), "Path": item.get("Path")}
        # Real Jellyfin omits ImageTags when EnableImages is false.
        if params.get("EnableImages") is not False:
            row["ImageTags"] = item.get("ImageTags", {})
        return row

    def fake_get(url, headers=None, params=None, timeout=None):
        # Jellyfin 10.9+/12.x reject X-Emby-Token; the token must ride Authorization.
        assert headers["Authorization"].startswith("MediaBrowser ") and 'Token="tok"' in headers["Authorization"]
        assert "X-Emby-Token" not in headers
        params = params or {}
        path = url.replace("http://jf.invalid:8096", "")
        if path == "/System/Info":
            return FakeResponse({"ServerName": "TestJF", "Version": "12.1.0"})
        if path == "/Users":
            return FakeResponse([{"Id": "u1", "Name": "admin", "Policy": {"IsAdministrator": True}}])
        if path == "/Library/MediaFolders":
            return FakeResponse({"Items": [{"Name": "Films", "Id": "lib1", "CollectionType": "movies"}]})
        assert params.get("userId") == "u1"  # the version-portable /Items?userId= routes
        if path == "/Items":
            if params.get("Ids"):
                wanted = set(params["Ids"].split(","))
                return FakeResponse({"Items": [i for i in items if i["Id"] in wanted]})
            if params.get("Fields") == _PRESENCE_FIELDS:
                rows = [_light(i, params) for i in items]
                return FakeResponse({"Items": rows, "TotalRecordCount": len(rows)})
            selected = items
            if since := JellyfinSource._parse_date(params.get("MinDateLastSaved") or ""):
                selected = [i for i in items if JellyfinSource._parse_date(i["DateLastSaved"]) >= since]
            start = params.get("StartIndex", 0)
            return FakeResponse({"Items": selected[start:], "TotalRecordCount": len(selected)})
        return FakeResponse(details[path.removeprefix("/Items/")])

    monkeypatch.setattr("cinefin.api.sync.plugins.jellyfin.requests.get", fake_get)
    plugin = JellyfinSource(jellyfin_source)
    plugin.fake_items, plugin.fake_details = items, details
    return plugin


def _mark_synced(source, when=datetime(2024, 3, 6, tzinfo=UTC)):
    """Stand in for the engine stamping last_sync, which puts the next run into delta mode."""
    source.last_sync = when
    source.save(update_fields=["last_sync"])


class TestJellyfinPlugin:
    def test_test_connection(self, jellyfin_plugin):
        assert jellyfin_plugin.test_connection() == (True, "Connection successful")
        assert jellyfin_plugin.user_id == "u1"
        assert jellyfin_plugin.get_libraries() == ["Films"]

    def test_apply_creates_movies(self, jellyfin_plugin, jellyfin_source):
        ctx = RecordingCtx()
        counts = jellyfin_plugin.apply(ctx, "sync", {})
        assert (counts["added"], counts["removed"], counts["failed"]) == (2, 0, 0)
        gamma = Movie.objects.get(tmdbid=601)
        assert (gamma.file_path, gamma.director, gamma.resolution) == ("/films/gamma.mkv", "John Smith", "1080p")
        assert (gamma.duration, gamma.jellyfin_item_id, gamma.sync_source) == (6000, "i1", jellyfin_source)
        assert gamma.remote_updated_at is not None
        assert gamma.audio_tracks.get().codec == "eac3"
        assert gamma.subtitle_tracks.get().forced is True
        assert any("Added: Gamma" in m for m in ctx.logs)
        # The listing is paginated, so the total is counted up front, not pinned to current.
        assert all(total == 2 for _c, total, _p, _i in ctx.progress_calls)
        assert ctx.progress_calls[-1][0] == 2

    def test_incremental_skips_unchanged_and_fetches_only_changed(self, jellyfin_plugin, jellyfin_source):
        sync(jellyfin_plugin)
        _mark_synced(jellyfin_source)
        counts = sync(jellyfin_plugin)
        assert (counts["skipped"], counts["added"], counts["updated"]) == (2, 0, 0)

        jellyfin_plugin.fake_items[0]["DateLastSaved"] = "2024-03-20T10:00:00.0000000Z"
        ctx = RecordingCtx()
        counts = jellyfin_plugin.apply(ctx, "sync", {})
        assert (counts["updated"], counts["skipped"]) == (1, 1)
        assert any("Changed: Gamma" in m for m in ctx.logs)

    def test_presence_pass_prunes_heals_and_recovers(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.fake_items[0]["ImageTags"] = {"Primary": "tagA"}
        sync(jellyfin_plugin)
        assert Movie.objects.get(tmdbid=601).poster_key == "tagA"
        _mark_synced(jellyfin_source)

        # Nothing "changed" since last sync, so only the presence pass sees any of this.
        jellyfin_plugin.fake_items[0]["ImageTags"] = {"Primary": "tagB"}
        jellyfin_plugin.fake_items[0]["Path"] = "/movies/gamma.mkv"
        jellyfin_plugin.fake_items.pop()  # Delta gone from the server
        counts = sync(jellyfin_plugin)
        assert counts["removed"] == 1
        gamma = Movie.objects.get(tmdbid=601)
        assert (gamma.poster_key, gamma.file_path) == ("tagB", "/movies/gamma.mkv")

        # A film present on the server but lost from the DB is recovered.
        jellyfin_plugin.fake_items.append(jellyfin_item("Delta", "i2", 602))
        assert sync(jellyfin_plugin)["added"] == 1
        assert Movie.objects.filter(jellyfin_item_id="i2").exists()

    def test_deep_reprocesses_present_films(self, jellyfin_plugin, jellyfin_source):
        sync(jellyfin_plugin)
        _mark_synced(jellyfin_source)
        counts = sync(jellyfin_plugin, deep=True)
        assert (counts["skipped"], counts["updated"]) == (0, 2)


class TestUnmatched:
    def test_plex_films_without_tmdb_are_imported_reported_and_kept(self, plex_plugin):
        for m in plex_plugin.fake_movies:
            m.guids = []
        counts = sync(plex_plugin)
        assert (counts["added"], counts["unmatched"], counts["failed"]) == (2, 2, 0)
        assert counts["changes"]["unmatched"] == ["Alpha (2023)", "Beta (2023)"]
        assert set(Movie.objects.filter(tmdbid=0).values_list("plex_rating_key", flat=True)) == {"10501", "10502"}

        counts = sync(plex_plugin)  # no collisions, and orphan pruning leaves them alone
        assert (counts["skipped"], counts["removed"]) == (2, 0)
        assert Movie.objects.filter(tmdbid=0).count() == 2

    def test_jellyfin_films_without_tmdb_are_imported(self, jellyfin_plugin, jellyfin_source):
        for item in jellyfin_plugin.fake_items:
            item["ProviderIds"] = {}
        counts = sync(jellyfin_plugin)
        assert (counts["unmatched"], counts["added"]) == (2, 2)
        assert set(Movie.objects.filter(tmdbid=0).values_list("jellyfin_item_id", flat=True)) == {"i1", "i2"}
        _mark_synced(jellyfin_source)
        assert sync(jellyfin_plugin)["skipped"] == 2


class TestPathMappings:
    def test_longest_prefix_wins(self, plex_source):
        plex_source.path_mappings = [{"from": "/data", "to": "/mnt"}, {"from": "/data/movies", "to": "/mnt/films"}]
        assert apply_path_mappings("/data/movies/a.mkv", plex_source) == "/mnt/films/a.mkv"
        assert apply_path_mappings("/data/other/b.mkv", plex_source) == "/mnt/other/b.mkv"
        assert apply_path_mappings("/elsewhere/c.mkv", plex_source) == "/elsewhere/c.mkv"

    def test_plex_sync_applies_mappings(self, plex_plugin, plex_source):
        plex_source.path_mappings = [{"from": "/films", "to": "/mnt/movies"}]
        plex_source.save()
        sync(plex_plugin)
        assert Movie.objects.get(tmdbid=501).file_path == "/mnt/movies/Alpha.mkv"


@pytest.fixture
def trailer_settings(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    (tmp_path / "trailers").mkdir()
    Settings.set("trailers", {"tmdb_api_key": "test-key"})
    return tmp_path / "trailers"


def _provider(monkeypatch, lookup):
    monkeypatch.setattr(
        "cinefin.api.ratings.get_provider",
        lambda system: SimpleNamespace(display_name="fake source", lookup=lookup),
    )


def _rated(rating):
    return lambda title, year=None: RatingResult(system="BBFC", rating=rating, matched_title=title, year=year)


class TestTrailerService:
    @pytest.mark.parametrize(
        "operation,method",
        [
            ("verify", "verify_existing_trailers"),
            ("library", "fetch_library_trailers"),
            ("ratings", "update_ratings"),
            ("rename", "rename_existing_trailers"),
            ("upcoming", "fetch_discover_trailers"),  # legacy alias old job rows still carry
        ],
    )
    def test_run_operation_dispatches(self, trailer_settings, monkeypatch, operation, method):
        service = TrailerService()
        received = {}
        monkeypatch.setattr(service, method, lambda **kw: received.update(kw) or True)
        assert service.run_operation(operation, {"limit": 5} if operation == "upcoming" else None) is True
        if operation == "upcoming":
            assert received["limit"] == 5

    def test_verify_imports_orphans_and_relinks(self, trailer_settings, monkeypatch):
        (trailer_settings / "Orphan Film (2023) [tmdb-901].mp4").write_bytes(b"fake")
        known = TrailerFactory(title="Known", tmdbid=902, file_path=str(trailer_settings / "old-location.mp4"))
        (trailer_settings / "Known (2020) [tmdb-902].mp4").write_bytes(b"fake")
        details = {
            "title": "Orphan Film",
            "release_date": "2023-06-01",
            "genres": [{"name": "Action"}],
            "release_dates": {"results": [{"iso_3166_1": "GB", "release_dates": [{"certification": "12A"}]}]},
            "credits": {"crew": [{"job": "Director", "name": "Jane Doe"}]},
        }
        service = TrailerService()
        monkeypatch.setattr(service, "_get_video_duration", lambda path: 120)
        monkeypatch.setattr(service.tmdb_movie, "details", lambda tmdbid, **kwargs: details)

        assert service.verify_existing_trailers() is True
        imported = Trailer.objects.get(tmdbid=901)
        assert (imported.title, imported.year, imported.content_rating) == ("Orphan Film", 2023, "12A")
        known.refresh_from_db()
        assert known.file_path == "trailers/Known (2020) [tmdb-902].mp4"
        assert service.sync_counts == {"added": 1, "updated": 1, "skipped": 0, "failed": 0}

    def test_discover_downloads_new_and_skips_existing(self, trailer_settings, monkeypatch):
        TrailerFactory(tmdbid=904, title="Already Here")
        discovered = [
            {"id": 903, "title": "New Film", "release_date": "2026-10-01"},
            {"id": 904, "title": "Already Here", "release_date": "2026-01-01"},
        ]
        details = {
            "title": "New Film",
            "genres": [],
            "videos": {"results": [{"type": "Trailer", "site": "YouTube", "key": "abc123", "size": 1080}]},
            "release_dates": {"results": []},
            "credits": {"crew": []},
        }
        downloads = []

        class FakeYDL:
            def __init__(self, opts):
                self.opts = opts

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def download(self, urls):
                downloads.extend(urls)
                with open(self.opts["outtmpl"], "wb") as f:
                    f.write(b"video")

        monkeypatch.setattr(trailer_service, "Discover", lambda: SimpleNamespace(discover_movies=lambda p: discovered))
        monkeypatch.setattr(trailer_service.yt_dlp, "YoutubeDL", FakeYDL)
        service = TrailerService()
        monkeypatch.setattr(service, "_get_video_duration", lambda path: 90)
        monkeypatch.setattr(
            service.tmdb_movie, "details", lambda tmdbid, **kw: details if tmdbid == 903 else pytest.fail("existing")
        )

        assert service.fetch_discover_trailers(year_from=2026, year_to=2026, limit=10) is True
        assert downloads == ["https://www.youtube.com/watch?v=abc123"]
        trailer = Trailer.objects.get(tmdbid=903)
        assert (trailer.year, trailer.month, trailer.duration) == (2026, 10, 90)
        assert trailer.file_path.startswith("trailers/")
        assert Trailer.objects.filter(tmdbid=904).count() == 1

    def test_single_fetch_refills_a_row_without_its_file(self, trailer_settings, monkeypatch):
        row = TrailerFactory(tmdbid=905, title="Lost File", file_path=str(trailer_settings / "gone.mp4"))
        details = {
            "title": "Lost File",
            "release_date": "2025-03-01",
            "genres": [],
            "videos": {"results": [{"type": "Trailer", "site": "YouTube", "key": "k905"}]},
            "release_dates": {"results": []},
            "credits": {"crew": []},
        }
        service = TrailerService()
        monkeypatch.setattr(service, "_get_video_duration", lambda path: 95)
        monkeypatch.setattr(service.tmdb_movie, "details", lambda tmdbid, **kw: details)
        monkeypatch.setattr(service, "_ytdlp_fetch", lambda key, dest: open(dest, "wb").write(b"video"))

        assert service.fetch_single_trailer(905) is True
        row.refresh_from_db()
        assert Trailer.objects.filter(tmdbid=905).count() == 1
        assert os.path.exists(usermedia_abs_path(row.file_path)) and row.duration == 95
        assert service.sync_counts == {"updated": 1}

    def test_ratings_update_and_repair(self, trailer_settings, monkeypatch):
        trailer = TrailerFactory(title="Unrated Film", content_rating="")
        movie = MovieFactory(certification="R")
        movie.certificates = {"BBFC": "R"}  # wrong-scheme value in the BBFC slot
        movie.save()
        _provider(monkeypatch, _rated("15"))

        assert TrailerService().update_ratings() is True
        trailer.refresh_from_db()
        movie.refresh_from_db()
        assert (trailer.content_rating, trailer.certificates, trailer.rating_lookups) == (
            "15",
            {"BBFC": "15"},
            {"BBFC": "matched"},
        )
        assert (movie.certificates["BBFC"], movie.certification) == ("15", "15")

    def test_ratings_scope_and_unmatched_memo(self, trailer_settings, monkeypatch):
        movie = MovieFactory(title="Unrated Movie", certification="")
        trailer = TrailerFactory(title="Unrated Trailer", content_rating="")
        looked = []
        _provider(monkeypatch, lambda title, year=None: looked.append(title))

        assert TrailerService().update_ratings(scope="movies") is True
        assert looked == [movie.title]
        assert TrailerService().update_ratings(scope="trailers") is True
        assert looked == [movie.title, trailer.title]
        trailer.refresh_from_db()
        assert trailer.rating_lookups == {"BBFC": "unmatched"}
        TrailerService().update_ratings()  # unmatched films aren't re-queried
        assert len(looked) == 2

    def test_ratings_aborts_when_provider_keeps_failing(self, trailer_settings, monkeypatch):
        monkeypatch.setattr(trailer_service.time, "sleep", lambda *_: None)
        movies = [MovieFactory(title=f"Film {i}", certification="") for i in range(8)]
        calls = []

        def down(title, year=None):
            calls.append(title)
            raise RuntimeError("site unavailable")

        _provider(monkeypatch, down)
        assert TrailerService().update_ratings(scope="movies") is False
        assert len(calls) == trailer_service.RATING_LOOKUP_ABORT_AFTER
        for m in movies:
            m.refresh_from_db()
            assert (m.rating_lookups or {}).get("BBFC") != "unmatched"

    def test_job_context_persists_output_and_cancels(self, trailer_settings):
        job = Job.trailer.create(operation="verify", state=Job.STATE_RUNNING)
        ctx = JobContext(job)
        service = TrailerService(log=ctx.log, progress=ctx.update_progress, check_cancelled=ctx.check_cancelled)
        assert service.run_operation("verify", {}) is True
        ctx.flush()
        job.refresh_from_db()
        assert any("Verification complete" in entry["message"] for entry in job.log)
        assert job.current == job.total

        (trailer_settings / "Some Film (2023) [tmdb-906].mp4").write_bytes(b"fake")
        job = Job.trailer.create(operation="verify", state=Job.STATE_RUNNING, cancel_requested=True)
        ctx = JobContext(job)
        service = TrailerService(log=ctx.log, progress=ctx.update_progress, check_cancelled=ctx.check_cancelled)
        with pytest.raises(JobCancelled):
            service.run_operation("verify", {})
