import importlib.util
import logging
import os
from typing import Any

from django.db.models import Count, Q
from django.http import HttpRequest
from ninja import Field, File, Form, Query, Router, Schema, Status, UploadedFile

from cinefin.api import ratings
from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Genre, Job, Settings, Trailer, TrailerTag
from cinefin.api.schemas.base import ErrorResponseSchema, SuccessResponseSchema
from cinefin.api.services.trailer_service import TrailerService
from cinefin.api.utils.media_paths import usermedia_abs_path

logger = logging.getLogger(__name__)


class GenreSchema(Schema):
    id: int = Field(..., description="Genre ID")
    name: str = Field(..., description="Genre name")


class TrailerTagSchema(Schema):
    id: int = Field(..., description="Trailer tag ID")
    name: str = Field(..., description="Trailer tag name")


class TrailerListItemSchema(Schema):
    id: int = Field(..., description="Trailer ID")
    title: str = Field(..., description="Trailer title")
    year: int | None = Field(None, description="Release year")
    month: int | None = Field(None, description="Release month")
    duration: int | None = Field(None, description="Duration in seconds")
    content_rating: str | None = Field(None, description="Content rating")
    tmdbid: int | None = Field(None, description="TMDB ID")
    file_path: str | None = Field(None, description="Path to trailer file")
    director: str | None = Field(None, description="Director name")
    genres: list[str] = Field([], description="List of genre names")
    trailer_tags: list[TrailerTagSchema] = Field([], description="Trailer tags (trailer-library vocabulary)")


class AssociatedMovieSchema(Schema):
    id: int = Field(..., description="Movie ID")
    title: str = Field(..., description="Movie title")
    year: int | None = Field(None, description="Movie release year")
    tmdbid: int | None = Field(None, description="TMDB ID")


class TrailerDetailSchema(Schema):
    id: int = Field(..., description="Trailer ID")
    title: str = Field(..., description="Trailer title")
    year: int | None = Field(None, description="Release year")
    month: int | None = Field(None, description="Release month")
    duration: int | None = Field(None, description="Duration in seconds")
    content_rating: str | None = Field(None, description="Content rating")
    tmdbid: int | None = Field(None, description="TMDB ID")
    file_path: str | None = Field(None, description="Path to trailer file")
    director: str | None = Field(None, description="Director name")
    certificates: dict[str, str] = Field({}, description="Certificates per ratings system, e.g. {'BBFC': '15'}")
    rating_lookups: dict[str, str] = Field({}, description="Provider lookup outcome per system (matched/unmatched)")
    associated_movie: AssociatedMovieSchema | None = Field(None, description="Associated movie details")
    genres: list[GenreSchema] = Field([], description="List of genres")
    trailer_tags: list[TrailerTagSchema] = Field([], description="Trailer tags (trailer-library vocabulary)")


class TrailerPaginationSchema(Schema):
    total: int = Field(..., description="Total number of trailers")
    limit: int = Field(..., description="Maximum items per page")
    offset: int = Field(..., description="Number of items skipped")
    has_more: bool = Field(..., description="Whether more items are available")


class TrailerListDataSchema(Schema):
    trailers: list[TrailerListItemSchema] = Field(..., description="List of trailers")
    pagination: TrailerPaginationSchema = Field(..., description="Pagination information")


class TrailerListResponseSchema(SuccessResponseSchema):
    data: TrailerListDataSchema = Field(..., description="Trailer list data")


class TrailerDetailDataSchema(Schema):
    trailer: TrailerDetailSchema = Field(..., description="Trailer details")


class TrailerDetailResponseSchema(SuccessResponseSchema):
    data: TrailerDetailDataSchema = Field(..., description="Trailer detail data")


class TrailerQueryParams(Schema):
    year: int | None = Field(None, description="Filter by release year")
    rating: str | None = Field(None, description="Filter by content rating")
    limit: int = Field(50, description="Maximum number of items to return")
    offset: int = Field(0, description="Number of items to skip")


class FetchRequestSchema(Schema):
    type: str = Field(
        "discover",
        description=(
            'Fetch operation type: "discover" (TMDB search by date/genre/rating), '
            '"library" (movies missing trailers) or "single" (one title by TMDB id)'
        ),
    )
    tmdbid: int | None = Field(None, description='TMDB id of the movie to fetch (required for type "single")')
    video_key: str | None = Field(
        None, description="YouTube video key to download (single fetch only) — omit for the automatic pick"
    )
    replace: bool = Field(
        False, description="Re-download over an existing trailer instead of skipping it (single fetch only)"
    )
    year: int | None = Field(None, description="Specific year to fetch")
    year_from: int | None = Field(None, description="Start of year range")
    year_to: int | None = Field(None, description="End of year range")
    months_ahead: int = Field(6, description="Number of months ahead for upcoming trailers")
    limit: int = Field(50, description="Maximum number of trailers to fetch")
    sort_by: str | None = Field("popularity.desc", description="Sort order")
    genres: list[int] | None = Field(None, description="Filter by genre IDs")
    min_rating: float | None = Field(None, description="Minimum TMDB rating")
    certification: str | None = Field(None, description="Content certification filter")


