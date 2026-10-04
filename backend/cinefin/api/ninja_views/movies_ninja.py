"""Movies API — managing and accessing the movie library."""

import os

from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Avg, Count, F, Prefetch, Q, Sum
from django.db.models.functions import Mod
from django.http import HttpRequest, HttpResponse, HttpResponseNotModified, HttpResponseRedirect
from ninja import Field, Query, Router, Schema

from cinefin.api.exceptions import NotFoundError, ValidationError
from cinefin.api.models import AudioTrack, Genre, Movie, ProgrammeBlock, Settings, SubtitleTrack, Trailer, TrailerRule
from cinefin.api.ratings.service import denormalize_certificate
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import poster_service, streaming_service
from cinefin.api.utils.media_paths import usermedia_abs_path

E400 = {400: ErrorResponseSchema}
E404 = {404: ErrorResponseSchema}
E500 = {500: ErrorResponseSchema}


class GenreSchema(Schema):
    id: int
    name: str


class AudioTrackSchema(Schema):
    id: int
    index: int
    language: str
    codec: str
    channels: int
    title: str | None = None


class SubtitleTrackSchema(Schema):
    id: int
    index: int
    language: str
    forced: bool
    sdh: bool = Field(description="Subtitles for the deaf and hard of hearing")


class VideoInfoSchema(Schema):
    codec: str | None = None
    width: int | None = None
    height: int | None = None
    framerate: float | None = None
    bitrate: int | None = None


class MovieListItemSchema(Schema):
    id: int
    title: str
    year: int | None = None
    director: str | None = None
    runtime: int | None = Field(default=None, description="Minutes")
    certification: str | None = None
    resolution: str | None = None
    file_size: int | None = Field(default=None, description="Bytes")
    file_path: str | None = None
    description: str | None = None
    tmdbid: int | None = None
    date_added: str | None = None
    thumbnail_url: str | None = None
    genres: list[str] = Field(description="Genre names")
    audio_track_count: int
    subtitle_track_count: int
    kiosk_display: bool
    stream_url: str
    has_trailer: bool = False


class PaginationSchema(Schema):
    page: int
    per_page: int
    total: int
    total_pages: int
    has_next: bool
    has_previous: bool


class FiltersSchema(Schema):
    genres: list[str]
    certifications: list[str]
    resolutions: list[str]


class MovieListDataSchema(Schema):
    items: list[MovieListItemSchema]
    pagination: PaginationSchema
    filters: FiltersSchema = Field(description="Available filter options")


class MovieListResponseSchema(SuccessResponseSchema):
    data: MovieListDataSchema


class MovieDetailSchema(Schema):
    id: int
    title: str
    year: int | None = None
    director: str | None = None
    runtime: int | None = Field(default=None, description="Minutes")
    certification: str | None = Field(default=None, description="Certificate in the active ratings system")
    certificates: dict[str, str] = Field(default={}, description="Certificates per ratings system, e.g. {'BBFC': '15'}")
    resolution: str | None = None
    file_size: int | None = Field(default=None, description="Bytes")
    file_path: str | None = None
    description: str | None = None
    tmdbid: int | None = None
    date_added: str | None = None
    thumbnail_url: str | None = None
    kiosk_display: bool
    stream_url: str
    genres: list[int] = Field(description="Genre IDs")
    audio_tracks: list[AudioTrackSchema]
    subtitle_tracks: list[SubtitleTrackSchema]
    video_info: VideoInfoSchema | None = None
    has_trailer: bool = False
    trailer_id: int | None = Field(
        default=None,
        description="Id of a playable covering trailer (file present on disk), or null — stream at /stream/trailer/{id}/",
    )


class MovieDetailResponseSchema(SuccessResponseSchema):
    data: MovieDetailSchema


class MovieStreamSchema(Schema):
    stream_url: str
    direct: bool
    plex_metadata: dict | None = None
    movie: dict


class MovieStreamResponseSchema(SuccessResponseSchema):
    data: MovieStreamSchema


