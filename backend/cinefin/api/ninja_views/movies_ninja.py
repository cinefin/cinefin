"""Movies API — managing and accessing the movie library."""

import logging
import os

from django.conf import settings
from django.core.paginator import EmptyPage, Paginator
from django.db.models import Avg, Count, F, Prefetch, Q, Sum
from django.db.models.functions import Mod
from django.http import HttpRequest, HttpResponse, HttpResponseNotModified, HttpResponseRedirect
from ninja import Field, Query, Router, Schema, Status

from cinefin.api.exceptions import NotFoundError, ValidationError
from cinefin.api.models import AudioTrack, Genre, Movie, Settings, SubtitleTrack, Trailer
from cinefin.api.ratings.service import denormalize_certificate
from cinefin.api.schemas.base import ErrorResponseSchema, MessageResponseSchema, SuccessResponseSchema
from cinefin.api.services import poster_service, streaming_service
from cinefin.api.utils.media_paths import usermedia_abs_path

logger = logging.getLogger(__name__)


class GenreSchema(Schema):
    id: int = Field(description="Genre unique identifier")
    name: str = Field(description="Genre name")


class AudioTrackSchema(Schema):
    id: int = Field(description="Audio track unique identifier")
    index: int = Field(description="Track index in media file")
    language: str = Field(description="Audio track language")
    codec: str = Field(description="Audio codec used")
    channels: int = Field(description="Number of audio channels")
    title: str | None = Field(default=None, description="Audio track title")


class SubtitleTrackSchema(Schema):
    id: int = Field(description="Subtitle track unique identifier")
    index: int = Field(description="Track index in media file")
    language: str = Field(description="Subtitle language")
    forced: bool = Field(description="Whether subtitle is forced")
    sdh: bool = Field(description="Whether subtitle is SDH (Subtitles for Deaf and Hard-of-hearing)")


class VideoInfoSchema(Schema):
    codec: str | None = Field(default=None, description="Video codec")
    width: int | None = Field(default=None, description="Video width in pixels")
    height: int | None = Field(default=None, description="Video height in pixels")
    framerate: float | None = Field(default=None, description="Video framerate")
    bitrate: int | None = Field(default=None, description="Video bitrate in bps")


class MovieListItemSchema(Schema):
    id: int = Field(description="Movie unique identifier")
    title: str = Field(description="Movie title")
    year: int | None = Field(default=None, description="Release year")
    director: str | None = Field(default=None, description="Movie director")
    runtime: int | None = Field(default=None, description="Runtime in minutes")
    certification: str | None = Field(default=None, description="Movie certification/rating")
    resolution: str | None = Field(default=None, description="Video resolution")
    file_size: int | None = Field(default=None, description="File size in bytes")
    file_path: str | None = Field(default=None, description="Path to movie file")
    description: str | None = Field(default=None, description="Movie description/plot")
    tmdbid: int | None = Field(default=None, description="TMDB ID")
    date_added: str | None = Field(default=None, description="Date added to library")
    thumbnail_url: str | None = Field(default=None, description="Thumbnail URL")
    genres: list[str] = Field(description="List of genre names")
    audio_track_count: int = Field(description="Number of audio tracks")
    subtitle_track_count: int = Field(description="Number of subtitle tracks")
    kiosk_display: bool = Field(description="Whether to display in kiosk mode")
    stream_url: str = Field(description="Movie streaming URL")
    has_trailer: bool = Field(default=False, description="Whether a downloaded trailer exists for this movie")


class PaginationSchema(Schema):
    page: int = Field(description="Current page number")
    per_page: int = Field(description="Items per page")
    total: int = Field(description="Total number of items")
    total_pages: int = Field(description="Total number of pages")
    has_next: bool = Field(description="Whether there is a next page")
    has_previous: bool = Field(description="Whether there is a previous page")