class PreviewTrailersSchema(Schema):
    year_from: int | None = Field(None, description="Start of year range")
    year_to: int | None = Field(None, description="End of year range")
    limit: int = Field(50, description="Maximum number of trailers to preview", ge=1, le=500)
    sort_by: str = Field("popularity.desc", description="Sort order")
    genres: list[int] | None = Field(None, description="Filter by genre IDs")
    min_rating: float | None = Field(None, description="Minimum TMDB rating", ge=0, le=10)
    certification: str | None = Field(None, description="Content certification filter")


class PreviewTrailerItemSchema(Schema):
    tmdb_id: int = Field(..., description="TMDB ID")
    title: str = Field(..., description="Movie title")
    year: int | None = Field(None, description="Release year")
    month: int | None = Field(None, description="Release month")
    genres: list[str] = Field([], description="Genre names")
    rating: float | None = Field(None, description="TMDB rating")
    popularity: float | None = Field(None, description="TMDB popularity score")
    certification: str | None = Field(None, description="Content certification")
    already_downloaded: bool = Field(False, description="Whether trailer already exists in library")


class PreviewTrailersDataSchema(Schema):
    trailers: list[PreviewTrailerItemSchema] = Field(..., description="Trailers that would be fetched")
    total_found: int = Field(..., description="Total matching criteria")
    will_fetch: int = Field(..., description="Trailers that will be fetched (after limit)")
    already_have: int = Field(..., description="Trailers already in library")


class PreviewTrailersResponseSchema(SuccessResponseSchema):
    data: PreviewTrailersDataSchema = Field(..., description="Preview data")


class TrailerStatsDataSchema(Schema):
    statistics: dict[str, Any] = Field(..., description="Trailer statistics")


class TrailerStatsResponseSchema(SuccessResponseSchema):
    data: TrailerStatsDataSchema = Field(..., description="Trailer statistics data")


class TrailerSettingsSchema(Schema):
    tmdb_api_key: str | None = Field(None, description="TMDB API key")
    download_quality: str | None = Field(None, description="Video quality: 720, 1080, 1440, 2160, best")
    rating_lookup_enabled: bool | None = Field(
        None, description="Backfill missing certificates from the classification bodies' websites"
    )
    upcoming_months_ahead: int | None = Field(None, description="Months ahead for upcoming releases", ge=1, le=24)
    filename_template: str | None = Field(None, description="Filename template (e.g. {title} ({year}) [tmdb-{tmdbid}])")
    folder_template: str | None = Field(None, description="Folder template (e.g. {year})")


class TrailerSettingsDataSchema(Schema):
    settings: dict[str, Any] = Field(..., description="Current trailer settings")
    naming_tokens: list[dict[str, str]] = Field(..., description="Available naming template tokens")
    dependencies: dict[str, bool] = Field(..., description="Optional dependency availability")
    supported_qualities: list[str] = Field(..., description="Supported download quality values")


class TrailerSettingsResponseSchema(SuccessResponseSchema):
    data: TrailerSettingsDataSchema = Field(..., description="Trailer settings data")


trailer_api = Router()


@trailer_api.get("/settings", tags=["Trailers"])
def get_trailer_settings(request: HttpRequest):
    from cinefin.api.services import trailer_naming as tn

    current = Settings.get("trailers") or {}
    defaults = Settings.DEFAULTS.get("trailers", {})
    merged = {**defaults, **current}

    return Status(
        200,
        TrailerSettingsResponseSchema(
            message="Trailer settings retrieved",
            data=TrailerSettingsDataSchema(
                settings=merged,
                naming_tokens=tn.AVAILABLE_TOKENS,
                dependencies={
                    "rating_provider_available": ratings.get_provider(Settings.get_ratings_system()) is not None,
                    "yt_dlp_available": _check_ytdlp_availability(),
                    "tmdb_available": _check_tmdb_availability(),
                },
                supported_qualities=["720", "1080", "1440", "2160", "best"],
            ),
        ),
    )


@trailer_api.post("/settings", tags=["Trailers"])
def update_trailer_settings(request: HttpRequest, data: TrailerSettingsSchema):
    current = dict(Settings.get("trailers") or {})

    updates = {k: v for k, v in data.dict().items() if v is not None}
    current.update(updates)
    Settings.set("trailers", current)

    return Status(200, {"success": True, "message": "Trailer settings saved", "data": {"settings": current}})


@trailer_api.get("/list", response={200: TrailerListResponseSchema, 500: ErrorResponseSchema})
def list_trailers(request: HttpRequest, filters: TrailerQueryParams = Query(...)):
    queryset = Trailer.objects.all().order_by("-year", "title")
    if filters.year:
        queryset = queryset.filter(year=filters.year)
    if filters.rating:
        queryset = queryset.filter(content_rating=filters.rating)
    total_count = queryset.count()
    trailers = queryset.prefetch_related("genres", "trailer_tags")[filters.offset : filters.offset + filters.limit]
    trailer_data = []
    for trailer in trailers:
        trailer_data.append(
            {
                "id": trailer.id,
                "title": trailer.title,
                "year": trailer.year,
                "month": trailer.month,
                "duration": trailer.duration,
                "content_rating": trailer.content_rating,
                "tmdbid": trailer.tmdbid,
                "file_path": trailer.file_path,
                "director": trailer.director,
                "genres": [genre.name for genre in trailer.genres.all()],
                "trailer_tags": [{"id": t.id, "name": t.name} for t in trailer.trailer_tags.all()],
            }
        )
    return Status(
        200,
        TrailerListResponseSchema(
            message="Trailers retrieved successfully",
            data=TrailerListDataSchema(
                trailers=trailer_data,
                pagination=TrailerPaginationSchema(
                    total=total_count,
                    limit=filters.limit,
                    offset=filters.offset,
                    has_more=filters.offset + filters.limit < total_count,
                ),
            ),
        ),
    )