class GenreStatsSchema(Schema):
    name: str
    movie_count: int


class YearStatsSchema(Schema):
    year: int
    count: int


class CertStatsSchema(Schema):
    certification: str
    count: int


class MovieStatsSchema(Schema):
    total_movies: int
    total_size_bytes: int
    total_size_readable: str
    total_runtime_minutes: int
    total_runtime_readable: str
    average_runtime_minutes: int
    genres: list[GenreStatsSchema]
    years: list[YearStatsSchema]
    certifications: list[CertStatsSchema]


class MovieStatsResponseSchema(SuccessResponseSchema):
    data: MovieStatsSchema


class GenreListResponseSchema(SuccessResponseSchema):
    data: list[GenreSchema]


class RatingsOptionsSchema(Schema):
    system: str = Field(description="Active ratings system, e.g. 'BBFC'")
    ratings: list[str] = Field(description="Valid certificates in ascending-severity order")


class RatingsOptionsResponseSchema(SuccessResponseSchema):
    data: RatingsOptionsSchema


class CertificationUpdateSchema(Schema):
    certification: str | None = Field(default=None, description="New certificate, or null/empty to clear")


class CertificationUpdateDataSchema(Schema):
    id: int
    certification: str = Field(description="Certificate in the active system after the update ('' when cleared)")
    certificates: dict[str, str]


class CertificationUpdateResponseSchema(SuccessResponseSchema):
    data: CertificationUpdateDataSchema


class BulkMovieIdsSchema(Schema):
    ids: list[int]


class BulkKioskRequestSchema(BulkMovieIdsSchema):
    kiosk_display: bool


class BulkDeleteDataSchema(Schema):
    deleted: int
    missing: list[int] = Field(description="Requested IDs that were not found")


class BulkDeleteResponseSchema(SuccessResponseSchema):
    data: BulkDeleteDataSchema


class BulkKioskDataSchema(Schema):
    updated: int
    missing: list[int] = Field(description="Requested IDs that were not found")
    kiosk_display: bool


class BulkKioskResponseSchema(SuccessResponseSchema):
    data: BulkKioskDataSchema


class ClearLibrarySchema(Schema):
    total: int
    in_use: int = Field(description="How many are referenced by a programme or trailer rule")


class ClearLibraryPreviewResponseSchema(SuccessResponseSchema):
    data: ClearLibrarySchema


class ClearLibraryDataSchema(Schema):
    deleted: int
    in_use: int = Field(description="How many of the removed movies were referenced by a programme or trailer rule")


class ClearLibraryResponseSchema(SuccessResponseSchema):
    data: ClearLibraryDataSchema


class MovieListFilters(Schema):
    search: str | None = Field(default=None, description="Search in title, director, or description")
    genre: str | None = Field(default=None, description="Comma-separated; a movie must have every genre")
    year_from: int | None = None
    year_to: int | None = None
    runtime_from: int | None = Field(default=None, description="Minutes")
    runtime_to: int | None = Field(default=None, description="Minutes")
    certification: str | None = None
    resolution: str | None = None
    kiosk: bool | None = None
    has_trailer: bool | None = None
    tmdb: str | None = Field(default=None, description="'missing' (tmdbid=0), 'present' (tmdbid>0), or unset for any")
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=10000)
    sort: str = "title"
    order: str = Field(default="asc", description="asc/desc")
    random_seed: int | None = Field(
        default=None, description="Seed for sort=random so pagination stays consistent (omit to reshuffle)"
    )


movies_api = Router()

SORT_FIELDS = {"title", "year", "date_added", "runtime", "file_size"}
TRACK_PREFETCHES = (
    "genres",
    Prefetch("audio_tracks", queryset=AudioTrack.objects.order_by("index")),
    Prefetch("subtitle_tracks", queryset=SubtitleTrack.objects.order_by("index")),
)


def _get_movie(movie_id: int, queryset=Movie.objects) -> Movie:
    try:
        return queryset.get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None