class FiltersSchema(Schema):
    genres: list[str] = Field(description="Available genre names")
    certifications: list[str] = Field(description="Available certification types")
    resolutions: list[str] = Field(description="Available resolution types")


class MovieListDataSchema(Schema):
    items: list[MovieListItemSchema] = Field(description="List of movies")
    pagination: PaginationSchema = Field(description="Pagination information")
    filters: FiltersSchema = Field(description="Available filter options")


class MovieListResponseSchema(SuccessResponseSchema):
    data: MovieListDataSchema


class MovieDetailSchema(Schema):
    id: int = Field(description="Movie unique identifier")
    title: str = Field(description="Movie title")
    year: int | None = Field(default=None, description="Release year")
    director: str | None = Field(default=None, description="Movie director")
    runtime: int | None = Field(default=None, description="Runtime in minutes")
    certification: str | None = Field(default=None, description="Certificate in the active ratings system")
    certificates: dict[str, str] = Field(default={}, description="Certificates per ratings system, e.g. {'BBFC': '15'}")
    resolution: str | None = Field(default=None, description="Video resolution")
    file_size: int | None = Field(default=None, description="File size in bytes")
    file_path: str | None = Field(default=None, description="Path to movie file")
    description: str | None = Field(default=None, description="Movie description/plot")
    tmdbid: int | None = Field(default=None, description="TMDB ID")
    date_added: str | None = Field(default=None, description="Date added to library")
    thumbnail_url: str | None = Field(default=None, description="Thumbnail URL")
    kiosk_display: bool = Field(description="Whether to display in kiosk mode")
    stream_url: str = Field(description="Movie streaming URL")
    genres: list[int] = Field(description="List of genre IDs")
    audio_tracks: list[AudioTrackSchema] = Field(description="Audio tracks")
    subtitle_tracks: list[SubtitleTrackSchema] = Field(description="Subtitle tracks")
    video_info: VideoInfoSchema | None = Field(default=None, description="Video technical information")
    has_trailer: bool = Field(default=False, description="Whether a downloaded trailer exists for this movie")
    trailer_id: int | None = Field(
        default=None,
        description="Id of a playable covering trailer (file present on disk), or null — stream at /stream/trailer/{id}/",
    )


class MovieDetailResponseSchema(SuccessResponseSchema):
    data: MovieDetailSchema


class MovieStreamSchema(Schema):
    stream_url: str = Field(description="Direct streaming URL")
    direct: bool = Field(description="Whether this is a direct stream")
    plex_metadata: dict | None = Field(default=None, description="Plex metadata if available")
    movie: dict = Field(description="Basic movie information")


class MovieStreamResponseSchema(SuccessResponseSchema):
    data: MovieStreamSchema


class GenreStatsSchema(Schema):
    name: str = Field(description="Genre name")
    movie_count: int = Field(description="Number of movies in this genre")


class YearStatsSchema(Schema):
    year: int = Field(description="Release year")
    count: int = Field(description="Number of movies from this year")


class CertStatsSchema(Schema):
    certification: str = Field(description="Certification type")
    count: int = Field(description="Number of movies with this certification")


class MovieStatsSchema(Schema):
    total_movies: int = Field(description="Total number of movies")
    total_size_bytes: int = Field(description="Total library size in bytes")
    total_size_readable: str = Field(description="Total library size in human readable format")
    total_runtime_minutes: int = Field(description="Total runtime in minutes")
    total_runtime_readable: str = Field(description="Total runtime in human readable format")
    average_runtime_minutes: int = Field(description="Average movie runtime in minutes")
    genres: list[GenreStatsSchema] = Field(description="Statistics by genre")
    years: list[YearStatsSchema] = Field(description="Statistics by year")
    certifications: list[CertStatsSchema] = Field(description="Statistics by certification")


class MovieStatsResponseSchema(SuccessResponseSchema):
    data: MovieStatsSchema


class GenreListResponseSchema(SuccessResponseSchema):
    data: list[GenreSchema]


