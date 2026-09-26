"""Native sync-plugin (Plex / Jellyfin) and trailer-service tests."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from plexapi.exceptions import Unauthorized

from cinefin.api.models import Job, Movie, Settings, SyncSource, Trailer
from cinefin.api.services import trailer_service
from cinefin.api.services.trailer_jobs import JobCancelled, JobContext
from cinefin.api.services.trailer_service import TrailerCancelled, TrailerService
from cinefin.api.sync.base import SyncCancelled
from cinefin.api.sync.plugins.jellyfin import JellyfinSource
from cinefin.api.sync.plugins.plex import PlexSource
from cinefin.api.tests.factories import MovieFactory, TrailerFactory

pytestmark = pytest.mark.django_db


class RecordingCtx:
    def __init__(self, cancel_after: int | None = None):
        self.logs: list[tuple[str, str]] = []
        self.progress_calls: list[tuple[int, int, str, str]] = []
        self.cancel_after = cancel_after
        self.checks = 0

    def log(self, level, message):
        self.logs.append((level.upper(), message))

    def info(self, msg):
        self.log("info", msg)

    def warn(self, msg):
        self.log("warning", msg)

    def error(self, msg):
        self.log("error", msg)

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

    def messages(self):
        return [m for _, m in self.logs]


def fake_plex_movie(title, tmdbid, size=1_000_000, with_marker=True, updated_at=None):
    audio = [SimpleNamespace(title="Main", language="eng", codec="ac3", channels=6)]
    subs = [SimpleNamespace(language="eng", forced=False, hearingImpaired=True)]
    video = [SimpleNamespace(codec="hevc", width=1920, height=1080, frameRate=23.976, bitrate=8000)]
    part = SimpleNamespace(
        size=size,
        file=f"/films/{title}.mkv",
        audioStreams=lambda: audio,
        videoStreams=lambda: video,
    )
    media = SimpleNamespace(parts=[part], videoResolution="1080")
    markers = [SimpleNamespace(type="credits", start=5_400_000)] if with_marker else []
    return SimpleNamespace(
        title=title,
        year=2023,
        ratingKey=str(10000 + tmdbid),
        updatedAt=updated_at or timezone.now().replace(microsecond=0),
        guids=[SimpleNamespace(id=f"tmdb://{tmdbid}")],
        media=[media],
        duration=7_200_000,
        contentRating="gb/15",
        directors=[SimpleNamespace(tag="Jane Doe")],
        summary="A film.",
        thumb=None,
        markers=markers,
        addedAt=timezone.now(),
        genres=[SimpleNamespace(tag="Action"), SimpleNamespace(tag="Drama")],
        subtitleStreams=lambda: subs,
        reload=lambda: None,
    )


class FakePlexServer:
    def __init__(self, movies):
        sections = {"Films": SimpleNamespace(type="movie", title="Films", all=lambda: movies)}
        self.library = SimpleNamespace(
            sections=lambda: list(sections.values()),
            section=lambda name: sections[name],
        )


@pytest.fixture
def plex_source():
    return SyncSource.objects.create(
        name="Plex", sync_type="plex", url="http://plex.invalid:32400", token="tok", libraries="Films"
    )


@pytest.fixture
def plex_plugin(plex_source, monkeypatch):
    movies = [fake_plex_movie("Alpha", 501), fake_plex_movie("Beta", 502, with_marker=False)]
    monkeypatch.setattr(
        "cinefin.api.sync.plugins.plex.PlexServer",
        lambda url, token: FakePlexServer(movies),
    )
    plugin = PlexSource(plex_source)
    plugin.fake_movies = movies
    return plugin


class TestPlexPlugin:
    def test_test_connection_success(self, plex_plugin):
        ok, message = plex_plugin.test_connection()
        assert ok is True
        assert message == "Connection successful"
        assert plex_plugin.get_libraries() == ["Films"]

    def test_test_connection_unauthorized(self, plex_source, monkeypatch):
        def boom(url, token):
            raise Unauthorized("bad token")

        monkeypatch.setattr("cinefin.api.sync.plugins.plex.PlexServer", boom)
        ok, message = PlexSource(plex_source).test_connection()
        assert ok is False
        assert "Invalid Plex token" in message

    def test_apply_creates_movies(self, plex_plugin, plex_source):
        ctx = RecordingCtx()
        counts = plex_plugin.apply(ctx, "sync", {})

        assert counts["added"] == 2
        assert counts["removed"] == 0
        assert counts["failed"] == 0
        assert counts["changes"]["added"] == ["Alpha", "Beta"]
        assert Movie.objects.count() == 2

        alpha = Movie.objects.get(tmdbid=501)
        assert alpha.title == "Alpha"
        assert alpha.year == 2023
        assert alpha.certification == "15"
        assert alpha.resolution == "1080"
        assert alpha.file_size == 1_000_000
        assert alpha.director == "Jane Doe"
        assert alpha.duration == 7200
        assert alpha.runtime == 120
        assert alpha.credits_marker == 5400
        assert alpha.sync_source == plex_source
        assert sorted(alpha.genres.values_list("name", flat=True)) == ["Action", "Drama"]

        assert alpha.video_codec == "hevc"
        assert (alpha.video_width, alpha.video_height) == (1920, 1080)
        assert alpha.video_framerate == 23.976
        assert alpha.video_bitrate == 8_000_000

        assert alpha.audio_tracks.count() == 1
        track = alpha.audio_tracks.get()
        assert (track.language, track.codec, track.channels) == ("eng", "ac3", 6)
        assert alpha.subtitle_tracks.count() == 1
        sub = alpha.subtitle_tracks.get()
        assert (sub.language, sub.forced, sub.sdh) == ("eng", False, True)

        beta = Movie.objects.get(tmdbid=502)
        assert beta.credits_marker == 0

        assert ctx.progress_calls
        assert any("Sync complete: 2 added" in m for m in ctx.messages())
        assert alpha.plex_rating_key == "10501"
        assert alpha.remote_updated_at is not None

    def test_apply_skips_unchanged_and_updates_changed(self, plex_plugin):
        plex_plugin.apply(RecordingCtx(), "sync", {})

        counts = plex_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["skipped"] == 2
        assert counts["added"] == 0 and counts["updated"] == 0
        assert Movie.objects.count() == 2

        plex_plugin.fake_movies[0].updatedAt = timezone.now().replace(microsecond=0) + timedelta(minutes=5)
        plex_plugin.fake_movies[0].summary = "A better synopsis."
        counts = plex_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["updated"] == 1
        assert counts["skipped"] == 1
        assert Movie.objects.get(tmdbid=501).description == "A better synopsis."

    def test_progress_reaches_total_when_tail_is_skipped(self, plex_plugin):
        """Regression: skipped items must still advance the progress counter."""
        plex_plugin.apply(RecordingCtx(), "sync", {})

        plex_plugin.fake_movies[0].updatedAt = timezone.now().replace(microsecond=0) + timedelta(minutes=5)
        ctx = RecordingCtx()
        counts = plex_plugin.apply(ctx, "sync", {})
        assert counts["updated"] == 1 and counts["skipped"] == 1
        current, total, _, item = ctx.progress_calls[-1]
        assert (current, total) == (2, 2)
        assert item == "Unchanged: Beta"

        ctx = RecordingCtx()
        counts = plex_plugin.apply(ctx, "sync", {})
        assert counts["skipped"] == 2
        assert ctx.progress_calls[-1][:2] == (2, 2)

    def test_deep_sync_reprocesses_everything(self, plex_plugin):
        plex_plugin.apply(RecordingCtx(), "sync", {})
        counts = plex_plugin.apply(RecordingCtx(), "sync", {"deep": True})
        assert counts["updated"] == 2
        assert counts["skipped"] == 0

    def test_apply_removes_orphans_scoped_to_source(self, plex_plugin, plex_source):
        other_source = SyncSource.objects.create(
            name="Other", sync_type="jellyfin", url="http://o.invalid", token="t", libraries="Films"
        )
        MovieFactory(title="Gone", tmdbid=999, sync_source=plex_source)
        MovieFactory(title="Foreign", tmdbid=998, sync_source=other_source)

        counts = plex_plugin.apply(RecordingCtx(), "sync", {})

        assert counts["removed"] == 1
        assert not Movie.objects.filter(tmdbid=999).exists()
        assert Movie.objects.filter(tmdbid=998).exists()

    def test_apply_cancellation_stops_cleanly(self, plex_plugin):
        ctx = RecordingCtx(cancel_after=1)
        with pytest.raises(SyncCancelled):
            plex_plugin.apply(ctx, "sync", {})
        assert Movie.objects.count() < 2

    def test_apply_relinks_moved_file_on_skip(self, plex_plugin):
        plex_plugin.apply(RecordingCtx(), "sync", {})
        alpha = Movie.objects.get(tmdbid=501)
        assert alpha.file_path == "/films/Alpha.mkv"

        plex_plugin.fake_movies[0].media[0].parts[0].file = "/new/Alpha.mkv"
        counts = plex_plugin.apply(RecordingCtx(), "sync", {})

        assert counts["skipped"] == 2
        alpha.refresh_from_db()
        assert alpha.file_path == "/new/Alpha.mkv"

    def test_apply_prunes_orphan_despite_a_processing_failure(self, plex_plugin, plex_source):
        """A per-film failure must not block pruning of genuinely-absent films."""
        MovieFactory(title="Gone", tmdbid=999, sync_source=plex_source)

        def boom():
            raise RuntimeError("bad reload")

        plex_plugin.fake_movies[1].reload = boom

        counts = plex_plugin.apply(RecordingCtx(), "sync", {})

        assert counts["failed"] == 1
        assert counts["removed"] == 1
        assert not Movie.objects.filter(tmdbid=999).exists()


class TestProbe:
    """SyncManager.probe lists a server's libraries without saving a source."""

    def test_probe_lists_libraries_for_unsaved_connection(self, monkeypatch):
        from cinefin.api.sync.service import SyncManager

        monkeypatch.setattr(
            "cinefin.api.sync.plugins.plex.PlexServer",
            lambda url, token: FakePlexServer([]),
        )
        result = SyncManager.probe(sync_type="plex", url="http://plex.invalid:32400/", token="tok")
        assert result == {"success": True, "message": "Connection successful", "libraries": ["Films"]}
        assert not SyncSource.objects.exists()

    def test_probe_reuses_saved_token_when_editing(self, plex_source, monkeypatch):
        from cinefin.api.sync.service import SyncManager

        seen = {}

        def fake_server(url, token):
            seen["token"] = token
            return FakePlexServer([])

        monkeypatch.setattr("cinefin.api.sync.plugins.plex.PlexServer", fake_server)
        result = SyncManager.probe(sync_type="plex", url=plex_source.url, token="********", source_id=plex_source.id)
        assert result["success"] is True
        assert seen["token"] == "tok"

    def test_probe_rejects_missing_credentials(self):
        from cinefin.api.exceptions import ValidationError
        from cinefin.api.sync.service import SyncManager

        with pytest.raises(ValidationError):
            SyncManager.probe(sync_type="plex", url="", token="tok")


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.content = b"x" if payload is not None else b""

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
        "Overview": "Spooky.",
        "RunTimeTicks": 60_000_000_000,
        "DateCreated": "2024-03-04T10:00:00.0000000Z",
        "DateLastSaved": "2024-03-05T10:00:00.0000000Z",
        "ImageTags": {},
    }