def _movie_fields(movie: Movie) -> dict:
    """The fields the list item and the detail share."""
    return {
        "id": movie.id,
        "title": movie.title,
        "year": movie.year,
        "director": movie.director,
        "runtime": movie.runtime,
        "certification": movie.certification,
        "resolution": movie.resolution,
        "file_size": movie.file_size,
        "file_path": movie.file_path,
        "description": movie.description,
        "tmdbid": movie.tmdbid,
        "date_added": movie.date_added.isoformat() if movie.date_added else None,
        "thumbnail_url": movie.thumbnail_url,
        "kiosk_display": movie.kiosk_display,
        "stream_url": f"/api/v2/movies/{movie.id}/stream",
    }


def _distinct_values(field: str) -> list[str]:
    return list(Movie.objects.values_list(field, flat=True).distinct().exclude(**{field: ""}).order_by(field))


@movies_api.get("/list", response={200: MovieListResponseSchema, **E500})
def list_movies(request: HttpRequest, filters: MovieListFilters = Query(...)):
    queryset = Movie.objects.all()

    if filters.search:
        queryset = queryset.filter(
            Q(title__icontains=filters.search)
            | Q(director__icontains=filters.search)
            | Q(description__icontains=filters.search)
        )
    for genre_name in (g.strip() for g in (filters.genre or "").split(",")):
        if genre_name:
            queryset = queryset.filter(genres__name__iexact=genre_name)
    for value, lookup in (
        (filters.year_from, "year__gte"),
        (filters.year_to, "year__lte"),
        (filters.runtime_from, "runtime__gte"),
        (filters.runtime_to, "runtime__lte"),
        (filters.certification, "certification__iexact"),
        (filters.resolution, "resolution__iexact"),
    ):
        if value:
            queryset = queryset.filter(**{lookup: value})
    if filters.kiosk is not None:
        queryset = queryset.filter(kiosk_display=filters.kiosk)
    # Films synced without a TMDB match carry tmdbid=0.
    if filters.tmdb == "missing":
        queryset = queryset.filter(tmdbid=0)
    elif filters.tmdb == "present":
        queryset = queryset.filter(tmdbid__gt=0)

    with_file = Trailer.objects.exclude(file_path="")
    trailer_tmdbids = set(with_file.exclude(tmdbid=0).values_list("tmdbid", flat=True))
    trailer_movie_ids = set(
        with_file.filter(associated_movie__isnull=False).values_list("associated_movie_id", flat=True)
    )
    if filters.has_trailer is not None:
        with_trailer_q = Q(tmdbid__in=trailer_tmdbids) | Q(id__in=trailer_movie_ids)
        queryset = queryset.filter(with_trailer_q) if filters.has_trailer else queryset.exclude(with_trailer_q)

    queryset = queryset.prefetch_related(*TRACK_PREFETCHES)

    if filters.sort == "random":
        if filters.random_seed:
            # Deterministic shuffle: for prime P, id → (id·mult) mod P is a
            # bijection, so a fixed seed gives one stable permutation across
            # pages (no dupes/gaps). The seed is spread by a large fixed
            # multiplier first, so even small seeds mix well (a bare id·seed
            # degenerates to id-order until the product wraps P).
            prime = 2147483647  # 2^31 - 1
            mult = (filters.random_seed % prime) * 1327217884 % prime or 1
            queryset = queryset.annotate(_rnd=Mod(F("id") * mult, prime)).order_by("_rnd", "id")
        else:
            queryset = queryset.order_by("?")
    elif filters.sort in SORT_FIELDS:
        queryset = queryset.order_by(f"-{filters.sort}" if filters.order == "desc" else filters.sort)
    else:
        queryset = queryset.order_by("title")

    paginator = Paginator(queryset.distinct(), filters.per_page)
    try:
        movies_page = paginator.page(filters.page)
    except EmptyPage:
        movies_page = paginator.page(paginator.num_pages)

    items = [
        {
            **_movie_fields(movie),
            "genres": [genre.name for genre in movie.genres.all()],
            # len() reads the prefetched cache; .count() would issue a query per movie
            "audio_track_count": len(movie.audio_tracks.all()),
            "subtitle_track_count": len(movie.subtitle_tracks.all()),
            "has_trailer": bool(movie.tmdbid and movie.tmdbid in trailer_tmdbids) or movie.id in trailer_movie_ids,
        }
        for movie in movies_page
    ]
    return {
        "message": "Movies retrieved successfully",
        "data": {
            "items": items,
            "pagination": {
                "page": movies_page.number,
                "per_page": filters.per_page,
                "total": paginator.count,
                "total_pages": paginator.num_pages,
                "has_next": movies_page.has_next(),
                "has_previous": movies_page.has_previous(),
            },
            "filters": {
                "genres": list(Genre.objects.order_by("name").values_list("name", flat=True)),
                "certifications": _distinct_values("certification"),
                "resolutions": _distinct_values("resolution"),
            },
        },
    }