@trailer_api.get(
    "/detail/{trailer_id}",
    response={200: TrailerDetailResponseSchema, 404: ErrorResponseSchema, 500: ErrorResponseSchema},
)
def get_trailer_detail(request: HttpRequest, trailer_id: int):
    try:
        trailer = Trailer.objects.get(id=trailer_id)
    except Trailer.DoesNotExist:
        raise NotFoundError("Trailer not found", error_code="TRAILER_NOT_FOUND") from None
    associated_movie = None
    try:
        movie = trailer.associated_movie
        if movie:
            associated_movie = {"id": movie.id, "title": movie.title, "year": movie.year, "tmdbid": movie.tmdbid}
    except Exception:
        pass
    trailer_data = {
        "id": trailer.id,
        "title": trailer.title,
        "year": trailer.year,
        "month": trailer.month,
        "duration": trailer.duration,
        "content_rating": trailer.content_rating,
        "tmdbid": trailer.tmdbid,
        "file_path": trailer.file_path,
        "director": trailer.director,
        "certificates": trailer.certificates or {},
        "rating_lookups": trailer.rating_lookups or {},
        "associated_movie": associated_movie,
        "genres": [{"id": g.id, "name": g.name} for g in trailer.genres.all()],
        "trailer_tags": [{"id": t.id, "name": t.name} for t in trailer.trailer_tags.all()],
    }
    return Status(
        200,
        TrailerDetailResponseSchema(
            message="Trailer details retrieved successfully", data=TrailerDetailDataSchema(trailer=trailer_data)
        ),
    )


def _job_dict(job: Job, include_log: bool = False) -> dict:
    return job.serialize(include_log=include_log)


def _start_job(operation: str, params: dict):
    from cinefin.api.services import trailer_jobs

    try:
        job = trailer_jobs.start_job(operation, params)
    except RuntimeError as e:
        raise UnprocessableEntityError(str(e), error_code="TRAILER_JOB_RUNNING") from e
    except ValueError as e:
        raise ValidationError(str(e), error_code="INVALID_OPERATION") from e
    return _ok({"job": _job_dict(job)})


_JOB_RESPONSES = {
    200: SuccessResponseSchema,
    400: ErrorResponseSchema,
    404: ErrorResponseSchema,
    422: ErrorResponseSchema,
    500: ErrorResponseSchema,
}


@trailer_api.post("/fetch", response=_JOB_RESPONSES)
def fetch_trailers(request: HttpRequest, data: FetchRequestSchema):
    if data.type not in ("discover", "library", "single"):
        raise ValidationError(f"Unknown fetch type: {data.type}", error_code="INVALID_FETCH_TYPE")
    if data.type == "single" and not data.tmdbid:
        raise ValidationError("A tmdbid is required for a single-title fetch", error_code="TMDBID_REQUIRED")

    if not TrailerService().tmdb.api_key:
        raise ValidationError(
            "TMDB API key not configured. Set it under Settings → Library source.", error_code="NO_TMDB_API_KEY"
        )

    params = {}
    if data.type == "discover":
        params = {
            "year": data.year,
            "months_ahead": data.months_ahead,
            "year_from": data.year_from,
            "year_to": data.year_to,
            "limit": data.limit,
            "sort_by": data.sort_by,
            "genres": data.genres,
            "min_rating": data.min_rating,
            "certification": data.certification,
        }
    elif data.type == "single":
        params = {"tmdbid": data.tmdbid, "video_key": data.video_key, "replace": data.replace}
    return _start_job(data.type, params)


@trailer_api.post("/verify", response=_JOB_RESPONSES)
def verify_trailers(request: HttpRequest):
    return _start_job("verify", {})


class RatingsUpdateSchema(Schema):
    scope: str = Field("trailers", pattern="^(movies|trailers|all)$")


@trailer_api.post("/ratings/update", response=_JOB_RESPONSES)
def update_trailer_ratings(request: HttpRequest, payload: RatingsUpdateSchema | None = None):
    scope = payload.scope if payload else "trailers"
    return _start_job("ratings", {"scope": scope})


@trailer_api.get("/jobs/current", response=_JOB_RESPONSES)
def current_trailer_job(request: HttpRequest):
    """The active trailer job (or most recent), with full log — used on page load."""
    job = (
        Job.trailer.filter(state__in=Job.ACTIVE_STATES).order_by("-created_at").first()
        or Job.trailer.order_by("-created_at").first()
    )
    return _ok({"job": _job_dict(job, include_log=True) if job else None})