def jellyfin_detail(path, size=5_000):
    return {
        "MediaSources": [
            {
                "Size": size,
                "Path": path,
                "DateModified": "2024-01-02T03:04:05.1234567Z",
                "MediaStreams": [
                    {
                        "Type": "Video",
                        "DisplayTitle": "1080p H264",
                        "Codec": "h264",
                        "Width": 1920,
                        "Height": 1080,
                        "RealFrameRate": 24,
                        "BitRate": 6_000_000,
                    },
                    {"Type": "Audio", "DisplayTitle": "Eng 5.1", "Language": "eng", "Codec": "eac3", "Channels": 6},
                    {"Type": "Subtitle", "Language": "swe", "IsForced": True, "IsHearingImpaired": False},
                ],
            }
        ],
        "DateCreated": "2024-03-04T10:00:00.0000000Z",
    }


@pytest.fixture
def jellyfin_source():
    return SyncSource.objects.create(
        name="Jellyfin", sync_type="jellyfin", url="http://jf.invalid:8096", token="tok", libraries="Films"
    )


@pytest.fixture
def jellyfin_plugin(jellyfin_source, monkeypatch):
    items = [jellyfin_item("Gamma", "i1", 601), jellyfin_item("Delta", "i2", 602)]
    details = {
        "i1": jellyfin_detail("/films/gamma.mkv"),
        "i2": jellyfin_detail("/films/delta.mkv", size=6_000),
    }

    def _light(item):
        return {k: item.get(k) for k in ("Id", "ProviderIds", "ImageTags", "Path")}

    def _changed_since(item, since_iso):
        since = JellyfinSource._parse_date(since_iso)
        saved = JellyfinSource._parse_date(item.get("DateLastSaved") or "")
        return saved is not None and since is not None and saved >= since

    def fake_get(url, headers=None, params=None, timeout=None):
        # Auth must ride the version-portable Authorization header, never X-Emby-Token.
        assert (headers or {}).get("Authorization", "").startswith("MediaBrowser ")
        assert "X-Emby-Token" not in (headers or {})
        params = params or {}
        path = url.replace("http://jf.invalid:8096", "")
        if path == "/System/Info":
            return FakeResponse({"ServerName": "TestJF", "Version": "12.1.0"})
        if path == "/Users":
            return FakeResponse([{"Id": "u1", "Name": "admin", "Policy": {"IsAdministrator": True}}])
        if path == "/Library/MediaFolders":
            return FakeResponse({"Items": [{"Name": "Films", "Id": "lib1", "CollectionType": "movies"}]})
        if path == "/Items":  # the item list (userId supplied as a query param)
            assert params.get("userId") == "u1"
            if params.get("Ids"):  # recovery by explicit ids → full items
                wanted = set(params["Ids"].split(","))
                return FakeResponse({"Items": [i for i in items if i["Id"] in wanted]})
            if "EnableImages" in params:  # the light presence pass
                rows = [_light(i) for i in items]
                return FakeResponse({"Items": rows, "TotalRecordCount": len(rows)})
            selected = items
            if params.get("MinDateLastSaved"):  # the incremental delta
                selected = [i for i in items if _changed_since(i, params["MinDateLastSaved"])]
            start = params.get("StartIndex", 0)
            return FakeResponse({"Items": selected[start:], "TotalRecordCount": len(selected)})
        for item_id, detail in details.items():
            if path == f"/Items/{item_id}":  # per-item detail
                assert params.get("userId") == "u1"
                return FakeResponse(detail)
        raise AssertionError(f"Unexpected Jellyfin request: {path}")

    monkeypatch.setattr("cinefin.api.sync.plugins.jellyfin.requests.get", fake_get)
    plugin = JellyfinSource(jellyfin_source)
    plugin.fake_items = items
    plugin.fake_details = details
    return plugin


