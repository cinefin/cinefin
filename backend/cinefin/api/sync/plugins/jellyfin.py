"""Jellyfin source plugin — streams movies from the API as they're fetched."""

from __future__ import annotations

import logging
import re
from collections.abc import Generator
from datetime import datetime
from typing import Any

import requests
from django.db import transaction

from ..base import SyncCancelled, SyncContext, SyncSourcePlugin
from ..registry import register
from .common import (
    RunChanges,
    apply_path_mappings,
    apply_video_attrs,
    ensure_aware,
    replace_tracks,
    resolution_rank,
    resolve_tmdb_via_imdb,
    sync_poster_key,
)

logger = logging.getLogger("cinefin.sync")


@register
class JellyfinSource(SyncSourcePlugin):
    type_id = "jellyfin"
    label = "Jellyfin"
    operations = ["sync"]
    needs_connection = True

    def __init__(self, source):
        super().__init__(source)
        self.base_url = source.url.rstrip("/")
        self.headers = {"X-Emby-Token": source.token, "Accept": "application/json"}
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

    def _connect_for_job(self, ctx: SyncContext) -> None:
        ctx.info(f"Connecting to {self.source.name}…")
        if not self._connect(ctx):
            raise RuntimeError("Failed to connect to source")

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

    def _count_movies(self, ctx: SyncContext, library_ids: dict[str, str]) -> int:
        """Total movie count across the configured libraries — the denominator for
        progress. One cheap request per library (Limit=1 returns the full
        TotalRecordCount without listing everything)."""
        total = 0
        for lib_id in library_ids.values():
            ctx.check_cancelled()
            result = (
                self._get(
                    f"/Users/{self.user_id}/Items",
                    {"ParentId": lib_id, "IncludeItemTypes": "Movie", "Recursive": True, "Limit": 1},
                    timeout=60,
                )
                or {}
            )
            total += result.get("TotalRecordCount", 0)
        return total

    def _stream_movies(self, ctx: SyncContext, library_ids: dict[str, str]) -> Generator[dict]:
        for lib_name, lib_id in library_ids.items():
            ctx.check_cancelled()
            ctx.info(f"Fetching from {lib_name}...")

            start, batch_size = 0, 100
            while True:
                ctx.check_cancelled()
                params = {
                    "ParentId": lib_id,
                    "IncludeItemTypes": "Movie",
                    "Recursive": True,
                    "Fields": "ProviderIds,People,Genres,Overview,DateCreated,DateLastSaved,ImageTags,Path",
                    "StartIndex": start,
                    "Limit": batch_size,
                }
                result = self._get(f"/Users/{self.user_id}/Items", params, timeout=60) or {}
                items = result.get("Items", [])
                total = result.get("TotalRecordCount", 0)

                if not items:
                    break

                yield from items

                start += len(items)
                if start >= total:
                    break

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        if not date_str:
            return None
        try:
            date_str = date_str.replace("Z", "+00:00")
            date_str = re.sub(r"(\.\d{6})\d+", r"\1", date_str)
            # Some fields (e.g. MediaSource.DateModified) omit the offset;
            # Jellyfin reports in UTC, so assume it for the naive case.
            return ensure_aware(datetime.fromisoformat(date_str), assume_utc=True)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _get_resolution(video_stream: dict) -> str:
        display = video_stream.get("DisplayTitle", "")

        for res in ["2160p", "4K", "1080p", "720p", "480p"]:
            if res in display or res.upper() in display.upper():
                return "4K" if res in ["2160p", "4K"] else res

        if res_field := video_stream.get("Resolution"):
            return res_field

        height = video_stream.get("Height", 0)
        if height >= 2160:
            return "4K"
        if height >= 1080:
            return "1080p"
        if height >= 720:
            return "720p"
        if height > 0:
            return f"{height}p"
        return "NA"

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
        """Upsert one movie; returns "added"/"updated" or None on failure.

        Identity: TMDB-matched films dedup on ``tmdbid``; unmatched (``tmdb_id == 0``)
        dedup on the server item id scoped to this source, else a shared ``tmdbid=0``
        would collapse every unmatched film into one row.
        """
        from cinefin.api.models import Genre, Movie
        from cinefin.api.ratings.service import file_source_certificate

        title = movie_data.get("Name", "Unknown")
        try:
            # Detail fetch must use the user endpoint for full media info.
            item_id = movie_data["Id"]
            detail = self._get(f"/Users/{self.user_id}/Items/{item_id}") or {}
            media_sources = detail.get("MediaSources", [])

            if not media_sources:
                ctx.warn(f"No media sources: {title}")
                return None

            source = self._pick_media_source(media_sources)
            file_size = source.get("Size", 0)

            if tmdb_id:
                existing = Movie.objects.filter(tmdbid=tmdb_id).first()
            else:
                existing = Movie.objects.filter(sync_source=self.source, jellyfin_item_id=item_id).first()
            created = existing is None
            movie = existing or Movie()
            streams = source.get("MediaStreams", [])
            video_streams = [s for s in streams if s.get("Type") == "Video"]

            director = ""
            if directors := [p for p in movie_data.get("People", []) if p.get("Type") == "Director"]:
                director = directors[0].get("Name", "")

            ticks = movie_data.get("RunTimeTicks", 0)

            with transaction.atomic():
                movie.title = title
                movie.tmdbid = tmdb_id
                movie.year = movie_data.get("ProductionYear", 0)
                movie.file_path = apply_path_mappings(source.get("Path", ""), self.source)
                movie.file_size = file_size
                movie.director = director
                movie.description = movie_data.get("Overview", "")
                movie.runtime = ticks / 600000000
                movie.duration = ticks / 10000000
                # File the server's certificate under its own scheme, never
                # clobbering provider-fetched values with wrong-scheme ones.
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
                movie.jellyfin_item_id = item_id  # Store for streaming URL generation
                movie.remote_updated_at = remote_updated

                # DateModified = file mtime; DateCreated = when added to library.
                source_date = source.get("DateModified")
                item_date = detail.get("DateCreated") or movie_data.get("DateCreated")
                ctx.log("debug", f"{title} dates - Source.DateModified: {source_date}, Item.DateCreated: {item_date}")

                file_date = source_date or item_date
                if date := self._parse_date(file_date):
                    movie.date_added = date

                movie.poster_key = movie_data.get("ImageTags", {}).get("Primary") or ""

                movie.save()

                movie.genres.clear()
                for genre_name in movie_data.get("Genres", []):
                    genre, _ = Genre.objects.get_or_create(name=genre_name)
                    movie.genres.add(genre)

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

            outcome = "added" if created else "updated"
            suffix = " (no TMDB match)" if not tmdb_id else ""
            ctx.info(f"{'Added' if created else 'Updated'}: {title}{suffix}")
            return outcome

        except Exception as e:  # noqa: BLE001
            ctx.error(f"Failed {title}: {e}")
            return None

    def apply(self, ctx: SyncContext, operation: str, params: dict[str, Any]) -> dict[str, int]:
        from django.db.models import Q

        from cinefin.api.models import Movie

        deep = bool(params.get("deep"))
        self._connect_for_job(ctx)
        ctx.check_cancelled()

        try:
            lib_ids = self._configured_library_ids()
            if not lib_ids:
                ctx.error("No valid libraries found")
                raise RuntimeError("No valid libraries found")

            ctx.info(f"Syncing: {', '.join(lib_ids.keys())}{' (deep sync)' if deep else ''}")

            # The stream is paginated, so learn the total up front for real progress.
            total = self._count_movies(ctx, lib_ids)

            changes = RunChanges()
            seen_item_ids: set[str] = set()
            seen_tmdb_ids: set[int] = set()
            processed = 0
            skipped = 0
            failed = 0

            for movie_data in self._stream_movies(ctx, lib_ids):
                ctx.check_cancelled()
                processed += 1
                title = movie_data.get("Name", "Unknown")
                item_id = movie_data.get("Id", "")
                seen_item_ids.add(item_id)
                # Jellyfin's list responses always null DateLastSaved (it's only
                # populated on the item detail), so there is no cheap per-item
                # "modified" stamp to diff. Store DateCreated as the stamp for the
                # record; the skip below keys on presence, not on it.
                remote_updated = self._parse_date(movie_data.get("DateLastSaved") or movie_data.get("DateCreated", ""))

                # Incremental skip before the detail fetch: any film we already
                # have is skipped outright — the listing offers no reliable change
                # signal, so a fast sync means present ⇒ skip. Full re-scan (deep)
                # reprocesses everything to pull in metadata and file changes.
                existing = Movie.objects.filter(sync_source=self.source, jellyfin_item_id=item_id).first()
                if existing:
                    if existing.tmdbid:
                        seen_tmdb_ids.add(existing.tmdbid)
                    if not deep:
                        skipped += 1
                        # Art key rides along in the listing → posters self-heal without a deep sync.
                        sync_poster_key(existing, movie_data.get("ImageTags", {}).get("Primary") or "")
                        # Path rides along too, so heal a stale path even on a skip.
                        new_path = apply_path_mappings(movie_data.get("Path", ""), self.source)
                        if new_path and new_path != existing.file_path:
                            existing.file_path = new_path
                            existing.save(update_fields=["file_path"])
                            ctx.info(f"Relinked moved file: {title}")
                        # Advance the counter so a long unchanged tail doesn't freeze progress.
                        ctx.progress(processed, total, item=f"Unchanged: {title}")
                        continue

                ctx.progress(processed, total, item=f"Processing: {title}")

                # Isolate each movie: one failure must not abort the whole sync.
                try:
                    tmdb_id = self._extract_tmdb_id(movie_data)
                    # No TMDB match: import anyway keyed on the item id (tmdbid stays 0);
                    # a later agent fix + re-sync fills in the tmdbid.
                    if not tmdb_id:
                        changes.record("unmatched", f"{title} ({movie_data.get('ProductionYear', '?')})")
                    else:
                        seen_tmdb_ids.add(tmdb_id)

                    outcome = self._process_movie(ctx, movie_data, tmdb_id, remote_updated)
                    if outcome is None:
                        failed += 1
                    else:
                        changes.record(outcome, title)
                except SyncCancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    ctx.error(f"Skipped {title}: {e}")
                    continue

            # Prune orphans, scoped to THIS source. Refuse after an empty crawl
            # (guards against mass-deletion on transient failure; an incomplete
            # listing raises out of _stream_movies before reaching here). Rows carry
            # the item id last seen under; legacy rows fall back to tmdbid.
            # seen_item_ids is built from the LISTING (pre-processing), so a film that
            # failed to process is still "present" and can't become a false orphan.
            ctx.check_cancelled()
            if not seen_item_ids:
                ctx.warn("Skipping orphan cleanup: no movies found (refusing to mass-delete)")
            else:
                if failed:
                    ctx.info(f"{failed} film(s) failed to process; pruning only films absent from the server")
                orphans = Movie.objects.filter(sync_source=self.source).filter(
                    Q(jellyfin_item_id__gt="") & ~Q(jellyfin_item_id__in=seen_item_ids)
                    | Q(jellyfin_item_id="") & ~Q(tmdbid__in=seen_tmdb_ids)
                )
                for title in orphans.values_list("title", flat=True):
                    changes.record("removed", title)
                    ctx.info(f"Removing: {title}")
                orphans.delete()

            counts = changes.counts
            if counts["unmatched"]:
                ctx.info(f"Imported {counts['unmatched']} film(s) with no TMDB match")
            ctx.info(
                f"Done: {counts['added']} added, {counts['updated']} updated, {skipped} unchanged, "
                f"{counts['removed']} removed, {counts['unmatched']} imported without a TMDB id, {failed} failed"
            )
            return {
                "added": counts["added"],
                "updated": counts["updated"],
                "skipped": skipped,
                "removed": counts["removed"],
                "unmatched": counts["unmatched"],
                "failed": failed,
                "changes": changes.as_dict(),
            }

        except SyncCancelled:
            raise
        except Exception as e:
            ctx.error(f"Sync failed: {e}")
            raise