@trailer_api.get("/jobs/{job_id}", response=_JOB_RESPONSES)
def get_trailer_job(request: HttpRequest, job_id: int):
    try:
        job = Job.trailer.get(pk=job_id)
    except Job.DoesNotExist:
        raise NotFoundError("Trailer job not found", error_code="TRAILER_JOB_NOT_FOUND") from None
    return _ok({"job": _job_dict(job, include_log=True)})


@trailer_api.post("/jobs/{job_id}/cancel", response=_JOB_RESPONSES)
def cancel_trailer_job(request: HttpRequest, job_id: int):
    updated = Job.trailer.filter(pk=job_id, state__in=Job.ACTIVE_STATES).update(
        cancel_requested=True, state=Job.STATE_CANCELLING
    )
    if not updated:
        raise NotFoundError("No active trailer job to cancel", error_code="TRAILER_JOB_NOT_ACTIVE")
    return _ok({"cancelling": True})


@trailer_api.post(
    "/preview",
    response={
        200: PreviewTrailersResponseSchema,
        400: ErrorResponseSchema,
        422: ErrorResponseSchema,
        500: ErrorResponseSchema,
    },
)
def preview_trailers(request: HttpRequest, filters: PreviewTrailersSchema):
    from datetime import datetime

    from tmdbv3api import Discover, TMDb

    tmdb_api_key = Settings.get("trailers.tmdb_api_key") or ""
    if not tmdb_api_key:
        raise ValidationError(
            "TMDB API key not configured. Set it under Settings → Library source.", error_code="NO_TMDB_API_KEY"
        )

    tmdb = TMDb()
    tmdb.api_key = tmdb_api_key
    discover = Discover()

    current_year = datetime.now().year
    year_from = filters.year_from if filters.year_from else current_year
    year_to = filters.year_to if filters.year_to else current_year + 1

    try:
        discover_params = {
            "sort_by": str(filters.sort_by),
            "include_adult": False,
            "region": "GB",
            "primary_release_date.gte": f"{year_from}-01-01",
            "primary_release_date.lte": f"{year_to}-12-31",
        }
        if filters.genres:
            discover_params["with_genres"] = ",".join(str(g) for g in filters.genres)
        if filters.min_rating:
            discover_params["vote_average.gte"] = float(filters.min_rating)
            discover_params["vote_count.gte"] = 10
        if filters.certification:
            # US for MPAA installs, GB otherwise — must match fetch_discover_trailers.
            discover_params["certification_country"] = "US" if Settings.get_ratings_system() == "MPAA" else "GB"
            discover_params["certification"] = str(filters.certification)

        logger.info(f"Preview discover params: {discover_params}")
        results = discover.discover_movies(discover_params)
        results_list = list(results) if results else []

        existing_tmdb_ids = set(Trailer.objects.values_list("tmdbid", flat=True))
        preview_items = []
        already_have_count = 0
        limit = int(filters.limit)

        GENRE_MAP = {
            28: "Action",
            12: "Adventure",
            16: "Animation",
            35: "Comedy",
            80: "Crime",
            99: "Documentary",
            18: "Drama",
            10751: "Family",
            14: "Fantasy",
            36: "History",
            27: "Horror",
            10402: "Music",
            9648: "Mystery",
            10749: "Romance",
            878: "Science Fiction",
            10770: "TV Movie",
            53: "Thriller",
            10752: "War",
            37: "Western",
        }

        for movie in results_list[:limit]:
            try:

                def safe_get(obj, attr, default=None):
                    return obj.get(attr, default) if isinstance(obj, dict) else getattr(obj, attr, default)

                movie_id = safe_get(movie, "id")
                if not movie_id:
                    continue
                already_downloaded = movie_id in existing_tmdb_ids
                if already_downloaded:
                    already_have_count += 1

                year = month = None
                release_date = safe_get(movie, "release_date")
                if release_date:
                    try:
                        parsed = datetime.strptime(str(release_date), "%Y-%m-%d")
                        year, month = parsed.year, parsed.month
                    except Exception:
                        pass

                genre_ids = safe_get(movie, "genre_ids", [])
                genre_names = [GENRE_MAP[int(gid)] for gid in genre_ids if int(gid) in GENRE_MAP]

                preview_items.append(
                    {
                        "tmdb_id": movie_id,
                        "title": safe_get(movie, "title", "Unknown"),
                        "year": year,
                        "month": month,
                        "genres": genre_names,
                        "rating": safe_get(movie, "vote_average"),
                        "popularity": safe_get(movie, "popularity"),
                        "certification": None,
                        "already_downloaded": already_downloaded,
                    }
                )
            except Exception as e:
                logger.warning(f"Error processing movie in preview: {e}")
                continue

        return Status(
            200,
            PreviewTrailersResponseSchema(
                message=f"Found {len(results_list)} trailers matching criteria",
                data=PreviewTrailersDataSchema(
                    trailers=preview_items,
                    total_found=len(results_list),
                    will_fetch=min(len(results_list), filters.limit) - already_have_count,
                    already_have=already_have_count,
                ),
            ),
        )
    except Exception as e:
        logger.exception("Failed to preview trailers")
        raise UnprocessableEntityError(f"Failed to preview trailers: {str(e)}", error_code="PREVIEW_FAILED") from e