def _format_file_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def _format_runtime(minutes):
    hours, mins = divmod(minutes or 0, 60)
    return f"{hours}h {mins}m" if hours else f"{mins} minutes"


@movies_api.get("/stats", response={200: MovieStatsResponseSchema, **E500})
def get_movie_stats(request: HttpRequest):
    stats = Movie.objects.aggregate(
        total_movies=Count("id"), total_size=Sum("file_size"), total_runtime=Sum("runtime"), avg_runtime=Avg("runtime")
    )
    genre_stats = (
        Genre.objects.annotate(movie_count=Count("movie"))
        .filter(movie_count__gt=0)
        .order_by("-movie_count")
        .values("name", "movie_count")
    )
    year_stats = Movie.objects.values("year").annotate(count=Count("id")).order_by("-year")[:10]
    cert_stats = (
        Movie.objects.exclude(certification="")
        .values("certification")
        .annotate(count=Count("id"))
        .order_by("certification")
    )
    total_size = stats["total_size"] or 0
    total_runtime = stats["total_runtime"] or 0
    return {
        "message": "Movie statistics retrieved successfully",
        "data": {
            "total_movies": stats["total_movies"] or 0,
            "total_size_bytes": total_size,
            "total_size_readable": _format_file_size(total_size),
            "total_runtime_minutes": total_runtime,
            "total_runtime_readable": _format_runtime(total_runtime),
            "average_runtime_minutes": round(stats["avg_runtime"] or 0),
            "genres": list(genre_stats),
            "years": list(year_stats),
            "certifications": list(cert_stats),
        },
    }


@movies_api.get("/genres", response={200: GenreListResponseSchema, **E500})
def list_genres(request: HttpRequest):
    return {
        "message": "Genres retrieved successfully",
        "data": list(Genre.objects.order_by("name").values("id", "name")),
    }


@movies_api.get("/ratings-options", response={200: RatingsOptionsResponseSchema, **E500})
def get_ratings_options(request: HttpRequest):
    system = Settings.get_ratings_system()
    return {
        "message": "Ratings options retrieved successfully",
        "data": {"system": system, "ratings": list(Settings.get_ratings_order(system))},
    }


# The bulk and /clear-library routes must be registered before the /{movie_id}
# routes: Ninja compiles {movie_id} with a string converter, so a later literal
# path would be shadowed by it.

BULK_MAX_IDS = 500


def _existing_bulk_ids(ids: list[int]) -> tuple[list[int], list[int]]:
    """(existing ids, missing ids) for a validated, de-duplicated bulk request."""
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        raise ValidationError("No movie IDs provided")
    if len(unique_ids) > BULK_MAX_IDS:
        raise ValidationError(f"Too many movie IDs (maximum {BULK_MAX_IDS} per request)")
    existing = set(Movie.objects.filter(id__in=unique_ids).values_list("id", flat=True))
    return list(existing), [movie_id for movie_id in unique_ids if movie_id not in existing]