class TestJellyfinPlugin:
    def test_auth_uses_mediabrowser_authorization(self, jellyfin_source):
        # Jellyfin 10.9+/12.x reject X-Emby-Token; the token must ride Authorization.
        plugin = JellyfinSource(jellyfin_source)
        auth = plugin.headers.get("Authorization", "")
        assert auth.startswith("MediaBrowser ")
        assert 'Token="tok"' in auth
        assert "X-Emby-Token" not in plugin.headers

    def test_test_connection_success(self, jellyfin_plugin):
        ok, message = jellyfin_plugin.test_connection()
        assert ok is True
        assert message == "Connection successful"
        assert jellyfin_plugin.user_id == "u1"
        assert jellyfin_plugin.get_libraries() == ["Films"]

    def test_test_connection_failure(self, jellyfin_source, monkeypatch):
        def boom(*args, **kwargs):
            raise ConnectionError("no route to host")

        monkeypatch.setattr("cinefin.api.sync.plugins.jellyfin.requests.get", boom)
        ok, message = JellyfinSource(jellyfin_source).test_connection()
        assert ok is False
        assert message == "Connection failed"

    def test_apply_creates_movies(self, jellyfin_plugin, jellyfin_source):
        ctx = RecordingCtx()
        counts = jellyfin_plugin.apply(ctx, "sync", {})

        assert counts["added"] == 2
        assert counts["removed"] == 0
        assert counts["failed"] == 0
        gamma = Movie.objects.get(tmdbid=601)
        assert gamma.title == "Gamma"
        assert gamma.year == 2022
        assert gamma.file_path == "/films/gamma.mkv"
        assert gamma.file_size == 5_000
        assert gamma.director == "John Smith"
        assert gamma.certification == ""
        assert gamma.resolution == "1080p"
        assert gamma.video_codec == "h264"
        assert (gamma.video_width, gamma.video_height) == (1920, 1080)
        assert gamma.video_framerate == 24
        assert gamma.video_bitrate == 6_000_000
        assert gamma.runtime == 100
        assert gamma.duration == 6000
        assert gamma.jellyfin_item_id == "i1"
        assert gamma.sync_source == jellyfin_source
        assert list(gamma.genres.values_list("name", flat=True)) == ["Horror"]
        assert gamma.date_added.year == 2024

        track = gamma.audio_tracks.get()
        assert (track.title, track.codec, track.channels) == ("Eng 5.1", "eac3", 6)
        sub = gamma.subtitle_tracks.get()
        assert (sub.language, sub.forced, sub.sdh) == ("swe", True, False)

        assert any("Added: Gamma" in m for m in ctx.messages())
        assert ctx.progress_calls

    def test_progress_denominator_is_the_real_total(self, jellyfin_plugin):
        # Regression: the stream is paginated, so the total must be counted up
        # front. It used to report current==total, pinning progress at 100%.
        ctx = RecordingCtx()
        jellyfin_plugin.apply(ctx, "sync", {})
        assert ctx.progress_calls
        assert all(total == 2 for _cur, total, _phase, _item in ctx.progress_calls)
        assert ctx.progress_calls[-1][0] == 2  # current reaches the total by the end

    def _mark_synced(self, source, when=datetime(2024, 3, 6, tzinfo=UTC)):
        # Stand in for the engine stamping last_sync after a successful run, which is
        # what puts the plugin into incremental (delta) mode on the next run.
        source.last_sync = when
        source.save(update_fields=["last_sync"])

    def test_incremental_skips_unchanged(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})  # initial full import
        self._mark_synced(jellyfin_source)  # after the films' DateLastSaved (2024-03-05)

        ctx = RecordingCtx()
        counts = jellyfin_plugin.apply(ctx, "sync", {})
        assert counts["skipped"] == 2  # delta empty → both confirmed present, unchanged
        assert counts["added"] == 0 and counts["updated"] == 0
        assert Movie.objects.count() == 2
        assert not any("Added:" in m for m in ctx.messages())

    def test_incremental_fetches_only_changed(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        self._mark_synced(jellyfin_source, datetime(2024, 3, 10, tzinfo=UTC))
        # Gamma changed after the last sync; Delta did not.
        jellyfin_plugin.fake_items[0]["DateLastSaved"] = "2024-03-20T10:00:00.0000000Z"

        ctx = RecordingCtx()
        counts = jellyfin_plugin.apply(ctx, "sync", {})
        assert counts["updated"] == 1  # only Gamma re-ingested
        assert counts["skipped"] == 1  # Delta unchanged
        assert any("Changed: Gamma" in m for m in ctx.messages())

    def test_incremental_prunes_orphan_via_presence_pass(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        self._mark_synced(jellyfin_source)
        # The server drops Delta (i2) — nothing changed, so only the presence pass sees it gone.
        jellyfin_plugin.fake_items[:] = [i for i in jellyfin_plugin.fake_items if i["Id"] != "i2"]
        del jellyfin_plugin.fake_details["i2"]

        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["removed"] == 1
        assert not Movie.objects.filter(jellyfin_item_id="i2").exists()
        assert Movie.objects.filter(jellyfin_item_id="i1").exists()

    def test_incremental_recovers_present_but_missing_film(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})  # imports i1 + i2
        # Simulate i2 lost from our DB (e.g. a prior transient failure); it hasn't
        # changed since, so the delta won't return it — only the presence pass will.
        Movie.objects.filter(jellyfin_item_id="i2").delete()
        self._mark_synced(jellyfin_source)

        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["added"] == 1
        assert Movie.objects.filter(jellyfin_item_id="i2").exists()  # recovered

    def test_deep_reprocesses_present_films(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        self._mark_synced(jellyfin_source)
        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {"deep": True})
        assert counts["skipped"] == 0  # deep ignores last_sync and re-crawls everything
        assert counts["updated"] == 2

    def test_apply_removes_orphans(self, jellyfin_plugin, jellyfin_source):
        MovieFactory(title="Old", tmdbid=888, sync_source=jellyfin_source)
        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["removed"] == 1
        assert not Movie.objects.filter(tmdbid=888).exists()

    def test_incremental_relinks_moved_file(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        gamma = Movie.objects.get(tmdbid=601)
        assert gamma.file_path == "/films/gamma.mkv"

        self._mark_synced(jellyfin_source)  # unchanged since → delta empty, presence pass heals
        jellyfin_plugin.fake_items[0]["Path"] = "/movies/gamma.mkv"
        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {})

        assert counts["skipped"] == 2
        gamma.refresh_from_db()
        assert gamma.file_path == "/movies/gamma.mkv"

    def test_apply_cancellation_stops_cleanly(self, jellyfin_plugin):
        ctx = RecordingCtx(cancel_after=1)
        with pytest.raises(SyncCancelled):
            jellyfin_plugin.apply(ctx, "sync", {})
        assert Movie.objects.count() == 0


@pytest.fixture
def trailer_settings(tmp_path, settings):
    settings.MEDIA_ROOT = str(tmp_path)
    trailers = tmp_path / "trailers"
    trailers.mkdir()
    Settings.set("trailers", {"tmdb_api_key": "test-key"})
    return trailers


class TestTrailerServiceDispatch:
    @pytest.mark.parametrize(
        "operation,method",
        [
            ("verify", "verify_existing_trailers"),
            ("library", "fetch_library_trailers"),
            ("ratings", "update_ratings"),
            ("rename", "rename_existing_trailers"),
        ],
    )
    def test_run_operation_dispatches(self, trailer_settings, monkeypatch, operation, method):
        service = TrailerService()
        called = []
        monkeypatch.setattr(service, method, lambda **kw: called.append(operation) or True)
        assert service.run_operation(operation) is True
        assert called == [operation]

    def test_run_operation_passes_upcoming_params(self, trailer_settings, monkeypatch):
        service = TrailerService()
        received = {}

        def fake_upcoming(**kwargs):
            received.update(kwargs)
            return True

        monkeypatch.setattr(service, "fetch_discover_trailers", fake_upcoming)
        service.run_operation("upcoming", {"year_from": 2026, "year_to": 2027, "limit": 5})
        assert received["year_from"] == 2026
        assert received["year_to"] == 2027
        assert received["limit"] == 5

    def test_run_operation_rejects_unknown(self, trailer_settings):
        with pytest.raises(ValueError):
            TrailerService().run_operation("does-not-exist")


class TestTrailerOperations:
    def test_verify_imports_orphans_and_relinks(self, trailer_settings, monkeypatch):
        tmp = trailer_settings
        orphan = tmp / "Orphan Film (2023) [tmdb-901].mp4"
        orphan.write_bytes(b"fake")
        known = TrailerFactory(title="Known", tmdbid=902, file_path=str(tmp / "old-location.mp4"))
        moved = tmp / "Known (2020) [tmdb-902].mp4"
        moved.write_bytes(b"fake")

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

        progress = []
        service._progress = lambda cur, tot, msg: progress.append((cur, tot, msg))

        assert service.verify_existing_trailers() is True

        imported = Trailer.objects.get(tmdbid=901)
        assert imported.title == "Orphan Film"
        assert imported.year == 2023
        assert imported.content_rating == "12A"
        assert imported.director == "Jane Doe"
        assert list(imported.genres.values_list("name", flat=True)) == ["Action"]

        known.refresh_from_db()
        assert known.file_path == "trailers/Known (2020) [tmdb-902].mp4"

        assert service.sync_counts == {"added": 1, "updated": 1, "skipped": 0, "failed": 0}
        assert progress

    def test_upcoming_downloads_and_creates(self, trailer_settings, monkeypatch):
        discovered = [{"id": 903, "title": "New Film", "release_date": "2026-10-01"}]

        class FakeDiscover:
            def discover_movies(self, params):
                return discovered

        details = {
            "title": "New Film",
            "genres": [{"name": "Sci-Fi"}],
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

        monkeypatch.setattr(trailer_service, "Discover", FakeDiscover)
        monkeypatch.setattr(trailer_service.yt_dlp, "YoutubeDL", FakeYDL)

        service = TrailerService()
        monkeypatch.setattr(service, "_get_video_duration", lambda path: 90)
        monkeypatch.setattr(service.tmdb_movie, "details", lambda tmdbid, **kwargs: details)

        assert service.fetch_discover_trailers(year_from=2026, year_to=2026, limit=10) is True

        assert downloads == ["https://www.youtube.com/watch?v=abc123"]
        trailer = Trailer.objects.get(tmdbid=903)
        assert trailer.title == "New Film"
        assert trailer.year == 2026
        assert trailer.month == 10
        assert trailer.duration == 90
        assert trailer.file_path.startswith("trailers/")
        assert list(trailer.genres.values_list("name", flat=True)) == ["Sci-Fi"]

    def test_upcoming_skips_existing(self, trailer_settings, monkeypatch):
        TrailerFactory(tmdbid=904, title="Already Here")
        discovered = [{"id": 904, "title": "Already Here", "release_date": "2026-01-01"}]

        class FakeDiscover:
            def discover_movies(self, params):
                return discovered

        monkeypatch.setattr(trailer_service, "Discover", FakeDiscover)
        service = TrailerService()
        monkeypatch.setattr(
            service.tmdb_movie, "details", lambda tmdbid: pytest.fail("must not hit TMDB for existing trailer")
        )

        assert service.fetch_discover_trailers(year_from=2026, year_to=2026) is True
        assert Trailer.objects.filter(tmdbid=904).count() == 1

    def test_ratings_updates_from_provider(self, trailer_settings, monkeypatch):
        from cinefin.api.ratings import RatingResult

        t = TrailerFactory(title="Unrated Film", content_rating="")

        class FakeProvider:
            display_name = "fake source"

            def lookup(self, title, year=None):
                return RatingResult(system="BBFC", rating="15", matched_title=title, year=year)

        monkeypatch.setattr("cinefin.api.ratings.get_provider", lambda system: FakeProvider())

        assert TrailerService().update_ratings() is True
        t.refresh_from_db()
        assert t.content_rating == "15"
        assert t.certificates == {"BBFC": "15"}
        assert t.rating_lookups == {"BBFC": "matched"}

    def test_ratings_repairs_wrong_scheme_certificates(self, trailer_settings, monkeypatch):
        """A wrong-scheme value in the BBFC slot is re-looked-up and replaced (movies too)."""
        from cinefin.api.ratings import RatingResult

        from .factories import MovieFactory

        movie = MovieFactory(certification="R")
        movie.certificates = {"BBFC": "R"}
        movie.save()

        class FakeProvider:
            display_name = "fake source"

            def lookup(self, title, year=None):
                return RatingResult(system="BBFC", rating="15", matched_title=title, year=year)

        monkeypatch.setattr("cinefin.api.ratings.get_provider", lambda system: FakeProvider())

        assert TrailerService().update_ratings() is True
        movie.refresh_from_db()
        assert movie.certificates["BBFC"] == "15"
        assert movie.certification == "15"

    def test_ratings_normalises_case_without_provider(self, trailer_settings, monkeypatch):
        t = TrailerFactory(title="Lowercase Film", content_rating="pg")
        t.certificates = {"BBFC": "pg"}
        t.save()

        class ExplodingProvider:
            display_name = "must not be called"

            def lookup(self, title, year=None):
                raise AssertionError("case-only mismatches must not hit the network")

        monkeypatch.setattr("cinefin.api.ratings.get_provider", lambda system: ExplodingProvider())

        assert TrailerService().update_ratings() is True
        t.refresh_from_db()
        assert t.certificates["BBFC"] == "PG"
        assert t.content_rating == "PG"

    def test_ratings_scope_limits_targets(self, trailer_settings, monkeypatch):
        from .factories import MovieFactory

        movie = MovieFactory(title="Unrated Movie", certification="")
        trailer = TrailerFactory(title="Unrated Trailer", content_rating="")
        looked = []

        class NoMatchProvider:
            display_name = "fake source"

            def lookup(self, title, year=None):
                looked.append(title)
                return None

        monkeypatch.setattr("cinefin.api.ratings.get_provider", lambda system: NoMatchProvider())

        assert TrailerService().update_ratings(scope="movies") is True
        assert movie.title in looked
        assert trailer.title not in looked

        looked.clear()
        assert TrailerService().update_ratings(scope="trailers") is True
        assert trailer.title in looked
        assert movie.title not in looked

    def test_ratings_marks_unmatched_and_skips_next_run(self, trailer_settings, monkeypatch):
        t = TrailerFactory(title="Obscure Film", content_rating="")
        calls = []

        class NoMatchProvider:
            display_name = "fake source"

            def lookup(self, title, year=None):
                calls.append(title)
                return None

        monkeypatch.setattr("cinefin.api.ratings.get_provider", lambda system: NoMatchProvider())

        assert TrailerService().update_ratings() is True
        t.refresh_from_db()
        assert t.content_rating == ""
        assert t.rating_lookups == {"BBFC": "unmatched"}
        assert TrailerService().update_ratings() is True
        assert len(calls) == 1

    def test_ratings_aborts_when_provider_keeps_failing(self, trailer_settings, monkeypatch):
        """A failing provider must stop early, report failure, and mark nothing."""
        monkeypatch.setattr(trailer_service.time, "sleep", lambda *_: None)
        movies = [MovieFactory(title=f"Film {i}", certification="") for i in range(8)]
        calls = []

        class DownProvider:
            display_name = "down source"

            def lookup(self, title, year=None):
                calls.append(title)
                raise RuntimeError("site unavailable")

        monkeypatch.setattr("cinefin.api.ratings.get_provider", lambda system: DownProvider())

        assert TrailerService().update_ratings(scope="movies") is False
        assert len(calls) == trailer_service.RATING_LOOKUP_ABORT_AFTER
        for m in movies:
            m.refresh_from_db()
            assert (m.rating_lookups or {}).get("BBFC") != "unmatched"

    def test_ratings_update_degrades_without_provider(self, trailer_settings, monkeypatch):
        TrailerFactory(title="Unrated Film", content_rating="")
        monkeypatch.setattr("cinefin.api.ratings.get_provider", lambda system: None)

        logs = []
        svc = TrailerService(log=lambda level, msg: logs.append((level, msg)))
        assert svc.update_ratings() is False
        assert any("provider" in m.lower() for _, m in logs), logs

    def test_cancellation_propagates(self, trailer_settings):
        (trailer_settings / "Some Film (2023) [tmdb-905].mp4").write_bytes(b"fake")

        def cancel():
            raise TrailerCancelled("stop")

        service = TrailerService(check_cancelled=cancel)
        with pytest.raises(TrailerCancelled):
            service.verify_existing_trailers()


class TestTrailerBackgroundJobs:
    def test_job_context_persists_service_output(self, trailer_settings):
        job = Job.trailer.create(operation="verify", state=Job.STATE_RUNNING)
        ctx = JobContext(job)
        service = TrailerService(log=ctx.log, progress=ctx.update_progress, check_cancelled=ctx.check_cancelled)

        assert service.run_operation("verify", {}) is True
        ctx.flush()

        job.refresh_from_db()
        assert any("Verification complete" in entry["message"] for entry in job.log)
        assert job.current == job.total

    def test_job_cancel_raises_job_cancelled(self, trailer_settings):
        (trailer_settings / "Some Film (2023) [tmdb-906].mp4").write_bytes(b"fake")
        job = Job.trailer.create(operation="verify", state=Job.STATE_RUNNING, cancel_requested=True)
        ctx = JobContext(job)
        service = TrailerService(log=ctx.log, progress=ctx.update_progress, check_cancelled=ctx.check_cancelled)

        with pytest.raises(JobCancelled):
            service.run_operation("verify", {})


class TestEnsureAware:
    def test_naive_becomes_local_aware(self):
        from cinefin.api.sync.plugins.common import ensure_aware

        dt = datetime(2026, 4, 5, 21, 38, 27)
        out = ensure_aware(dt)
        assert timezone.is_aware(out)
        assert (out.year, out.hour, out.minute) == (2026, 21, 38)

    def test_naive_assume_utc(self):
        from datetime import UTC

        from cinefin.api.sync.plugins.common import ensure_aware

        out = ensure_aware(datetime(2026, 4, 5, 21, 38, 27), assume_utc=True)
        assert timezone.is_aware(out)
        assert out.utcoffset().total_seconds() == 0
        assert out.astimezone(UTC).hour == 21

    def test_aware_passthrough_and_none(self):
        from cinefin.api.sync.plugins.common import ensure_aware

        aware = timezone.now()
        assert ensure_aware(aware) is aware
        assert ensure_aware(None) is None

    def test_jellyfin_parse_date_offsetless_is_aware(self):
        out = JellyfinSource._parse_date("2026-04-05T21:38:27.1234567")
        assert out is not None and timezone.is_aware(out)
        assert out.utcoffset().total_seconds() == 0

    def test_plex_apply_stores_aware_date_added(self, plex_plugin, plex_source):
        naive = datetime(2026, 4, 5, 21, 38, 27)
        for m in plex_plugin.fake_movies:
            m.addedAt = naive
        plex_plugin.apply(RecordingCtx(), "sync", {})
        movie = Movie.objects.get(tmdbid=501)
        assert timezone.is_aware(movie.date_added)


class TestMediaTreeWritability:
    def test_unwritable_subdir_logged_at_boot(self, tmp_path, settings, caplog):
        import logging
        import os

        if os.geteuid() == 0:
            pytest.skip("os.access is always true as root")

        from cinefin.api.apps import ApiConfig

        settings.CINEFIN_DISABLE_BACKGROUND_WORKERS = False
        settings.MEDIA_ROOT = str(tmp_path)
        (tmp_path / "screenshots").mkdir()
        (tmp_path / "screenshots").chmod(0o555)
        try:
            with caplog.at_level(logging.ERROR):
                ApiConfig._ensure_media_tree()
        finally:
            (tmp_path / "screenshots").chmod(0o755)

        assert any("NOT writable" in r.message and "chown" in r.message for r in caplog.records)

    def test_all_writable_no_error(self, tmp_path, settings, caplog):
        import logging

        from cinefin.api.apps import ApiConfig

        settings.CINEFIN_DISABLE_BACKGROUND_WORKERS = False
        settings.MEDIA_ROOT = str(tmp_path)
        with caplog.at_level(logging.ERROR):
            ApiConfig._ensure_media_tree()
        assert not any("NOT writable" in r.message for r in caplog.records)


class TestPathMappings:
    def test_longest_prefix_wins(self, plex_source):
        from cinefin.api.sync.plugins.common import apply_path_mappings

        plex_source.path_mappings = [
            {"from": "/data", "to": "/mnt"},
            {"from": "/data/movies", "to": "/mnt/films"},
        ]
        assert apply_path_mappings("/data/movies/a.mkv", plex_source) == "/mnt/films/a.mkv"
        assert apply_path_mappings("/data/other/b.mkv", plex_source) == "/mnt/other/b.mkv"
        assert apply_path_mappings("/elsewhere/c.mkv", plex_source) == "/elsewhere/c.mkv"

    def test_plex_sync_applies_mappings(self, plex_plugin, plex_source):
        plex_source.path_mappings = [{"from": "/films", "to": "/mnt/movies"}]
        plex_source.save()
        plex_plugin.apply(RecordingCtx(), "sync", {})
        assert Movie.objects.get(tmdbid=501).file_path == "/mnt/movies/Alpha.mkv"


class TestUnmatchedReporting:
    def test_films_without_tmdb_are_imported_and_reported(self, plex_plugin):
        stray = fake_plex_movie("Stray", 599)
        stray.guids = []
        plex_plugin.fake_movies.append(stray)

        counts = plex_plugin.apply(RecordingCtx(), "sync", {})

        assert counts["unmatched"] == 1
        assert counts["changes"]["unmatched"] == ["Stray (2023)"]
        stray_row = Movie.objects.get(title="Stray")
        assert stray_row.tmdbid == 0
        assert stray_row.plex_rating_key == "10599"
        assert stray_row.year == 2023
        assert sorted(stray_row.genres.values_list("name", flat=True)) == ["Action", "Drama"]
        assert counts["added"] == 3
        assert counts["failed"] == 0

    def test_two_no_tmdb_films_do_not_collide(self, plex_plugin):
        s1, s2 = plex_plugin.fake_movies
        s1.title, s2.title = "StrayOne", "StrayTwo"
        s1.guids = []
        s2.guids = []

        counts = plex_plugin.apply(RecordingCtx(), "sync", {})

        assert counts["added"] == 2
        assert counts["unmatched"] == 2
        no_tmdb = Movie.objects.filter(tmdbid=0)
        assert no_tmdb.count() == 2
        assert set(no_tmdb.values_list("title", flat=True)) == {"StrayOne", "StrayTwo"}

        counts = plex_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["skipped"] == 2
        assert Movie.objects.filter(tmdbid=0).count() == 2

    def test_no_tmdb_films_survive_orphan_pruning(self, plex_plugin):
        stray = fake_plex_movie("Stray", 599)
        stray.guids = []
        plex_plugin.fake_movies.append(stray)
        plex_plugin.apply(RecordingCtx(), "sync", {})

        counts = plex_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["removed"] == 0
        assert Movie.objects.filter(title="Stray").exists()

    def test_jellyfin_films_without_tmdb_are_imported(self, jellyfin_plugin, jellyfin_source):
        for item in jellyfin_plugin.fake_items:
            item["ProviderIds"] = {}

        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {})

        assert counts["unmatched"] == 2
        assert counts["added"] == 2
        no_tmdb = Movie.objects.filter(tmdbid=0)
        assert no_tmdb.count() == 2
        assert set(no_tmdb.values_list("jellyfin_item_id", flat=True)) == {"i1", "i2"}

        jellyfin_source.last_sync = datetime(2024, 3, 6, tzinfo=UTC)
        jellyfin_source.save(update_fields=["last_sync"])
        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["skipped"] == 2
        assert Movie.objects.filter(tmdbid=0).count() == 2


class TestJellyfinIncremental:
    def _mark_synced(self, source):
        source.last_sync = datetime(2024, 3, 6, tzinfo=UTC)  # after the fixtures' DateLastSaved
        source.save(update_fields=["last_sync"])

    def test_second_run_skips_unchanged(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        self._mark_synced(jellyfin_source)
        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        assert counts["skipped"] == 2
        assert counts["added"] == 0 and counts["updated"] == 0

    def test_deep_sync_reprocesses(self, jellyfin_plugin, jellyfin_source):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        self._mark_synced(jellyfin_source)
        counts = jellyfin_plugin.apply(RecordingCtx(), "sync", {"deep": True})
        assert counts["updated"] == 2
        assert counts["skipped"] == 0

    def test_stamp_stored(self, jellyfin_plugin):
        jellyfin_plugin.apply(RecordingCtx(), "sync", {})
        movie = Movie.objects.get(tmdbid=601)
        assert movie.remote_updated_at is not None
        assert movie.jellyfin_item_id == "i1"