class MatchTestTrailerSchema(Schema):
    id: int
    title: str
    year: int | None = None
    content_rating: str = ""
    will_play: bool = Field(..., description="Among the top `requested` that the rule would actually play")


class MatchTestDataSchema(Schema):
    movie_id: int | None = None
    movie_title: str | None = None
    matched: int = Field(..., description="Trailers satisfying the (hard) criteria")
    requested: int = Field(..., description="How many the rule asks for")
    trailers: list[MatchTestTrailerSchema] = Field(..., description="Ranked candidates, capped at 50")


class MatchTestResponseSchema(SuccessResponseSchema):
    data: MatchTestDataSchema


@trailer_api.get("/match-test", response={200: MatchTestResponseSchema, 404: ErrorResponseSchema})
def match_test(
    request: HttpRequest,
    movie_id: int | None = None,
    genre_ids: str = "",
    certificate_ceiling: str = "",
    year_from: int | None = None,
    year_to: int | None = None,
    tag_id: int | None = None,
    count: int = 3,
):
    """Dry-run a trailer rule's matching; flags the top `count` candidates that would play."""
    from cinefin.api.models import Movie, TrailerTag
    from cinefin.api.services.trailer_matching import Criteria, _rank, build_pool

    movie = None
    if movie_id:
        try:
            movie = Movie.objects.get(pk=movie_id)
        except Movie.DoesNotExist:
            raise NotFoundError("Movie not found") from None

    tag = TrailerTag.objects.filter(pk=tag_id).first() if tag_id else None
    gids = [int(g) for g in genre_ids.split(",") if g.strip().isdigit()]
    criteria = Criteria(
        reference_movie=movie,
        genre_ids=gids,
        certificate_ceiling=certificate_ceiling or "",
        year_from=year_from,
        year_to=year_to,
        tag=tag,
    )

    ranked = _rank(build_pool(criteria), criteria)
    top_ids = {t.id for t in ranked[:count]}

    return Status(
        200,
        MatchTestResponseSchema(
            data=MatchTestDataSchema(
                movie_id=movie.id if movie else None,
                movie_title=movie.title if movie else None,
                matched=len(ranked),
                requested=count,
                trailers=[
                    MatchTestTrailerSchema(
                        id=t.id,
                        title=t.title,
                        year=t.year,
                        content_rating=t.content_rating or "",
                        will_play=t.id in top_ids,
                    )
                    for t in ranked[:50]
                ],
            )
        ),
    )


@trailer_api.get("/stats", response={200: TrailerStatsResponseSchema, 500: ErrorResponseSchema})
def get_trailer_stats(request: HttpRequest):
    stats = TrailerService().get_statistics()
    return Status(
        200,
        TrailerStatsResponseSchema(
            message="Trailer statistics retrieved successfully", data=TrailerStatsDataSchema(statistics=stats)
        ),
    )


def _ok(data=None):
    return {"success": True, "data": data}


def _valid_ratings() -> set:
    from cinefin.api.models import Settings

    return Settings.get_valid_ratings()


def _trailer_row(t, exists, valid):
    return {
        "id": t.id,
        "title": t.title,
        "year": t.year,
        "month": t.month,
        "duration": t.duration,
        "content_rating": t.content_rating,
        "rating_ok": bool(t.content_rating) and t.content_rating in valid,
        "tmdbid": t.tmdbid,
        "director": t.director,
        "file_path": t.file_path,
        "file_name": os.path.basename(t.file_path) if t.file_path else "",
        "file_exists": exists,
        "stream_url": f"/stream/trailer/{t.id}/",
        "has_movie": t.associated_movie_id is not None,
        "genres": [g.name for g in t.genres.all()],
        "trailer_tags": [{"id": tg.id, "name": tg.name} for tg in t.trailer_tags.all()],
    }


@trailer_api.get("/library")
def trailer_library(
    request: HttpRequest,
    q: str = "",
    rating: str = "",
    genre: str = "",
    year: int | None = None,
    tag: int | None = None,
    missing: bool = False,
    rating_issue: bool = False,
    sort: str = "-year",
    limit: int = 60,
    offset: int = 0,
):
    valid = _valid_ratings()
    base = Trailer.objects.all()
    if q:
        base = base.filter(Q(title__icontains=q) | Q(director__icontains=q))
    if rating:
        base = base.filter(content_rating=rating)
    if genre:
        base = base.filter(genres__name=genre)
    if year:
        base = base.filter(year=year)
    if tag:
        base = base.filter(trailer_tags__id=tag)
    if rating_issue:
        base = base.filter(Q(content_rating="") | ~Q(content_rating__in=valid))
    allowed_sorts = {"-year", "year", "title", "-title", "content_rating", "-content_rating"}
    order = sort if sort in allowed_sorts else "-year"
    base = base.distinct().order_by(order, "title").prefetch_related("genres", "trailer_tags")

    all_rows = list(Trailer.objects.values("file_path", "content_rating"))
    total_lib = len(all_rows)
    with_file = sum(1 for t in all_rows if t["file_path"] and os.path.exists(t["file_path"]))
    issues = sum(1 for t in all_rows if not t["content_rating"] or t["content_rating"] not in valid)
    present_ratings = sorted({(t["content_rating"] or "") for t in all_rows} - {""})
    genres = sorted(Genre.objects.filter(trailer__isnull=False).values_list("name", flat=True).distinct())
    trailer_tags = [
        {"id": t.id, "name": t.name, "trailer_count": t.n}
        for t in TrailerTag.objects.annotate(n=Count("trailers")).order_by("name")
    ]

    rows = []
    for t in base:
        exists = bool(t.file_path and os.path.exists(usermedia_abs_path(t.file_path)))
        if missing and exists:
            continue
        rows.append((t, exists))

    page = rows[offset : offset + limit]
    trailers = [_trailer_row(t, exists, valid) for (t, exists) in page]

    return _ok(
        {
            "trailers": trailers,
            "total": len(rows),
            "limit": limit,
            "offset": offset,
            "stats": {
                "total": total_lib,
                "with_file": with_file,
                "missing": total_lib - with_file,
                "rating_issues": issues,
            },
            "facets": {
                "ratings": present_ratings,
                "genres": genres,
                "valid_ratings": sorted(valid),
                "trailer_tags": trailer_tags,
            },
        }
    )


