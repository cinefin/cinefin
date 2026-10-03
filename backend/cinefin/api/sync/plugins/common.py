"""Helpers shared by the Plex/Jellyfin source plugins. Poster art is never downloaded or stored, only
referenced — see ``services/poster_service.py``."""

from datetime import UTC, datetime

from django.conf import settings
from django.db.models import Q
from django.utils import timezone


def ensure_aware(dt: datetime | None, assume_utc: bool = False) -> datetime | None:
    """Make a naive datetime aware. ``assume_utc``: UTC (Jellyfin) else local (Plex)."""
    if dt is None or timezone.is_aware(dt):
        return dt
    return dt.replace(tzinfo=UTC) if assume_utc else timezone.make_aware(dt)


def apply_path_mappings(path: str, source) -> str:
    """Rewrite a server-reported path via the source's mappings; longest prefix wins."""
    if not path:
        return path
    best = None
    for rule in source.path_mappings or []:
        src = (rule.get("from") or "").rstrip("/")
        if src and path.startswith(src) and (best is None or len(src) > len(best[0])):
            best = (src, (rule.get("to") or "").rstrip("/"))
    return best[1] + path[len(best[0]) :] if best else path


def resolve_tmdb_via_imdb(imdb_id: str) -> int | None:
    """Best-effort IMDb→TMDB resolution; None (unmatched) if no key or lookup fails."""
    from cinefin.api.models import Settings

    api_key = Settings.get("trailers.tmdb_api_key", "") or getattr(settings, "TMDB_API_KEY", "")
    if not api_key or not imdb_id:
        return None
    try:
        from tmdbv3api import Find, TMDb

        TMDb().api_key = api_key
        result = Find().find_by_imdb_id(imdb_id)
        movies = result.get("movie_results") if isinstance(result, dict) else getattr(result, "movie_results", None)
        if movies:
            first = movies[0]
            return int(first["id"] if isinstance(first, dict) else first.id)
    except Exception:  # noqa: BLE001 — resolution is optional; failure means "unmatched"
        return None
    return None


# Rank strings the two servers use for video resolution, best first.
_RESOLUTION_ORDER = ("4k", "2160", "1080", "720", "576", "480")


def resolution_rank(resolution: str | None) -> int:
    value = (resolution or "").lower()
    return next((len(_RESOLUTION_ORDER) - i for i, m in enumerate(_RESOLUTION_ORDER) if m in value), 0)


class RunChanges:
    """Run receipt of added/updated/removed/unmatched titles. Titles capped per bucket to avoid bloating the
    Job row; counts stay exact."""

    CAP = 50

    def __init__(self):
        self._buckets: dict[str, list[str]] = {"added": [], "updated": [], "removed": [], "unmatched": []}
        self.counts: dict[str, int] = {k: 0 for k in self._buckets}

    def record(self, bucket: str, title: str) -> None:
        self.counts[bucket] += 1
        if len(self._buckets[bucket]) < self.CAP:
            self._buckets[bucket].append(title)

    def as_dict(self) -> dict:
        return {k: v for k, v in self._buckets.items() if v}

    def summary(self, ctx, done: str, skipped: int, failed: int) -> dict:
        """Log the run's closing lines and return the Job's counts."""
        counts = self.counts
        if counts["unmatched"]:
            ctx.info(f"Imported {counts['unmatched']} film(s) with no TMDB match")
        ctx.info(
            f"{done}: {counts['added']} added, {counts['updated']} updated, {skipped} unchanged, "
            f"{counts['removed']} removed, {counts['unmatched']} imported without a TMDB id, {failed} failed"
        )
        return {
            "added": counts["added"],
            "updated": counts["updated"],
            "skipped": skipped,
            "removed": counts["removed"],
            "unmatched": counts["unmatched"],
            "failed": failed,
            "changes": self.as_dict(),
        }


def find_movie(source, tmdb_id: int, **server_id):
    """The row to upsert. TMDB-matched films dedup on ``tmdbid``; unmatched ones (``tmdb_id == 0``) on the
    server's item id scoped to this source, else a shared ``tmdbid=0`` would collapse them into one row."""
    from cinefin.api.models import Movie

    if tmdb_id:
        return Movie.objects.filter(tmdbid=tmdb_id).first()
    return Movie.objects.filter(sync_source=source, **server_id).first()


def set_genres(movie, names) -> None:
    from cinefin.api.models import Genre

    movie.genres.clear()
    for name in names:
        movie.genres.add(Genre.objects.get_or_create(name=name)[0])


def relink(ctx, movie, new_path: str, title: str) -> None:
    """Heal a stale file path (servers can move a file without marking the item changed)."""
    if new_path and new_path != movie.file_path:
        movie.file_path = new_path
        movie.save(update_fields=["file_path"])
        ctx.info(f"Relinked moved file: {title}")


def prune_orphans(
    ctx, source, changes: RunChanges, id_field: str, seen_ids: set, seen_tmdb_ids: set, failed: int, removing: str
):
    """Delete this source's films the server no longer lists.

    Rows carry the server id last seen under; legacy rows fall back to tmdbid. ``seen_ids`` comes from the
    LISTING (pre-processing), so a film that failed to process is still "present" and can't become a false
    orphan. An empty listing is refused to avoid mass-deletion on a transient failure.
    """
    from cinefin.api.models import Movie

    if not seen_ids:
        ctx.warn("Skipping orphan cleanup: no movies found (refusing to mass-delete)")
        return
    if failed:
        ctx.info(f"{failed} film(s) failed to process; pruning only films absent from the server")
    orphans = Movie.objects.filter(sync_source=source).filter(
        Q(**{f"{id_field}__gt": ""}) & ~Q(**{f"{id_field}__in": seen_ids})
        | Q(**{id_field: ""}) & ~Q(tmdbid__in=seen_tmdb_ids)
    )
    for title in orphans.values_list("title", flat=True):
        changes.record("removed", title)
        ctx.info(f"{removing}{title}")
    orphans.delete()


def replace_tracks(movie, audio: list[dict], subtitles: list[dict]) -> None:
    from cinefin.api.models import AudioTrack, SubtitleTrack

    movie.audio_tracks.all().delete()
    for index, track in enumerate(audio):
        AudioTrack.objects.create(
            movie=movie,
            index=index,
            title=track.get("title", ""),
            language=track.get("language", ""),
            codec=track.get("codec", ""),
            channels=track.get("channels", 0) or 0,
        )
    movie.subtitle_tracks.all().delete()
    for index, track in enumerate(subtitles):
        SubtitleTrack.objects.create(
            movie=movie,
            index=index,
            language=track.get("language", ""),
            forced=bool(track.get("forced", False)),
            sdh=bool(track.get("sdh", False)),
        )


VIDEO_ATTR_FIELDS = ["video_codec", "video_width", "video_height", "video_framerate", "video_bitrate"]


def apply_video_attrs(movie, *, codec="", width=0, height=0, framerate=0.0, bitrate=0) -> None:
    """Set video-stream attrs (bitrate in bits/sec); does not save."""
    movie.video_codec = (codec or "")[:50]
    movie.video_width = int(width or 0)
    movie.video_height = int(height or 0)
    movie.video_framerate = float(framerate or 0)
    movie.video_bitrate = int(bitrate or 0)


def sync_poster_key(movie, key: str) -> None:
    """Refresh a skipped movie's poster ref so server-side art edits show up without a deep sync."""
    if (movie.poster_key or "") != (key or ""):
        movie.poster_key = key or ""
        movie.save(update_fields=["poster_key"])