class AudioTrackListResponseSchema(SuccessResponseSchema):
    data: list[AudioTrackSchema]


class SubtitleTrackListResponseSchema(SuccessResponseSchema):
    data: list[SubtitleTrackSchema]


class RatingsOptionsSchema(Schema):
    system: str = Field(description="Active ratings system, e.g. 'BBFC'")
    ratings: list[str] = Field(description="Valid certificates in ascending-severity order")


class RatingsOptionsResponseSchema(SuccessResponseSchema):
    data: RatingsOptionsSchema


class CertificationUpdateSchema(Schema):
    certification: str | None = Field(default=None, description="New certificate, or null/empty to clear")


class CertificationUpdateDataSchema(Schema):
    id: int = Field(description="Movie ID")
    certification: str = Field(description="Certificate in the active system after the update ('' when cleared)")
    certificates: dict[str, str] = Field(description="Full per-system certificate store after the update")


class CertificationUpdateResponseSchema(SuccessResponseSchema):
    data: CertificationUpdateDataSchema


class BulkMovieIdsSchema(Schema):
    ids: list[int] = Field(description="Movie IDs to act on")


class BulkKioskRequestSchema(BulkMovieIdsSchema):
    kiosk_display: bool = Field(description="Kiosk display value to apply to all movies")


class BulkDeleteDataSchema(Schema):
    deleted: int = Field(description="Number of movies removed from the library")
    missing: list[int] = Field(description="Requested IDs that were not found")


class BulkDeleteResponseSchema(SuccessResponseSchema):
    data: BulkDeleteDataSchema


class BulkKioskDataSchema(Schema):
    updated: int = Field(description="Number of movies updated")
    missing: list[int] = Field(description="Requested IDs that were not found")
    kiosk_display: bool = Field(description="Kiosk display value that was applied")


class BulkKioskResponseSchema(SuccessResponseSchema):
    data: BulkKioskDataSchema


class ClearLibrarySchema(Schema):
    total: int = Field(description="Movies currently in the library")
    in_use: int = Field(description="How many of those are referenced by a programme or trailer rule")


class ClearLibraryPreviewResponseSchema(SuccessResponseSchema):
    data: ClearLibrarySchema


class ClearLibraryDataSchema(Schema):
    deleted: int = Field(description="Movies removed from the library")
    in_use: int = Field(description="How many of the removed movies were referenced by a programme or trailer rule")


class ClearLibraryResponseSchema(SuccessResponseSchema):
    data: ClearLibraryDataSchema


class MovieListFilters(Schema):
    search: str | None = Field(default=None, description="Search in title, director, or description")
    genre: str | None = Field(default=None, description="Filter by genre (comma-separated for multiple)")
    year_from: int | None = Field(default=None, description="Filter movies from this year")
    year_to: int | None = Field(default=None, description="Filter movies up to this year")
    runtime_from: int | None = Field(default=None, description="Filter movies with runtime >= this value (minutes)")
    runtime_to: int | None = Field(default=None, description="Filter movies with runtime <= this value (minutes)")
    certification: str | None = Field(default=None, description="Filter by certification")
    resolution: str | None = Field(default=None, description="Filter by resolution")
    kiosk: bool | None = Field(
        default=None,
        description="Filter by kiosk display flag (true = shown on the kiosk, false = hidden from it)",
    )
    has_trailer: bool | None = Field(
        default=None,
        description="Filter by downloaded trailer (true = has one, false = missing)",
    )
    tmdb: str | None = Field(
        default=None,
        description="Filter by TMDB id presence: 'missing' (tmdbid=0), 'present' (tmdbid>0), or unset for any",
    )
    page: int = Field(default=1, description="Page number", ge=1)
    per_page: int = Field(
        default=20,
        description="Items per page (the library page fetches the whole filtered set in one request)",
        ge=1,
        le=10000,
    )
    sort: str = Field(default="title", description="Sort field")
    order: str = Field(default="asc", description="Sort order (asc/desc)")
    random_seed: int | None = Field(
        default=None, description="Seed for sort=random so pagination stays consistent (omit to reshuffle)"
    )