def _trailer_detail(t, valid):
    exists = bool(t.file_path and os.path.exists(usermedia_abs_path(t.file_path)))
    data = _trailer_row(t, exists, valid)
    data["certificates"] = t.certificates or {}
    data["rating_lookups"] = t.rating_lookups or {}
    movie = t.associated_movie
    data["associated_movie"] = (
        {"id": movie.id, "title": movie.title, "year": movie.year, "tmdbid": movie.tmdbid} if movie else None
    )
    return data


@trailer_api.get("/library/{int:trailer_id}")
def trailer_library_detail(request: HttpRequest, trailer_id: int):
    try:
        t = Trailer.objects.get(id=trailer_id)
    except Trailer.DoesNotExist:
        raise NotFoundError("Trailer not found", error_code="TRAILER_NOT_FOUND") from None
    return _ok({"trailer": _trailer_detail(t, _valid_ratings())})


class TrailerPatchSchema(Schema):
    content_rating: str | None = None


@trailer_api.patch("/library/{int:trailer_id}")
def update_trailer(request: HttpRequest, trailer_id: int, payload: TrailerPatchSchema):
    try:
        t = Trailer.objects.get(id=trailer_id)
    except Trailer.DoesNotExist:
        raise NotFoundError("Trailer not found", error_code="TRAILER_NOT_FOUND") from None
    if payload.content_rating is not None:
        # A manual edit targets the ACTIVE display system's certificate slot.
        system = Settings.get_ratings_system()
        value = payload.content_rating.strip()
        t.set_certificate(system, value, active_system=system)
        if value:
            t.mark_rating_lookup(system, "matched")
    t.save()
    return _ok({"trailer": _trailer_detail(t, _valid_ratings())})


@trailer_api.delete("/library/{int:trailer_id}")
def delete_trailer(request: HttpRequest, trailer_id: int, delete_file: bool = False):
    try:
        trailer = Trailer.objects.get(id=trailer_id)
    except Trailer.DoesNotExist:
        raise NotFoundError("Trailer not found", error_code="TRAILER_NOT_FOUND") from None
    removed_file = False
    if delete_file and trailer.file_path and os.path.exists(usermedia_abs_path(trailer.file_path)):
        try:
            os.remove(usermedia_abs_path(trailer.file_path))
            removed_file = True
        except OSError as e:
            raise UnprocessableEntityError(f"Could not delete file: {e}", error_code="FILE_DELETE_FAILED") from e
    title = trailer.title
    trailer.delete()
    return _ok({"deleted": True, "title": title, "file_removed": removed_file})


class TrailerBulkIdsSchema(Schema):
    ids: list[int] = Field(..., description="Trailer IDs to delete")
    delete_files: bool = Field(True, description="Also remove the files from disk")


@trailer_api.post("/library/bulk-delete")
def bulk_delete_trailers(request: HttpRequest, payload: TrailerBulkIdsSchema):
    """Delete multiple trailers; missing IDs and un-removable files are reported back, not fatal."""
    if not payload.ids:
        raise ValidationError("No trailer IDs provided", error_code="NO_IDS")
    if len(payload.ids) > 500:
        raise ValidationError("Too many IDs (max 500)", error_code="TOO_MANY_IDS")

    deleted, files_removed = 0, 0
    missing: list[int] = []
    file_errors: list[str] = []
    for trailer_id in payload.ids:
        trailer = Trailer.objects.filter(id=trailer_id).first()
        if trailer is None:
            missing.append(trailer_id)
            continue
        if payload.delete_files and trailer.file_path and os.path.exists(usermedia_abs_path(trailer.file_path)):
            try:
                os.remove(usermedia_abs_path(trailer.file_path))
                files_removed += 1
            except OSError as e:
                file_errors.append(f"{trailer.title}: {e}")
        trailer.delete()
        deleted += 1
    return _ok({"deleted": deleted, "files_removed": files_removed, "missing": missing, "file_errors": file_errors})


