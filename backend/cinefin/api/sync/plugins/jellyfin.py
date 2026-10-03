"""Jellyfin source plugin — streams movies from the API as they're fetched."""

import logging
import re
from collections.abc import Generator
from datetime import datetime, timedelta
from typing import Any

import requests
from django.db import transaction

from ...utils.jellyfin import auth_header as jellyfin_auth_header
from ..base import SyncCancelled, SyncContext, SyncSourcePlugin
from ..registry import register
from .common import (
    RunChanges,
    apply_path_mappings,
    apply_video_attrs,
    ensure_aware,
    find_movie,
    prune_orphans,
    relink,
    replace_tracks,
    resolution_rank,
    resolve_tmdb_via_imdb,
    set_genres,
    sync_poster_key,
)

logger = logging.getLogger("cinefin.sync")

# Full fields for the items we actually ingest.
_LIST_FIELDS = "ProviderIds,People,Genres,Overview,DateCreated,DateLastSaved,ImageTags,Path"
# Just enough to prune orphans and self-heal art/paths, no per-item detail fetch.
# ImageTags is NOT an ItemFields value — it rides on the default EnableImages, so it
# must not be suppressed on this listing or the art-key self-heal wipes poster keys.
_PRESENCE_FIELDS = "ProviderIds,Path"
# Cushion on the incremental "changed since last sync" window, for clock skew.
_INCREMENTAL_BUFFER = timedelta(hours=1)


