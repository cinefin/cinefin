"""Plex source plugin — crawls Plex movie libraries into the local Movie table."""

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


def _best_media(plex_movie):
    # Multi-version entries (4K + 1080p): take the highest-res, not media[0].
    return max(plex_movie.media, key=lambda m: resolution_rank(m.videoResolution))


@register
class PlexSource(SyncSourcePlugin):
    type_id = "plex"
    label = "Plex Media Server"

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

    def get_libraries(self) -> list[str]:
        try:
            return [s.title for s in self._connect().library.sections() if s.type == "movie"]
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
        return resolve_tmdb_via_imdb(imdb_id) if imdb_id else None

    def _process_movie(self, ctx: SyncContext, plex_movie, tmdb_id: int) -> str | None:
        """Upsert one Movie from a fully-loaded Plex movie; "added"/"updated" or None."""
        from cinefin.api.models import Movie
        from cinefin.api.ratings.service import file_source_certificate

        try:
            with transaction.atomic():
                title = plex_movie.title
                media = _best_media(plex_movie)
                part = media.parts[0]
                rating_key = str(plex_movie.ratingKey)
                existing = find_movie(self.source, tmdb_id, plex_rating_key=rating_key)
                movie = existing or Movie()
                ctx.log("debug", f"Processing movie: {title} ({plex_movie.year or 0})")

                credits_marker = 0
                try:
                    marker = next((m for m in plex_movie.markers or [] if m.type == "credits"), None)
                    if marker is not None:
                        credits_marker = int(marker.start / 1000)
                        ctx.log("debug", f"Found credits marker at {credits_marker}s for {title}")
                except Exception as e:  # noqa: BLE001
                    ctx.log("debug", f"No credits marker found for {title}: {e}")

                movie.title = title
                movie.file_path = apply_path_mappings(part.file, self.source)
                movie.director = plex_movie.directors[0].tag if plex_movie.directors else ""
                movie.description = plex_movie.summary or ""
                movie.tmdbid = tmdb_id
                movie.year = plex_movie.year or 0
                movie.poster_key = plex_movie.thumb or ""
                movie.duration = (plex_movie.duration or 0) / 1000  # seconds
                movie.runtime = (plex_movie.duration or 0) / 60000  # minutes
                # Filed under the server's own scheme, never clobbering provider-fetched values.
                file_source_certificate(movie, plex_movie.contentRating or "")
                movie.resolution = media.videoResolution or "NA"
                movie.file_size = part.size or 0
                movie.date_added = ensure_aware(plex_movie.addedAt)  # plexapi gives naive server-local times
                movie.sync_source = self.source
                movie.credits_marker = credits_marker
                movie.plex_rating_key = rating_key
                movie.remote_updated_at = ensure_aware(getattr(plex_movie, "updatedAt", None))
                movie.save()
                set_genres(movie, [genre.tag for genre in plex_movie.genres])

            # Tracks OUTSIDE the transaction; reload first so media data is complete.
            plex_movie.reload()
            mediapart = plex_movie.media[0].parts[0]
            if video_streams := mediapart.videoStreams():
                v = video_streams[0]
                apply_video_attrs(
                    movie,
                    codec=v.codec or "",
                    width=getattr(v, "width", 0) or 0,
                    height=getattr(v, "height", 0) or 0,
                    framerate=getattr(v, "frameRate", 0) or 0,
                    bitrate=(getattr(v, "bitrate", 0) or 0) * 1000,  # Plex reports kbps
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
            return "updated" if existing else "added"

        except Exception as e:  # noqa: BLE001
            ctx.error(f"Error processing movie {plex_movie.title}: {e}")
            return None

    def apply(self, ctx: SyncContext, operation: str, params: dict[str, Any]) -> dict[str, int]:
        from cinefin.api.models import Movie

        deep = bool(params.get("deep"))
        ctx.info(f"Connecting to {self.source.name}…")
        try:
            plex = self._connect()
        except Exception as e:  # noqa: BLE001
            ctx.error(
                "Invalid Plex token - authentication failed"
                if isinstance(e, Unauthorized)
                else f"Connection failed: {e}"
            )
            raise RuntimeError("Failed to connect to source") from e
        ctx.info(f"Successfully connected to Plex server at {self.source.url}")
        ctx.check_cancelled()

        try:
            libraries_to_sync = self.source.get_libraries_list()
            ctx.info(f"Syncing libraries: {', '.join(libraries_to_sync)}{' (deep sync)' if deep else ''}")

            # Single listing pass — plexapi pages internally; no per-item requests until an item needs processing.
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
            skipped = failed = 0

            for position, plex_movie in enumerate(items, start=1):
                ctx.check_cancelled()
                rating_key = str(plex_movie.ratingKey)
                seen_keys.add(rating_key)
                remote_updated = ensure_aware(getattr(plex_movie, "updatedAt", None))

                # Incremental skip: the listing carries updatedAt, so unchanged films cost zero further requests.
                existing = Movie.objects.filter(sync_source=self.source, plex_rating_key=rating_key).first()
                if existing:
                    if existing.tmdbid:
                        seen_tmdb_ids.add(existing.tmdbid)
                    if not deep and remote_updated and existing.remote_updated_at == remote_updated:
                        skipped += 1
                        # Art key and path ride along in the listing, so posters and moved files self-heal
                        # without a deep sync (Plex can move a file without bumping updatedAt).
                        sync_poster_key(existing, plex_movie.thumb or "")
                        try:
                            new_path = apply_path_mappings(_best_media(plex_movie).parts[0].file, self.source)
                            relink(ctx, existing, new_path, plex_movie.title)
                        except Exception:  # noqa: BLE001 — best effort; keep the skip
                            pass
                        ctx.progress(position, total, item=f"Unchanged: {plex_movie.title}")
                        continue

                ctx.progress(position, total, item=f"Processing: {plex_movie.title}")
                # Isolate each movie: a single failure must not abort the rest.
                try:
                    plex_movie.reload()  # full metadata: guids, markers, streams
                    tmdb_id = self._get_tmdb_id(plex_movie) or 0
                    # No TMDB match: import anyway keyed on the ratingKey; a later fix + re-sync fills it in.
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

            # A library that failed to list would make all its films look like orphans.
            if had_library_error:
                ctx.warn("Skipping orphan cleanup: a library failed to crawl this run")
            else:
                prune_orphans(
                    ctx,
                    self.source,
                    changes,
                    "plex_rating_key",
                    seen_keys,
                    seen_tmdb_ids,
                    failed,
                    removing="Removing movie no longer in Plex: ",
                )
            return changes.summary(ctx, "Sync complete", skipped, failed)

        except SyncCancelled:
            raise
        except Exception as e:
            ctx.error(f"Sync failed: {e}")
            raise