@trailer_api.post("/upload", response={201: dict})
def upload_trailer(
    request: HttpRequest,
    file: UploadedFile = File(..., description="Trailer video file"),
    title: str | None = Form(None, description="Trailer title (required when no tmdbid)"),
    tmdbid: int | None = Form(None, description="Optional TMDB id to link — fills metadata automatically"),
    tags: str | None = Form(None, description="Comma-separated trailer tag names (created if new)"),
):
    tag_names = [t.strip() for t in (tags or "").split(",") if t.strip()]
    service = TrailerService()
    trailer = service.import_uploaded_trailer(file, title=title, tmdbid=tmdbid, tag_names=tag_names)
    return Status(201, _ok({"trailer": _trailer_detail(trailer, _valid_ratings())}))


@trailer_api.get("/tmdb-search")
def tmdb_search(request: HttpRequest, q: str = "", limit: int = 8):
    """Thin TMDB movie-search proxy; without a key returns an empty result list, never an error."""
    q = q.strip()
    api_key = TrailerService().tmdb.api_key
    if not api_key or not q:
        return _ok({"results": [], "api_key_configured": bool(api_key)})

    from tmdbv3api import Movie as TmdbMovie

    try:
        results = TmdbMovie().search(q)
    except Exception as e:
        raise UnprocessableEntityError(f"TMDB search failed: {e}", error_code="TMDB_SEARCH_FAILED") from e

    def _get(obj, key, default=None):
        # tmdbv3api wraps payloads in AsObj (not a dict subclass) — duck-type.
        return obj.get(key, default) if hasattr(obj, "get") else getattr(obj, key, default)

    from cinefin.api.models import Movie as MovieModel

    rows = []
    for movie in list(results or [])[: max(1, min(limit, 20))]:
        movie_id = _get(movie, "id")
        if not movie_id:
            continue
        release_date = _get(movie, "release_date") or ""
        poster_path = _get(movie, "poster_path") or ""
        rows.append(
            {
                "tmdbid": movie_id,
                "title": _get(movie, "title") or "Unknown",
                "year": int(release_date[:4]) if release_date[:4].isdigit() else None,
                "poster_url": f"https://image.tmdb.org/t/p/w92{poster_path}" if poster_path else None,
            }
        )

    ids = [r["tmdbid"] for r in rows]
    with_trailer = set(Trailer.objects.filter(tmdbid__in=ids).values_list("tmdbid", flat=True))
    in_library = set(MovieModel.objects.filter(tmdbid__in=ids).values_list("tmdbid", flat=True))
    for r in rows:
        r["has_trailer"] = r["tmdbid"] in with_trailer
        r["in_library"] = r["tmdbid"] in in_library
    return _ok({"results": rows, "api_key_configured": True})


@trailer_api.get("/tmdb-videos")
def tmdb_videos(request: HttpRequest, tmdbid: int):
    """List a movie's YouTube videos from TMDB, trailers first (official before fan uploads, newest first)."""
    service = TrailerService()
    if not service.tmdb.api_key:
        raise ValidationError(
            "TMDB API key not configured. Set it under Settings → Library source.", error_code="NO_TMDB_API_KEY"
        )
    try:
        details = service.tmdb_movie.details(int(tmdbid), append_to_response="videos")
    except Exception as e:
        raise UnprocessableEntityError(
            f"Could not fetch TMDB videos for id {tmdbid}: {e}", error_code="TMDB_FETCH_FAILED"
        ) from e

    def _get(obj, key, default=None):
        # tmdbv3api wraps payloads in AsObj (not a dict subclass) — duck-type.
        return obj.get(key, default) if hasattr(obj, "get") else getattr(obj, key, default)

    results = _get(_get(details, "videos") or {}, "results") or []
    videos = []
    for v in results:
        if _get(v, "site") != "YouTube" or not _get(v, "key"):
            continue
        videos.append(
            {
                "key": _get(v, "key"),
                "name": _get(v, "name") or "Untitled",
                "type": _get(v, "type") or "",
                "size": _get(v, "size"),
                "official": bool(_get(v, "official")),
                "published_at": _get(v, "published_at") or "",
            }
        )

    type_rank = {"Trailer": 0, "Teaser": 1}
    # Stable sorts: date pass first, then the grouping pass.
    videos.sort(key=lambda v: v["published_at"], reverse=True)
    videos.sort(key=lambda v: (type_rank.get(v["type"], 2), not v["official"]))
    return _ok({"videos": videos})


# Trailer tags — a vocabulary separate from the user-media Tag model.


def _tag_dict(tag: TrailerTag, count: int | None = None) -> dict:
    data = {"id": tag.id, "name": tag.name}
    data["trailer_count"] = count if count is not None else tag.trailers.count()
    return data


def _trailer_tag_list(trailer: Trailer) -> list[dict]:
    return [{"id": t.id, "name": t.name} for t in trailer.trailer_tags.all()]


class TrailerTagCreateSchema(Schema):
    name: str = Field(..., description="Tag name")


@trailer_api.get("/tags")
def list_trailer_tags(request: HttpRequest):
    tags = TrailerTag.objects.annotate(n=Count("trailers")).order_by("name")
    return _ok({"tags": [_tag_dict(t, t.n) for t in tags]})