movies_api = Router()


def _trailer_ownership() -> tuple[set[int], set[int]]:
    """(tmdbids carrying a trailer, movie ids with an explicitly linked trailer)."""
    tmdbids = set(Trailer.objects.exclude(tmdbid=0).values_list("tmdbid", flat=True))
    movie_ids = set(
        Trailer.objects.filter(associated_movie__isnull=False).values_list("associated_movie_id", flat=True)
    )
    return tmdbids, movie_ids


@movies_api.get("/list", response={200: MovieListResponseSchema, 500: ErrorResponseSchema})
def list_movies(request: HttpRequest, filters: MovieListFilters = Query(...)):
    per_page = min(filters.per_page, 10000)

    queryset = Movie.objects.all()

    if filters.search:
        queryset = queryset.filter(
            Q(title__icontains=filters.search)
            | Q(director__icontains=filters.search)
            | Q(description__icontains=filters.search)
        )

    if filters.genre:
        genre_list = [g.strip() for g in filters.genre.split(",") if g.strip()]
        if genre_list:
            for genre_name in genre_list:
                queryset = queryset.filter(genres__name__iexact=genre_name)

    if filters.year_from:
        queryset = queryset.filter(year__gte=filters.year_from)

    if filters.year_to:
        queryset = queryset.filter(year__lte=filters.year_to)

    if filters.runtime_from:
        queryset = queryset.filter(runtime__gte=filters.runtime_from)

    if filters.runtime_to:
        queryset = queryset.filter(runtime__lte=filters.runtime_to)

    if filters.certification:
        queryset = queryset.filter(certification__iexact=filters.certification)

    if filters.resolution:
        queryset = queryset.filter(resolution__iexact=filters.resolution)

    if filters.kiosk is not None:
        queryset = queryset.filter(kiosk_display=filters.kiosk)

    # Films synced without a TMDB match carry tmdbid=0.
    if filters.tmdb == "missing":
        queryset = queryset.filter(tmdbid=0)
    elif filters.tmdb == "present":
        queryset = queryset.filter(tmdbid__gt=0)

    trailer_tmdbids, trailer_movie_ids = _trailer_ownership()
    if filters.has_trailer is not None:
        with_trailer_q = Q(tmdbid__in=trailer_tmdbids) | Q(id__in=trailer_movie_ids)
        queryset = queryset.filter(with_trailer_q) if filters.has_trailer else queryset.exclude(with_trailer_q)

    queryset = queryset.prefetch_related(
        "genres",
        Prefetch("audio_tracks", queryset=AudioTrack.objects.order_by("index")),
        Prefetch("subtitle_tracks", queryset=SubtitleTrack.objects.order_by("index")),
    )

    valid_sort_fields = {
        "title": "title",
        "year": "year",
        "date_added": "date_added",
        "runtime": "runtime",
        "file_size": "file_size",
    }

    if filters.sort == "random":
        if filters.random_seed:
            # Deterministic shuffle: for prime P, id → (id·mult) mod P is a
            # bijection, so a fixed seed gives one stable permutation across
            # pages (no dupes/gaps). The seed is spread by a large fixed
            # multiplier first, so even small seeds mix well (a bare id·seed
            # degenerates to id-order until the product wraps P). Omitting the
            # seed reshuffles each request.
            prime = 2147483647  # 2^31 - 1
            mult = (filters.random_seed % prime) * 1327217884 % prime or 1
            queryset = queryset.annotate(_rnd=Mod(F("id") * mult, prime)).order_by("_rnd", "id")
        else:
            queryset = queryset.order_by("?")
    elif filters.sort in valid_sort_fields:
        order_by = valid_sort_fields[filters.sort]
        if filters.order == "desc":
            order_by = f"-{order_by}"
        queryset = queryset.order_by(order_by)
    else:
        queryset = queryset.order_by("title")

    queryset = queryset.distinct()

    all_genres = Genre.objects.all().order_by("name").values_list("name", flat=True)
    all_certifications = (
        Movie.objects.values_list("certification", flat=True)
        .distinct()
        .exclude(certification="")
        .order_by("certification")
    )
    all_resolutions = (
        Movie.objects.values_list("resolution", flat=True).distinct().exclude(resolution="").order_by("resolution")
    )

    paginator = Paginator(queryset, per_page)

    try:
        movies_page = paginator.page(filters.page)
    except EmptyPage:
        # Out-of-range page: clamp to the last page (matches list_media).
        movies_page = paginator.page(paginator.num_pages)

    items = []
    for movie in movies_page:
        items.append(
            MovieListItemSchema(
                id=movie.id,
                title=movie.title,
                year=movie.year,
                director=movie.director,
                runtime=movie.runtime,
                certification=movie.certification,
                resolution=movie.resolution,
                file_size=movie.file_size,
                file_path=movie.file_path,
                description=movie.description,
                tmdbid=movie.tmdbid,
                date_added=movie.date_added.isoformat() if movie.date_added else None,
                thumbnail_url=movie.thumbnail_url,
                genres=[genre.name for genre in movie.genres.all()],
                # len() reads the prefetched cache; .count() would issue a query per movie
                audio_track_count=len(movie.audio_tracks.all()),
                subtitle_track_count=len(movie.subtitle_tracks.all()),
                kiosk_display=movie.kiosk_display,
                stream_url=f"/api/v2/movies/{movie.id}/stream",
                has_trailer=bool(movie.tmdbid and movie.tmdbid in trailer_tmdbids) or movie.id in trailer_movie_ids,
            )
        )

    return Status(
        200,
        MovieListResponseSchema(
            message="Movies retrieved successfully",
            data=MovieListDataSchema(
                items=items,
                pagination=PaginationSchema(
                    page=movies_page.number,
                    per_page=per_page,
                    total=paginator.count,
                    total_pages=paginator.num_pages,
                    has_next=movies_page.has_next(),
                    has_previous=movies_page.has_previous(),
                ),
                filters=FiltersSchema(
                    genres=list(all_genres), certifications=list(all_certifications), resolutions=list(all_resolutions)
                ),
            ),
        ),
    )