def _movies(count: int) -> str:
    return f"{count} movie" if count == 1 else f"{count} movies"


@movies_api.post("/bulk-delete", response={200: BulkDeleteResponseSchema, **E400, **E500})
def bulk_delete_movies(request: HttpRequest, payload: BulkMovieIdsSchema):
    # Removes from the library DB only; does not delete files on disk.
    existing, missing = _existing_bulk_ids(payload.ids)
    Movie.objects.filter(id__in=existing).delete()
    return {
        "message": f"{_movies(len(existing))} removed from library",
        "data": {"deleted": len(existing), "missing": missing},
    }


@movies_api.post("/bulk-kiosk", response={200: BulkKioskResponseSchema, **E400, **E500})
def bulk_kiosk_movies(request: HttpRequest, payload: BulkKioskRequestSchema):
    existing, missing = _existing_bulk_ids(payload.ids)
    updated = Movie.objects.filter(id__in=existing).update(kiosk_display=payload.kiosk_display)
    status = "enabled" if payload.kiosk_display else "disabled"
    return {
        "message": f"Kiosk display {status} for {_movies(updated)}",
        "data": {"updated": updated, "missing": missing, "kiosk_display": payload.kiosk_display},
    }


def _movies_in_use_count() -> int:
    """Distinct movies referenced by a programme block (feature) or a trailer rule."""
    used = set(ProgrammeBlock.objects.filter(movie__isnull=False).values_list("movie_id", flat=True))
    used |= set(TrailerRule.objects.filter(reference_movie__isnull=False).values_list("reference_movie_id", flat=True))
    return len(used)


@movies_api.get("/clear-library", response={200: ClearLibraryPreviewResponseSchema, **E500})
def clear_library_preview(request: HttpRequest):
    return {"message": "Library summary", "data": {"total": Movie.objects.count(), "in_use": _movies_in_use_count()}}


@movies_api.post("/clear-library", response={200: ClearLibraryResponseSchema, **E500})
def clear_library(request: HttpRequest):
    """Remove every movie from the library (DB only). Referencing programme/trailer-rule slots are SET_NULL."""
    in_use = _movies_in_use_count()
    total = Movie.objects.count()
    Movie.objects.all().delete()
    return {"message": f"{_movies(total)} removed from library", "data": {"deleted": total, "in_use": in_use}}


@movies_api.get("/{movie_id}", response={200: MovieDetailResponseSchema, **E404, **E500})
def get_movie_detail(request: HttpRequest, movie_id: int):
    movie = _get_movie(movie_id, Movie.objects.prefetch_related(*TRACK_PREFETCHES))

    # Video tech info as reported by the media server at sync time (never a local scan).
    video_info = None
    if movie.video_codec or movie.video_width or movie.video_bitrate:
        video_info = {
            "codec": movie.video_codec or None,
            "width": movie.video_width or None,
            "height": movie.video_height or None,
            "framerate": movie.video_framerate or None,
            "bitrate": movie.video_bitrate or None,
        }

    # A linked trailer wins over a tmdbid-only match.
    trailer_q = Q(associated_movie_id=movie.id)
    if movie.tmdbid:
        trailer_q |= Q(tmdbid=movie.tmdbid)
    covering = list(Trailer.objects.filter(trailer_q).order_by(F("associated_movie_id").desc(nulls_last=True)))
    playable = next((t for t in covering if t.file_path and os.path.exists(usermedia_abs_path(t.file_path))), None)

    return {
        "message": "Movie details retrieved successfully",
        "data": {
            **_movie_fields(movie),
            "certificates": movie.certificates or {},
            "genres": [genre.id for genre in movie.genres.all()],
            "audio_tracks": [
                {
                    "id": t.id,
                    "index": t.index,
                    "language": t.language,
                    "codec": t.codec,
                    "channels": t.channels,
                    "title": t.title,
                }
                for t in movie.audio_tracks.all()
            ],
            "subtitle_tracks": [
                {"id": t.id, "index": t.index, "language": t.language, "forced": t.forced, "sdh": t.sdh}
                for t in movie.subtitle_tracks.all()
            ],
            "video_info": video_info,
            "has_trailer": playable is not None,
            "trailer_id": playable.id if playable else None,
        },
    }