@trailer_api.post("/tags", response={200: dict, 201: dict})
def create_trailer_tag(request: HttpRequest, payload: TrailerTagCreateSchema):
    """Create a trailer tag; case-insensitively idempotent (an existing name is returned)."""
    name = payload.name.strip()
    if not name:
        raise ValidationError("Tag name is required", error_code="TAG_NAME_REQUIRED")
    existing = TrailerTag.objects.filter(name__iexact=name).first()
    if existing:
        return Status(200, _ok({"tag": _tag_dict(existing), "created": False}))
    tag = TrailerTag.objects.create(name=name)
    return Status(201, _ok({"tag": _tag_dict(tag, 0), "created": True}))


@trailer_api.delete("/tags/{int:tag_id}")
def delete_trailer_tag(request: HttpRequest, tag_id: int):
    """Delete a trailer tag; never refuses — references fall back to "any tag" (FK is SET_NULL)."""
    try:
        tag = TrailerTag.objects.get(pk=tag_id)
    except TrailerTag.DoesNotExist:
        raise NotFoundError("Trailer tag not found", error_code="TRAILER_TAG_NOT_FOUND") from None
    name = tag.name
    detached = tag.trailers.count()
    tag.delete()
    return _ok({"deleted": True, "name": name, "detached_trailers": detached})


class TrailerTagAssignSchema(Schema):
    tag_id: int | None = Field(None, description="Existing tag id")
    name: str | None = Field(None, description="Tag name (created if new) — used when tag_id is absent")


def _resolve_assign_tag(payload: TrailerTagAssignSchema) -> TrailerTag:
    if payload.tag_id:
        try:
            return TrailerTag.objects.get(pk=payload.tag_id)
        except TrailerTag.DoesNotExist:
            raise NotFoundError("Trailer tag not found", error_code="TRAILER_TAG_NOT_FOUND") from None
    name = (payload.name or "").strip()
    if not name:
        raise ValidationError("Provide tag_id or name", error_code="TAG_NAME_REQUIRED")
    tag = TrailerTag.objects.filter(name__iexact=name).first()
    return tag or TrailerTag.objects.create(name=name)


@trailer_api.post("/library/{int:trailer_id}/tags")
def add_trailer_tag(request: HttpRequest, trailer_id: int, payload: TrailerTagAssignSchema):
    try:
        trailer = Trailer.objects.get(id=trailer_id)
    except Trailer.DoesNotExist:
        raise NotFoundError("Trailer not found", error_code="TRAILER_NOT_FOUND") from None
    tag = _resolve_assign_tag(payload)
    trailer.trailer_tags.add(tag)
    return _ok({"trailer_tags": _trailer_tag_list(trailer)})


@trailer_api.delete("/library/{int:trailer_id}/tags/{int:tag_id}")
def remove_trailer_tag(request: HttpRequest, trailer_id: int, tag_id: int):
    try:
        trailer = Trailer.objects.get(id=trailer_id)
    except Trailer.DoesNotExist:
        raise NotFoundError("Trailer not found", error_code="TRAILER_NOT_FOUND") from None
    trailer.trailer_tags.remove(tag_id)
    return _ok({"trailer_tags": _trailer_tag_list(trailer)})


class TrailerBulkTagSchema(TrailerTagAssignSchema):
    ids: list[int] = Field(..., description="Trailer IDs to tag")


@trailer_api.post("/library/bulk-tag")
def bulk_tag_trailers(request: HttpRequest, payload: TrailerBulkTagSchema):
    """Attach one tag to many trailers; missing IDs are reported back."""
    if not payload.ids:
        raise ValidationError("No trailer IDs provided", error_code="NO_IDS")
    if len(payload.ids) > 500:
        raise ValidationError("Too many IDs (max 500)", error_code="TOO_MANY_IDS")
    tag = _resolve_assign_tag(payload)
    trailers = list(Trailer.objects.filter(id__in=payload.ids))
    tag.trailers.add(*trailers)
    missing = sorted(set(payload.ids) - {t.id for t in trailers})
    return _ok({"tagged": len(trailers), "missing": missing, "tag": _tag_dict(tag)})


@trailer_api.post("/library/rename")
def rename_trailers(request: HttpRequest, dry_run: bool = True):
    """Rename trailers to the configured naming template; returns the plan (dry_run) or result counts."""
    service = TrailerService()

    if dry_run:
        changes = []
        for trailer, old, new in service.iter_rename_targets():
            if old == new:
                continue
            rel_old = os.path.basename(old) if old else "(no file)"
            if not old or not os.path.exists(old):
                changes.append({"action": "skip", "label": trailer.title, "detail": f"missing: {rel_old}"})
            elif os.path.exists(new):
                changes.append(
                    {
                        "action": "conflict",
                        "label": trailer.title,
                        "detail": f"target exists: {os.path.relpath(new, service.trailer_dir)}",
                    }
                )
            else:
                rel_new = os.path.relpath(new, service.trailer_dir)
                changes.append({"action": "update", "label": trailer.title, "detail": f"{rel_old} → {rel_new}"})
        total = Trailer.objects.count()
        return _ok({"dry_run": True, "plan": {"total": total, "changes": changes}})
    else:
        success = service.rename_existing_trailers()
        counts = dict(service.sync_counts or {})
        return _ok({"dry_run": False, "counts": counts, "success": success})


def _check_ytdlp_availability() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


def _check_tmdb_availability() -> bool:
    return importlib.util.find_spec("tmdbv3api") is not None