@movies_api.get("/stats", response={200: MovieStatsResponseSchema, 500: ErrorResponseSchema})
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

    return Status(
        200,
        MovieStatsResponseSchema(
            message="Movie statistics retrieved successfully",
            data=MovieStatsSchema(
                total_movies=stats["total_movies"] or 0,
                total_size_bytes=stats["total_size"] or 0,
                total_size_readable=_format_file_size(stats["total_size"] or 0),
                total_runtime_minutes=stats["total_runtime"] or 0,
                total_runtime_readable=_format_runtime(stats["total_runtime"] or 0),
                average_runtime_minutes=round(stats["avg_runtime"] or 0),
                genres=[GenreStatsSchema(**genre) for genre in genre_stats],
                years=[YearStatsSchema(**year) for year in year_stats],
                certifications=[CertStatsSchema(**cert) for cert in cert_stats],
            ),
        ),
    )


@movies_api.get("/genres", response={200: GenreListResponseSchema, 500: ErrorResponseSchema})
def list_genres(request: HttpRequest):
    genres = Genre.objects.all().order_by("name")
    return Status(
        200,
        GenreListResponseSchema(
            message="Genres retrieved successfully",
            data=[GenreSchema(id=genre.id, name=genre.name) for genre in genres],
        ),
    )


