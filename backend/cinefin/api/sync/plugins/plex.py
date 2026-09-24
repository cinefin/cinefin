"""Plex source plugin — crawls Plex movie libraries into the local Movie table."""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction
from plexapi.exceptions import NotFound, Unauthorized
from plexapi.server import PlexServer

from ..base import SyncCancelled, SyncContext, SyncSourcePlugin
from ..registry import register
from .common import (
    VIDEO_ATTR_FIELDS,
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
class PlexSource(SyncSourcePlugin):
    type_id = "plex"
    label = "Plex Media Server"
    operations = ["sync"]
    needs_connection = True

    def __init__(self, source):
        super().__init__(source)
        self.plex: PlexServer | None = None

    def _connect(self) -> PlexServer:
        if self.plex is None:
            self.plex = PlexServer(self.source.url, self.source.token)
        return self.plex

    def test_connection(self) -> tuple[bool, str]:
        try:
            self._connect()
            return True, "Connection successful"
        except Unauthorized:
            return False, "Invalid Plex token - authentication failed"
        except Exception as e:  # noqa: BLE001
            return False, f"Connection failed: {e}"

    def _connect_for_job(self, ctx: SyncContext) -> PlexServer:
        ctx.info(f"Connecting to {self.source.name}…")
        try:
            plex = self._connect()
        except Unauthorized as e:
            ctx.error("Invalid Plex token - authentication failed")
            raise RuntimeError("Failed to connect to source") from e
        except Exception as e:  # noqa: BLE001
            ctx.error(f"Connection failed: {e}")
            raise RuntimeError("Failed to connect to source") from e
        ctx.info(f"Successfully connected to Plex server at {self.source.url}")
        return plex

    def get_libraries(self) -> list[str]:
        try:
            plex = self._connect()
            return [s.title for s in plex.library.sections() if s.type == "movie"]
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to get Plex libraries: %s", e)
            return []

    @staticmethod
    def _get_tmdb_id(plex_movie) -> int | None:
        imdb_id = None
        for guid in plex_movie.guids:
            if "tmdb://" in guid.id:
                return int(guid.id.replace("tmdb://", ""))
            if "imdb://" in guid.id:
                imdb_id = guid.id.replace("imdb://", "")
        if imdb_id:
            return resolve_tmdb_via_imdb(imdb_id)
        return None

    def _process_movie(self, ctx: SyncContext, plex_movie, tmdb_id: int) -> str | None:
        """Upsert one Movie from a fully-loaded Plex movie; "added"/"updated" or None.

        Identity: TMDB-matched films dedup on ``tmdbid``; unmatched (``tmdb_id == 0``)
        dedup on the ``ratingKey`` scoped to this source, else a shared ``tmdbid=0``
        would collapse every unmatched film into one row.
        """
        from cinefin.api.models import Genre, Movie
        from cinefin.api.ratings.service import file_source_certificate

        try:
            with transaction.atomic():
                title = plex_movie.title
                year = plex_movie.year or 0

                # Multi-version entries (4K + 1080p): take the highest-res, not media[0].
                media = max(plex_movie.media, key=lambda m: resolution_rank(m.videoResolution))
                part = media.parts[0]
                file_size = part.size or 0

                rating_key = str(plex_movie.ratingKey)
                if tmdb_id:
                    existing_movie = Movie.objects.filter(tmdbid=tmdb_id).first()
                else:
                    existing_movie = Movie.objects.filter(sync_source=self.source, plex_rating_key=rating_key).first()
                created = existing_movie is None
                movie = existing_movie or Movie()
                ctx.log("debug", f"Processing movie: {title} ({year})")

                file_path = apply_path_mappings(part.file, self.source)
                resolution = media.videoResolution or "NA"

                # Runtime in minutes, duration in seconds.
                runtime = (plex_movie.duration or 0) / 60000
                duration = (plex_movie.duration or 0) / 1000

                content_rating = plex_movie.contentRating or ""

                director = ""
                if plex_movie.directors:
                    director = plex_movie.directors[0].tag

                credits_marker = 0
                try:
                    if hasattr(plex_movie, "markers") and plex_movie.markers:
                        for marker in plex_movie.markers:
                            if marker.type == "credits":
                                credits_marker = int(marker.start / 1000)
                                ctx.log("debug", f"Found credits marker at {credits_marker}s for {title}")
                                break
                except Exception as e:  # noqa: BLE001
                    ctx.log("debug", f"No credits marker found for {title}: {e}")

                movie.title = title
                movie.file_path = file_path
                movie.director = director
                movie.description = plex_movie.summary or ""
                movie.tmdbid = tmdb_id
                movie.year = year
                movie.poster_key = plex_movie.thumb or ""
                movie.duration = duration
                movie.runtime = runtime
                # File the server's certificate under its own scheme, never
                # clobbering provider-fetched values with wrong-scheme ones.
                file_source_certificate(movie, content_rating)
                movie.resolution = resolution
                movie.file_size = file_size
                # plexapi returns naive server-local datetimes.
                movie.date_added = ensure_aware(plex_movie.addedAt)
                movie.sync_source = self.source
                movie.credits_marker = credits_marker
                movie.plex_rating_key = rating_key
                movie.remote_updated_at = ensure_aware(getattr(plex_movie, "updatedAt", None))
                movie.save()

                movie.genres.clear()
                for genre in plex_movie.genres:
                    genre_obj, _ = Genre.objects.get_or_create(name=genre.tag)
                    movie.genres.add(genre_obj)

            # Tracks OUTSIDE the transaction; reload first so media data is complete.
            plex_movie.reload()
            mediapart = plex_movie.media[0].parts[0]

            # Plex gives bitrate in kbps.
            video_streams = mediapart.videoStreams()
            if video_streams:
                v = video_streams[0]
                apply_video_attrs(
                    movie,
                    codec=v.codec or "",
                    width=getattr(v, "width", 0) or 0,
                    height=getattr(v, "height", 0) or 0,
                    framerate=getattr(v, "frameRate", 0) or 0,
                    bitrate=(getattr(v, "bitrate", 0) or 0) * 1000,
                )
                movie.save(update_fields=VIDEO_ATTR_FIELDS)

            replace_tracks(
                movie,
                audio=[
                    {
                        "title": t.title or "",
                        "language": t.language or "",
                        "codec": t.codec or "",
                        "channels": t.channels,
                    }
                    for t in mediapart.audioStreams()
                ],
                subtitles=[
                    {
                        "language": t.language or "",
                        "forced": getattr(t, "forced", False),
                        "sdh": getattr(t, "hearingImpaired", False),
                    }
                    for t in plex_movie.subtitleStreams()
                ],
            )

            return "added" if created else "updated"

        except Exception as e:  # noqa: BLE001
            ctx.error(f"Error processing movie {plex_movie.title}: {e}")
            return None

    def apply(self, ctx: SyncContext, operation: str, params: dict[str, Any]) -> dict[str, int]:
        from django.db.models import Q

        from cinefin.api.models import Movie

        deep = bool(params.get("deep"))
        plex = self._connect_for_job(ctx)
        ctx.check_cancelled()

        try:
            libraries_to_sync = self.source.get_libraries_list()
            ctx.info(f"Syncing libraries: {', '.join(libraries_to_sync)}{' (deep sync)' if deep else ''}")

            # Single listing pass — plexapi pages internally; no per-item requests
            # until an item needs processing.
            items = []
            had_library_error = False
            for library_name in libraries_to_sync:
                try:
                    library = plex.library.section(library_name)
                    if library.type != "movie":
                        ctx.warn(f"Skipping non-movie library: {library_name}")
                        continue
                    items.extend(library.all())
                except NotFound:
                    ctx.warn(f"Library not found: {library_name}")
                    had_library_error = True
                except Exception as e:  # noqa: BLE001
                    ctx.error(f"Error listing library {library_name}: {e}")
                    had_library_error = True

            total = len(items)
            ctx.info(f"Found {total} films on the server")

            changes = RunChanges()
            seen_keys: set[str] = set()
            seen_tmdb_ids: set[int] = set()
            skipped = 0
            failed = 0

            for position, plex_movie in enumerate(items, start=1):
                ctx.check_cancelled()
                rating_key = str(plex_movie.ratingKey)
                seen_keys.add(rating_key)
                remote_updated = ensure_aware(getattr(plex_movie, "updatedAt", None))

                # Incremental skip: the listing carries updatedAt, so unchanged
                # films cost zero further requests. Deep syncs reprocess everything.
                existing = Movie.objects.filter(sync_source=self.source, plex_rating_key=rating_key).first()
                if existing:
                    if existing.tmdbid:
                        seen_tmdb_ids.add(existing.tmdbid)
                    if not deep and remote_updated and existing.remote_updated_at == remote_updated:
                        skipped += 1
                        # Art key rides along in the listing → posters self-heal without a deep sync.
                        sync_poster_key(existing, plex_movie.thumb or "")
                        # Path rides along too: Plex can move a file without bumping updatedAt,
                        # so heal a stale path even on a skip. Best-effort; never abort the skip.
                        try:
                            skip_media = max(plex_movie.media, key=lambda m: resolution_rank(m.videoResolution))
                            new_path = apply_path_mappings(skip_media.parts[0].file, self.source)
                            if new_path and new_path != existing.file_path:
                                existing.file_path = new_path
                                existing.save(update_fields=["file_path"])
                                ctx.info(f"Relinked moved file: {plex_movie.title}")
                        except Exception:  # noqa: BLE001 — best effort; keep the skip
                            pass
                        # Advance the bar so an unchanged tail doesn't freeze progress mid-way.
                        ctx.progress(position, total, item=f"Unchanged: {plex_movie.title}")
                        continue

                ctx.progress(position, total, item=f"Processing: {plex_movie.title}")
                # Isolate each movie: a single failure must not abort the rest.
                try:
                    plex_movie.reload()  # full metadata: guids, markers, streams
                    tmdb_id = self._get_tmdb_id(plex_movie) or 0
                    # No TMDB match: import anyway keyed on the ratingKey (tmdbid stays 0);
                    # a later agent fix + re-sync fills in the tmdbid.
                    if not tmdb_id:
                        changes.record("unmatched", f"{plex_movie.title} ({plex_movie.year or '?'})")
                    else:
                        seen_tmdb_ids.add(tmdb_id)

                    outcome = self._process_movie(ctx, plex_movie, tmdb_id)
                    if outcome is None:
                        failed += 1
                    else:
                        changes.record(outcome, plex_movie.title)
                        suffix = " (no TMDB match)" if not tmdb_id else ""
                        ctx.info(f"{'Added' if outcome == 'added' else 'Updated'}: {plex_movie.title}{suffix}")
                except SyncCancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    ctx.error(f"Skipped {getattr(plex_movie, 'title', '?')}: {e}")
                    continue

            # Prune orphans, scoped to THIS source only. Refuse after an INCOMPLETE
            # crawl (failed listing or empty result) to avoid mass-deletion on a
            # transient failure. Rows carry the ratingKey last seen under; legacy rows
            # fall back to tmdbid. seen_keys is built from the LISTING (pre-processing),
            # so a film that failed to process is still "present" and can't become a
            # false orphan.
            if had_library_error:
                ctx.warn("Skipping orphan cleanup: a library failed to crawl this run")
            elif not seen_keys:
                ctx.warn("Skipping orphan cleanup: no movies found (refusing to mass-delete)")
            else:
                if failed:
                    ctx.info(f"{failed} film(s) failed to process; pruning only films absent from the server")
                orphans = Movie.objects.filter(sync_source=self.source).filter(
                    Q(plex_rating_key__gt="", plex_rating_key__isnull=False) & ~Q(plex_rating_key__in=seen_keys)
                    | Q(plex_rating_key="") & ~Q(tmdbid__in=seen_tmdb_ids)
                )
                for title in orphans.values_list("title", flat=True):
                    changes.record("removed", title)
                    ctx.info(f"Removing movie no longer in Plex: {title}")
                orphans.delete()

            counts = changes.counts
            if counts["unmatched"]:
                ctx.info(f"Imported {counts['unmatched']} film(s) with no TMDB match")
            ctx.info(
                f"Sync complete: {counts['added']} added, {counts['updated']} updated, {skipped} unchanged, "
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