@register
class JellyfinSource(SyncSourcePlugin):
    type_id = "jellyfin"
    label = "Jellyfin"

    def __init__(self, source):
        super().__init__(source)
        self.base_url = source.url.rstrip("/")
        self.headers = {"Authorization": jellyfin_auth_header(source.token), "Accept": "application/json"}
        self.user_id: str | None = None

    def _get(self, endpoint: str, params: dict | None = None, timeout: int = 30) -> dict | None:
        resp = requests.get(f"{self.base_url}{endpoint}", headers=self.headers, params=params, timeout=timeout)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def _connect(self, ctx: SyncContext | None = None) -> bool:
        def log(level: str, msg: str) -> None:
            if ctx is not None:
                ctx.log(level, msg)
            else:
                getattr(logger, level, logger.info)(msg)

        try:
            log("info", f"Connecting to {self.base_url}")
            info = self._get("/System/Info")
            log("info", f"Connected: {info.get('ServerName')} v{info.get('Version')}")

            users = self._get("/Users") or []
            if users:
                user = next((u for u in users if u.get("Policy", {}).get("IsAdministrator")), users[0])
                self.user_id = user["Id"]
                log("info", f"Using user: {user.get('Name')}")
            return True
        except Exception as e:  # noqa: BLE001
            log("error", f"Connection failed: {e}")
            return False

    def test_connection(self) -> tuple[bool, str]:
        ok = self._connect()
        return ok, "Connection successful" if ok else "Connection failed"

    def get_libraries(self) -> list[str]:
        try:
            if not self.user_id and not self._connect():
                return []
            folders = self._get("/Library/MediaFolders") or {}
            return [f["Name"] for f in folders.get("Items", []) if f.get("CollectionType") == "movies"]
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to get Jellyfin libraries: %s", e)
            return []

    def _configured_library_ids(self) -> dict[str, str]:
        libraries = self.source.get_libraries_list()
        folders = self._get("/Library/MediaFolders") or {}
        return {
            f["Name"]: f["Id"]
            for f in folders.get("Items", [])
            if f.get("CollectionType") == "movies" and f["Name"] in libraries
        }

    def _movies(self, lib_id: str, **params) -> dict:
        query = {"userId": self.user_id, "ParentId": lib_id, "IncludeItemTypes": "Movie", "Recursive": True}
        return self._get("/Items", {**query, **params}, timeout=60) or {}

    def _count_movies(self, ctx: SyncContext, library_ids: dict[str, str]) -> int:
        """Total movie count across the libraries (the progress denominator); Limit=1 still reports the total."""
        total = 0
        for lib_id in library_ids.values():
            ctx.check_cancelled()
            total += self._movies(lib_id, Limit=1).get("TotalRecordCount", 0)
        return total

    def _page(self, ctx: SyncContext, lib_id: str, batch_size: int, **params) -> Generator[dict]:
        start = 0
        while True:
            ctx.check_cancelled()
            result = self._movies(lib_id, StartIndex=start, Limit=batch_size, **params)
            items = result.get("Items", [])
            if not items:
                break
            yield from items
            start += len(items)
            if start >= result.get("TotalRecordCount", 0):
                break

    def _stream_movies(
        self, ctx: SyncContext, library_ids: dict[str, str], min_date_last_saved: datetime | None = None
    ) -> Generator[dict]:
        """Full-field movie items; with min_date_last_saved, only films saved since then (the incremental delta)."""
        extra = {"MinDateLastSaved": min_date_last_saved.isoformat()} if min_date_last_saved is not None else {}
        for lib_name, lib_id in library_ids.items():
            ctx.check_cancelled()
            ctx.info(f"Fetching from {lib_name}...")
            yield from self._page(ctx, lib_id, 100, Fields=_LIST_FIELDS, **extra)

    def _list_present(self, ctx: SyncContext, library_ids: dict[str, str]) -> Generator[dict]:
        """Light listing of every current movie (id + art tag + path), in larger batches since rows are tiny."""
        for lib_id in library_ids.values():
            yield from self._page(ctx, lib_id, 500, Fields=_PRESENCE_FIELDS)

    def _fetch_items_by_ids(self, ctx: SyncContext, item_ids: list[str]) -> list[dict]:
        """Full-field items for specific ids: films on the server but missing here, which the delta won't return."""
        out: list[dict] = []
        for i in range(0, len(item_ids), 100):
            ctx.check_cancelled()
            chunk = item_ids[i : i + 100]
            result = self._get("/Items", {"userId": self.user_id, "Ids": ",".join(chunk), "Fields": _LIST_FIELDS}) or {}
            out.extend(result.get("Items", []))
        return out

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            date_str = re.sub(r"(\.\d{6})\d+", r"\1", date_str.replace("Z", "+00:00"))
            # Some fields (e.g. MediaSource.DateModified) omit the offset; Jellyfin reports in UTC.
            return ensure_aware(datetime.fromisoformat(date_str), assume_utc=True)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _get_resolution(video_stream: dict) -> str:
        display = video_stream.get("DisplayTitle", "").upper()
        for res in ["2160p", "4K", "1080p", "720p", "480p"]:
            if res.upper() in display:
                return "4K" if res in ["2160p", "4K"] else res
        if res_field := video_stream.get("Resolution"):
            return res_field
        height = video_stream.get("Height", 0)
        for floor, label in ((2160, "4K"), (1080, "1080p"), (720, "720p")):
            if height >= floor:
                return label
        return f"{height}p" if height > 0 else "NA"

    @staticmethod
    def _extract_tmdb_id(movie_data: dict) -> int:
        provider_ids = movie_data.get("ProviderIds", {})
        try:
            tmdb_id = int(provider_ids.get("Tmdb", 0))
        except (ValueError, TypeError):
            tmdb_id = 0
        if not tmdb_id and (imdb_id := provider_ids.get("Imdb")):
            tmdb_id = resolve_tmdb_via_imdb(imdb_id) or 0
        return tmdb_id

    @staticmethod
    def _pick_media_source(media_sources: list[dict]) -> dict:
        """Highest-resolution version when the film has several."""

        def rank(source: dict) -> int:
            streams = source.get("MediaStreams", [])
            video = next((st for st in streams if st.get("Type") == "Video"), {})
            return resolution_rank(video.get("DisplayTitle") or str(video.get("Height", "")))

        return max(media_sources, key=rank)

    def _process_movie(self, ctx: SyncContext, movie_data: dict, tmdb_id: int, remote_updated) -> str | None:
        """Upsert one movie; returns "added"/"updated" or None on failure."""
        from cinefin.api.models import Movie
        from cinefin.api.ratings.service import file_source_certificate

        title = movie_data.get("Name", "Unknown")
        try:
            # Per-item detail (MediaSources/MediaStreams) via the version-portable /Items/{id} route; userId
            # supplies the user context the removed /Users/{id}/Items route carried.
            item_id = movie_data["Id"]
            detail = self._get(f"/Items/{item_id}", {"userId": self.user_id}) or {}
            media_sources = detail.get("MediaSources", [])

            if not media_sources:
                ctx.warn(f"No media sources: {title}")
                return None

            source = self._pick_media_source(media_sources)
            existing = find_movie(self.source, tmdb_id, jellyfin_item_id=item_id)
            created = existing is None
            movie = existing or Movie()
            streams = source.get("MediaStreams", [])
            video_streams = [s for s in streams if s.get("Type") == "Video"]
            directors = [p for p in movie_data.get("People", []) if p.get("Type") == "Director"]
            ticks = movie_data.get("RunTimeTicks", 0)

            with transaction.atomic():
                movie.title = title
                movie.tmdbid = tmdb_id
                movie.year = movie_data.get("ProductionYear", 0)
                movie.file_path = apply_path_mappings(source.get("Path", ""), self.source)
                movie.file_size = source.get("Size", 0)
                movie.director = directors[0].get("Name", "") if directors else ""
                movie.description = movie_data.get("Overview", "")
                movie.runtime = ticks / 600000000
                movie.duration = ticks / 10000000
                # Filed under the server's own scheme, never clobbering provider-fetched values.
                file_source_certificate(movie, movie_data.get("OfficialRating", ""))
                movie.resolution = self._get_resolution(video_streams[0]) if video_streams else "NA"
                # Jellyfin gives bitrate already in bits/sec.
                if video_streams:
                    vs = video_streams[0]
                    apply_video_attrs(
                        movie,
                        codec=vs.get("Codec", ""),
                        width=vs.get("Width", 0),
                        height=vs.get("Height", 0),
                        framerate=vs.get("RealFrameRate") or vs.get("AverageFrameRate") or 0,
                        bitrate=vs.get("BitRate", 0),
                    )
                movie.sync_source = self.source
                movie.jellyfin_item_id = item_id
                movie.remote_updated_at = remote_updated

                # DateModified = file mtime; DateCreated = when added to library.
                source_date = source.get("DateModified")
                item_date = detail.get("DateCreated") or movie_data.get("DateCreated")
                ctx.log("debug", f"{title} dates - Source.DateModified: {source_date}, Item.DateCreated: {item_date}")

                if date := self._parse_date(source_date or item_date):
                    movie.date_added = date
                movie.poster_key = movie_data.get("ImageTags", {}).get("Primary") or ""
                movie.save()
                set_genres(movie, movie_data.get("Genres", []))

            replace_tracks(
                movie,
                audio=[
                    {
                        "title": s.get("DisplayTitle", ""),
                        "language": s.get("Language", ""),
                        "codec": s.get("Codec", ""),
                        "channels": s.get("Channels", 0),
                    }
                    for s in streams
                    if s.get("Type") == "Audio"
                ],
                subtitles=[
                    {
                        "language": s.get("Language", ""),
                        "forced": s.get("IsForced", False),
                        "sdh": s.get("IsHearingImpaired", False),
                    }
                    for s in streams
                    if s.get("Type") == "Subtitle"
                ],
            )

            suffix = " (no TMDB match)" if not tmdb_id else ""
            ctx.info(f"{'Added' if created else 'Updated'}: {title}{suffix}")
            return "added" if created else "updated"

        except Exception as e:  # noqa: BLE001
            ctx.error(f"Failed {title}: {e}")
            return None

    def _ingest(self, ctx: SyncContext, movie_data: dict, changes: RunChanges, seen_tmdb_ids: set[int]) -> bool:
        """Process one full-field item, recording the outcome on ``changes``; True on failure (never raises)."""
        title = movie_data.get("Name", "Unknown")
        remote_updated = self._parse_date(movie_data.get("DateLastSaved") or movie_data.get("DateCreated", ""))
        try:
            tmdb_id = self._extract_tmdb_id(movie_data)
            # No TMDB match: import anyway keyed on the item id; a later fix + re-sync fills in the tmdbid.
            if not tmdb_id:
                changes.record("unmatched", f"{title} ({movie_data.get('ProductionYear', '?')})")
            else:
                seen_tmdb_ids.add(tmdb_id)
            outcome = self._process_movie(ctx, movie_data, tmdb_id, remote_updated)
            if outcome is None:
                return True
            changes.record(outcome, title)
            return False
        except SyncCancelled:
            raise
        except Exception as e:  # noqa: BLE001
            ctx.error(f"Skipped {title}: {e}")
            return True

    def apply(self, ctx: SyncContext, operation: str, params: dict[str, Any]) -> dict[str, int]:
        from cinefin.api.models import Movie

        deep = bool(params.get("deep"))
        ctx.info(f"Connecting to {self.source.name}…")
        if not self._connect(ctx):
            raise RuntimeError("Failed to connect to source")
        ctx.check_cancelled()

        try:
            lib_ids = self._configured_library_ids()
            if not lib_ids:
                ctx.error("No valid libraries found")
                raise RuntimeError("No valid libraries found")

            # Incremental delta: ask the server (MinDateLastSaved) for only the films saved since our last sync,
            # which also catches metadata/file changes. The first run and deep syncs crawl everything.
            threshold = None if deep or not self.source.last_sync else self.source.last_sync - _INCREMENTAL_BUFFER
            delta = threshold is not None
            mode = "deep sync" if deep else "incremental" if delta else "full sync"
            ctx.info(f"Syncing: {', '.join(lib_ids.keys())} ({mode})")

            # Full-library total: the progress denominator (and it primes the connection).
            total = self._count_movies(ctx, lib_ids)

            changes = RunChanges()
            seen_item_ids: set[str] = set()
            seen_tmdb_ids: set[int] = set()
            processed_ids: set[str] = set()
            processed = unchanged = failed = 0

            # 1) Ingest the changed set (delta) or the whole library (full/deep).
            for movie_data in self._stream_movies(ctx, lib_ids, min_date_last_saved=threshold):
                ctx.check_cancelled()
                processed += 1
                item_id = movie_data.get("Id", "")
                seen_item_ids.add(item_id)
                processed_ids.add(item_id)
                if delta:
                    ctx.info(f"Changed: {movie_data.get('Name', 'Unknown')}")
                else:
                    ctx.progress(processed, total, item=f"Processing: {movie_data.get('Name', 'Unknown')}")
                if self._ingest(ctx, movie_data, changes, seen_tmdb_ids):
                    failed += 1

            # 2) Incremental only: the delta skipped unchanged films, so enumerate all current ids cheaply — for
            # orphan pruning, poster/path self-heal, and to recover any film on the server but missing here (e.g.
            # one that failed a prior run and hasn't changed since).
            if delta:
                checked = 0
                missing_ids: list[str] = []
                for row in self._list_present(ctx, lib_ids):
                    ctx.check_cancelled()
                    checked += 1
                    item_id = row.get("Id", "")
                    seen_item_ids.add(item_id)
                    if item_id in processed_ids:
                        continue  # already ingested in the delta pass
                    existing = Movie.objects.filter(sync_source=self.source, jellyfin_item_id=item_id).first()
                    if existing:
                        unchanged += 1
                        if existing.tmdbid:
                            seen_tmdb_ids.add(existing.tmdbid)
                        # Art key + path ride along so posters/moved files self-heal without a deep sync. An
                        # absent ImageTags means "not reported", not "no poster", so never wipe on it.
                        if "ImageTags" in row:
                            sync_poster_key(existing, row["ImageTags"].get("Primary") or "")
                        relink(ctx, existing, apply_path_mappings(row.get("Path", ""), self.source), existing.title)
                    else:
                        missing_ids.append(item_id)
                    ctx.progress(checked, total, item="Checking library…")

                if missing_ids:
                    ctx.info(f"Recovering {len(missing_ids)} film(s) present on the server but not yet imported")
                    for movie_data in self._fetch_items_by_ids(ctx, missing_ids):
                        ctx.check_cancelled()
                        if self._ingest(ctx, movie_data, changes, seen_tmdb_ids):
                            failed += 1

            # An incomplete listing raises out of _stream_movies / _list_present before reaching here.
            ctx.check_cancelled()
            prune_orphans(
                ctx,
                self.source,
                changes,
                "jellyfin_item_id",
                seen_item_ids,
                seen_tmdb_ids,
                failed,
                removing="Removing: ",
            )
            return changes.summary(ctx, "Done", unchanged, failed)

        except SyncCancelled:
            raise
        except Exception as e:
            ctx.error(f"Sync failed: {e}")
            raise