@movies_api.get("/ratings-options", response={200: RatingsOptionsResponseSchema, 500: ErrorResponseSchema})
def get_ratings_options(request: HttpRequest):
    system = Settings.get_ratings_system()
    return Status(
        200,
        RatingsOptionsResponseSchema(
            message="Ratings options retrieved successfully",
            data=RatingsOptionsSchema(system=system, ratings=list(Settings.get_ratings_order(system))),
        ),
    )


# NOTE: the bulk routes must be registered before the /{movie_id} routes —
# Ninja compiles {movie_id} with a string converter, so a later "/bulk-…"
# path would otherwise be shadowed by it.

BULK_MAX_IDS = 500


def _validate_bulk_ids(ids: list[int]) -> list[int]:
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        raise ValidationError("No movie IDs provided")
    if len(unique_ids) > BULK_MAX_IDS:
        raise ValidationError(f"Too many movie IDs (maximum {BULK_MAX_IDS} per request)")
    return unique_ids


@movies_api.post(
    "/bulk-delete",
    response={200: BulkDeleteResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def bulk_delete_movies(request: HttpRequest, payload: BulkMovieIdsSchema):
    # Removes from the library DB only; does not delete files on disk.
    ids = _validate_bulk_ids(payload.ids)
    existing = set(Movie.objects.filter(id__in=ids).values_list("id", flat=True))
    missing = [movie_id for movie_id in ids if movie_id not in existing]

    if existing:
        Movie.objects.filter(id__in=existing).delete()

    deleted = len(existing)
    noun = "movie" if deleted == 1 else "movies"
    return Status(
        200,
        BulkDeleteResponseSchema(
            message=f"{deleted} {noun} removed from library",
            data=BulkDeleteDataSchema(deleted=deleted, missing=missing),
        ),
    )


@movies_api.post(
    "/bulk-kiosk",
    response={200: BulkKioskResponseSchema, 400: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def bulk_kiosk_movies(request: HttpRequest, payload: BulkKioskRequestSchema):
    ids = _validate_bulk_ids(payload.ids)
    existing = set(Movie.objects.filter(id__in=ids).values_list("id", flat=True))
    missing = [movie_id for movie_id in ids if movie_id not in existing]

    updated = 0
    if existing:
        updated = Movie.objects.filter(id__in=existing).update(kiosk_display=payload.kiosk_display)

    status = "enabled" if payload.kiosk_display else "disabled"
    noun = "movie" if updated == 1 else "movies"
    return Status(
        200,
        BulkKioskResponseSchema(
            message=f"Kiosk display {status} for {updated} {noun}",
            data=BulkKioskDataSchema(updated=updated, missing=missing, kiosk_display=payload.kiosk_display),
        ),
    )


def _movies_in_use_count() -> int:
    """Distinct movies referenced by a programme block (feature) or a trailer rule."""
    from cinefin.api.models import ProgrammeBlock, TrailerRule

    used = set(ProgrammeBlock.objects.filter(movie__isnull=False).values_list("movie_id", flat=True))
    used |= set(TrailerRule.objects.filter(reference_movie__isnull=False).values_list("reference_movie_id", flat=True))
    return len(used)


# Registered before /{movie_id} (string converter) so the literal path wins.
@movies_api.get("/clear-library", response={200: ClearLibraryPreviewResponseSchema, 500: ErrorResponseSchema})
def clear_library_preview(request: HttpRequest):
    """Counts for the clear-library confirmation (total + how many are in use)."""
    return Status(
        200,
        ClearLibraryPreviewResponseSchema(
            message="Library summary",
            data=ClearLibrarySchema(total=Movie.objects.count(), in_use=_movies_in_use_count()),
        ),
    )


@movies_api.post("/clear-library", response={200: ClearLibraryResponseSchema, 500: ErrorResponseSchema})
def clear_library(request: HttpRequest):
    """Remove every movie from the library (DB only — playout is streaming, no files on disk).

    Movies referenced by a programme/trailer rule are SET_NULL, so those slots empty out
    rather than deleting the programme; the confirmation warns with `in_use`."""
    in_use = _movies_in_use_count()
    total = Movie.objects.count()
    Movie.objects.all().delete()
    noun = "movie" if total == 1 else "movies"
    return Status(
        200,
        ClearLibraryResponseSchema(
            message=f"{total} {noun} removed from library",
            data=ClearLibraryDataSchema(deleted=total, in_use=in_use),
        ),
    )


@movies_api.get(
    "/{movie_id}", response={200: MovieDetailResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def get_movie_detail(request: HttpRequest, movie_id: int):
    try:
        movie = Movie.objects.prefetch_related(
            "genres",
            Prefetch("audio_tracks", queryset=AudioTrack.objects.order_by("index")),
            Prefetch("subtitle_tracks", queryset=SubtitleTrack.objects.order_by("index")),
        ).get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None

    audio_tracks = [
        AudioTrackSchema(
            id=track.id,
            language=track.language,
            codec=track.codec,
            channels=track.channels,
            index=track.index,
            title=track.title,
        )
        for track in movie.audio_tracks.all()
    ]

    subtitle_tracks = [
        SubtitleTrackSchema(id=track.id, language=track.language, forced=track.forced, sdh=track.sdh, index=track.index)
        for track in movie.subtitle_tracks.all()
    ]

    # Video tech info as reported by the media server at sync time (never a local scan).
    video_info = None
    if movie.video_codec or movie.video_width or movie.video_bitrate:
        video_info = VideoInfoSchema(
            codec=movie.video_codec or None,
            width=movie.video_width or None,
            height=movie.video_height or None,
            framerate=movie.video_framerate or None,
            bitrate=movie.video_bitrate or None,
        )

    # has_trailer = any covering row; trailer_id is set only when one has a
    # file on disk. A linked trailer wins over a tmdbid-only match.
    trailer_q = Q(associated_movie_id=movie.id)
    if movie.tmdbid:
        trailer_q |= Q(tmdbid=movie.tmdbid)
    covering = list(Trailer.objects.filter(trailer_q).order_by(F("associated_movie_id").desc(nulls_last=True)))
    playable = next((t for t in covering if t.file_path and os.path.exists(usermedia_abs_path(t.file_path))), None)

    movie_detail = MovieDetailSchema(
        id=movie.id,
        title=movie.title,
        year=movie.year,
        director=movie.director,
        runtime=movie.runtime,
        certification=movie.certification,
        certificates=movie.certificates or {},
        resolution=movie.resolution,
        file_size=movie.file_size,
        file_path=movie.file_path,
        description=movie.description,
        tmdbid=movie.tmdbid,
        date_added=movie.date_added.isoformat() if movie.date_added else None,
        thumbnail_url=movie.thumbnail_url,
        kiosk_display=movie.kiosk_display,
        stream_url=f"/api/v2/movies/{movie.id}/stream",
        genres=[genre.id for genre in movie.genres.all()],
        audio_tracks=audio_tracks,
        subtitle_tracks=subtitle_tracks,
        video_info=video_info,
        has_trailer=bool(covering),
        trailer_id=playable.id if playable else None,
    )

    return Status(200, MovieDetailResponseSchema(message="Movie details retrieved successfully", data=movie_detail))


@movies_api.get("/{movie_id}/poster", response={200: None, 302: None, 404: ErrorResponseSchema})
def get_movie_poster(request: HttpRequest, movie_id: int):
    # Proxied live from the media server (never synced to disk); the art key
    # doubles as the ETag. Falls back to the bundled default poster on any failure.
    try:
        movie = Movie.objects.select_related("sync_source").get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None

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


@movies_api.get(
    "/{movie_id}/stream",
    response={
        200: MovieStreamResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def stream_movie(request: HttpRequest, movie_id: int):
    try:
        movie = Movie.objects.select_related("sync_source").get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None

    # Always returns a dict with a stream_url (falls back to a Django-served
    # local URL internally), so there is no error branch to handle here.
    result = streaming_service.get_movie_stream_url(movie)

    return Status(
        200,
        MovieStreamResponseSchema(
            message="Movie stream URL retrieved successfully",
            data=MovieStreamSchema(
                stream_url=result["stream_url"],
                direct=result["direct"],
                plex_metadata=result.get("plex_metadata"),
                movie={
                    "id": movie.id,
                    "title": movie.title,
                    "year": movie.year,
                    "runtime": movie.runtime,
                    "resolution": movie.resolution,
                    "file_size": movie.file_size,
                },
            ),
        ),
    )


@movies_api.get(
    "/{movie_id}/audio_tracks",
    response={200: AudioTrackListResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def get_movie_audio_tracks(request: HttpRequest, movie_id: int):
    try:
        movie = Movie.objects.get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None

    tracks = AudioTrack.objects.filter(movie=movie).order_by("index")

    return Status(
        200,
        AudioTrackListResponseSchema(
            message="Audio tracks retrieved successfully",
            data=[
                AudioTrackSchema(
                    id=track.id,
                    index=track.index,
                    language=track.language,
                    codec=track.codec,
                    channels=track.channels,
                    title=track.title,
                )
                for track in tracks
            ],
        ),
    )


@movies_api.get(
    "/{movie_id}/subtitle_tracks",
    response={200: SubtitleTrackListResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def get_movie_subtitle_tracks(request: HttpRequest, movie_id: int):
    try:
        movie = Movie.objects.get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None

    tracks = SubtitleTrack.objects.filter(movie=movie).order_by("index")

    return Status(
        200,
        SubtitleTrackListResponseSchema(
            message="Subtitle tracks retrieved successfully",
            data=[
                SubtitleTrackSchema(
                    id=track.id, index=track.index, language=track.language, forced=track.forced, sdh=track.sdh
                )
                for track in tracks
            ],
        ),
    )


def _format_file_size(size_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def _format_runtime(minutes):
    if not minutes:
        return "0 minutes"

    hours = minutes // 60
    mins = minutes % 60

    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins} minutes"


@movies_api.delete(
    "/{movie_id}", response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema}
)
def delete_movie(request: HttpRequest, movie_id: int):
    # Removes from the library DB only; does not delete the file on disk.
    try:
        movie = Movie.objects.get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None

    title = movie.title
    movie.delete()
    return Status(200, MessageResponseSchema(message=f"'{title}' removed from library"))


@movies_api.post(
    "/{movie_id}/toggle_kiosk",
    response={200: MessageResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def toggle_movie_kiosk(request: HttpRequest, movie_id: int):
    try:
        movie = Movie.objects.get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None

    movie.kiosk_display = not movie.kiosk_display
    movie.save()

    status = "enabled" if movie.kiosk_display else "disabled"
    return Status(200, MessageResponseSchema(message=f"Kiosk display {status} for '{movie.title}'"))


@movies_api.patch(
    "/{movie_id}/certification",
    response={
        200: CertificationUpdateResponseSchema,
        400: ErrorResponseSchema,
        404: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def update_movie_certification(request: HttpRequest, movie_id: int, payload: CertificationUpdateSchema):
    try:
        movie = Movie.objects.get(id=movie_id)
    except Movie.DoesNotExist:
        raise NotFoundError("Movie not found") from None

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

    # Re-derive the denormalised scalar via the single source of truth, scoped
    # to this one row (full-table denormalize belongs to ratings-system switches).
    denormalize_certificate(movie, system)

    return Status(
        200,
        CertificationUpdateResponseSchema(
            message="Certificate updated successfully",
            data=CertificationUpdateDataSchema(
                id=movie.id,
                certification=movie.certification or "",
                certificates=movie.certificates or {},
            ),
        ),
    )