@movies_api.get("/{movie_id}/poster", response={200: None, 302: None, **E404})
def get_movie_poster(request: HttpRequest, movie_id: int):
    # Proxied live from the media server (never synced to disk); the art key
    # doubles as the ETag. Falls back to the bundled default poster on any failure.
    movie = _get_movie(movie_id, Movie.objects.select_related("sync_source"))

    etag = f'"{movie.poster_key}"'
    if movie.poster_key and request.headers.get("If-None-Match") == etag:
        return HttpResponseNotModified()

    content = poster_service.fetch_poster(movie)
    if content is None:
        # Briefly cache the fallback so an unreachable media server isn't
        # re-probed for every tile on every page load while it's down.
        fallback = HttpResponseRedirect(settings.STATIC_URL + "img/default-movie-poster.jpg")
        fallback["Cache-Control"] = "private, max-age=60"
        return fallback

    response = HttpResponse(content, content_type="image/jpeg")
    response["Cache-Control"] = "private, max-age=86400"
    response["ETag"] = etag
    return response


@movies_api.get("/{movie_id}/stream", response={200: MovieStreamResponseSchema, **E400, **E404, **E500})
def stream_movie(request: HttpRequest, movie_id: int):
    movie = _get_movie(movie_id, Movie.objects.select_related("sync_source"))
    result = streaming_service.get_movie_stream_url(movie)
    return {
        "message": "Movie stream URL retrieved successfully",
        "data": {
            "stream_url": result["stream_url"],
            "direct": result["direct"],
            "plex_metadata": result.get("plex_metadata"),
            "movie": {
                "id": movie.id,
                "title": movie.title,
                "year": movie.year,
                "runtime": movie.runtime,
                "resolution": movie.resolution,
                "file_size": movie.file_size,
            },
        },
    }


@movies_api.delete("/{movie_id}", response={200: MessageResponseSchema, **E404, **E500})
def delete_movie(request: HttpRequest, movie_id: int):
    # Removes from the library DB only; does not delete the file on disk.
    movie = _get_movie(movie_id)
    movie.delete()
    return {"message": f"'{movie.title}' removed from library"}


@movies_api.post("/{movie_id}/toggle_kiosk", response={200: MessageResponseSchema, **E404, **E500})
def toggle_movie_kiosk(request: HttpRequest, movie_id: int):
    movie = _get_movie(movie_id)
    movie.kiosk_display = not movie.kiosk_display
    movie.save()
    status = "enabled" if movie.kiosk_display else "disabled"
    return {"message": f"Kiosk display {status} for '{movie.title}'"}


@movies_api.patch(
    "/{movie_id}/certification", response={200: CertificationUpdateResponseSchema, **E400, **E404, **E500}
)
def update_movie_certification(request: HttpRequest, movie_id: int, payload: CertificationUpdateSchema):
    movie = _get_movie(movie_id)
    system = Settings.get_ratings_system()
    value = (payload.certification or "").strip()

    # Empty means "Unrated": drop the active system's slot.
    if value and value not in Settings.get_valid_ratings(system):
        raise ValidationError(f"'{value}' is not a valid {system} certificate")

    certs = dict(movie.certificates or {})
    if value:
        certs[system] = value
    else:
        certs.pop(system, None)
    movie.certificates = certs
    movie.save(update_fields=["certificates"])
    # Re-derive the denormalised scalar for this one row only.
    denormalize_certificate(movie, system)

    return {
        "message": "Certificate updated successfully",
        "data": {"id": movie.id, "certification": movie.certification or "", "certificates": movie.certificates or {}},
    }
