"""Trailers API — the trailer library, TMDB fetch jobs and trailer tags."""

import importlib.util
import logging
import os
from datetime import datetime
from typing import Any

from django.db.models import Count, Q
from django.http import HttpRequest
from ninja import Field, File, Form, Router, Schema, Status, UploadedFile

from cinefin.api import ratings
from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import Genre, Job, Movie, Settings, Trailer, TrailerTag
from cinefin.api.schemas.base import ErrorResponseSchema, SuccessResponseSchema
from cinefin.api.services import trailer_jobs
from cinefin.api.services import trailer_naming as tn
from cinefin.api.services.trailer_service import TrailerService
from cinefin.api.utils.media_paths import usermedia_abs_path

logger = logging.getLogger(__name__)

NO_TMDB_KEY = "TMDB API key not configured. Set it under Settings → Library source."
BULK_MAX_IDS = 500

# TMDB's movie genre ids.
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


class FetchRequestSchema(Schema):
    type: str = Field(
        "discover",
        description=(
            '"discover" (TMDB search by date/genre/rating), '
            '"library" (movies missing trailers) or "single" (one title by TMDB id)'
        ),
    )
    tmdbid: int | None = Field(None, description='Required for type "single"')
    video_key: str | None = Field(None, description="YouTube video key (single only) — omit for the automatic pick")
    replace: bool = Field(False, description="Re-download over an existing trailer (single only)")
    year: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    months_ahead: int = 6
    limit: int = 50
    sort_by: str | None = "popularity.desc"
    genres: list[int] | None = Field(None, description="TMDB genre IDs")
    min_rating: float | None = None
    certification: str | None = None


class PreviewTrailersSchema(Schema):
    year_from: int | None = None
    year_to: int | None = None
    limit: int = Field(50, ge=1, le=500)
    sort_by: str = "popularity.desc"
    genres: list[int] | None = Field(None, description="TMDB genre IDs")
    min_rating: float | None = Field(None, ge=0, le=10)
    certification: str | None = None


class PreviewTrailerItemSchema(Schema):
    tmdb_id: int
    title: str
    year: int | None = None
    month: int | None = None
    genres: list[str] = []
    rating: float | None = None
    popularity: float | None = None
    certification: str | None = None
    already_downloaded: bool = False


class PreviewTrailersDataSchema(Schema):
    trailers: list[PreviewTrailerItemSchema]
    total_found: int
    will_fetch: int
    already_have: int


class PreviewTrailersResponseSchema(SuccessResponseSchema):
    data: PreviewTrailersDataSchema


class TrailerStatsDataSchema(Schema):
    statistics: dict[str, Any]


class TrailerStatsResponseSchema(SuccessResponseSchema):
    data: TrailerStatsDataSchema


class TrailerSettingsSchema(Schema):
    tmdb_api_key: str | None = None
    download_quality: str | None = Field(None, description="720, 1080, 1440, 2160 or best")
    rating_lookup_enabled: bool | None = Field(
        None, description="Backfill missing certificates from the classification bodies' websites"
    )
    upcoming_months_ahead: int | None = Field(None, ge=1, le=24)
    filename_template: str | None = Field(None, description="e.g. {title} ({year}) [tmdb-{tmdbid}]")
    folder_template: str | None = Field(None, description="e.g. {year}")


class RatingsUpdateSchema(Schema):
    scope: str = Field("trailers", pattern="^(movies|trailers|all)$")


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


class TrailerPatchSchema(Schema):
    content_rating: str | None = None


class TrailerBulkIdsSchema(Schema):
    ids: list[int]
    delete_files: bool = Field(True, description="Also remove the files from disk")


class TrailerTagCreateSchema(Schema):
    name: str


class TrailerTagAssignSchema(Schema):
    tag_id: int | None = None
    name: str | None = Field(None, description="Tag name (created if new) — used when tag_id is absent")


class TrailerBulkTagSchema(TrailerTagAssignSchema):
    ids: list[int]


trailer_api = Router()


def _ok(data=None):
    return {"success": True, "data": data}


def _get_trailer(trailer_id: int) -> Trailer:
    try:
        return Trailer.objects.get(id=trailer_id)
    except Trailer.DoesNotExist:
        raise NotFoundError("Trailer not found", error_code="TRAILER_NOT_FOUND") from None


def _require_tmdb_key(api_key) -> None:
    if not api_key:
        raise ValidationError(NO_TMDB_KEY, error_code="NO_TMDB_API_KEY")


def _check_bulk_ids(ids: list[int]) -> None:
    if not ids:
        raise ValidationError("No trailer IDs provided", error_code="NO_IDS")
    if len(ids) > BULK_MAX_IDS:
        raise ValidationError("Too many IDs (max 500)", error_code="TOO_MANY_IDS")


def _tmdb_get(obj, key, default=None):
    # tmdbv3api wraps payloads in AsObj (not a dict subclass) — duck-type.
    return obj.get(key, default) if hasattr(obj, "get") else getattr(obj, key, default)


@trailer_api.get("/settings", tags=["Trailers"])
def get_trailer_settings(request: HttpRequest):
    return {
        "success": True,
        "message": "Trailer settings retrieved",
        "data": {
            "settings": {**Settings.DEFAULTS.get("trailers", {}), **(Settings.get("trailers") or {})},
            "naming_tokens": tn.AVAILABLE_TOKENS,
            "dependencies": {
                "rating_provider_available": ratings.get_provider(Settings.get_ratings_system()) is not None,
                "yt_dlp_available": importlib.util.find_spec("yt_dlp") is not None,
                "tmdb_available": importlib.util.find_spec("tmdbv3api") is not None,
            },
            "supported_qualities": ["720", "1080", "1440", "2160", "best"],
        },
    }


@trailer_api.post("/settings", tags=["Trailers"])
def update_trailer_settings(request: HttpRequest, data: TrailerSettingsSchema):
    current = dict(Settings.get("trailers") or {})
    current.update({k: v for k, v in data.dict().items() if v is not None})
    Settings.set("trailers", current)
    return {"success": True, "message": "Trailer settings saved", "data": {"settings": current}}


def _start_job(operation: str, params: dict):
    try:
        job = trailer_jobs.start_job(operation, params)
    except RuntimeError as e:
        raise UnprocessableEntityError(str(e), error_code="TRAILER_JOB_RUNNING") from e
    except ValueError as e:
        raise ValidationError(str(e), error_code="INVALID_OPERATION") from e
    return _ok({"job": job.serialize()})


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
    _require_tmdb_key(TrailerService().tmdb.api_key)

    params = {}
    if data.type == "discover":
        params = data.dict(
            include={
                "year",
                "months_ahead",
                "year_from",
                "year_to",
                "limit",
                "sort_by",
                "genres",
                "min_rating",
                "certification",
            }
        )
    elif data.type == "single":
        params = {"tmdbid": data.tmdbid, "video_key": data.video_key, "replace": data.replace}
    return _start_job(data.type, params)


@trailer_api.post("/verify", response=_JOB_RESPONSES)
def verify_trailers(request: HttpRequest):
    return _start_job("verify", {})


@trailer_api.post("/ratings/update", response=_JOB_RESPONSES)
def update_trailer_ratings(request: HttpRequest, payload: RatingsUpdateSchema | None = None):
    return _start_job("ratings", {"scope": payload.scope if payload else "trailers"})


@trailer_api.get("/jobs/current", response=_JOB_RESPONSES)
def current_trailer_job(request: HttpRequest):
    """The active trailer job (or most recent), with full log — used on page load."""
    job = (
        Job.trailer.filter(state__in=Job.ACTIVE_STATES).order_by("-created_at").first()
        or Job.trailer.order_by("-created_at").first()
    )
    return _ok({"job": job.serialize(include_log=True) if job else None})


@trailer_api.get("/jobs/{job_id}", response=_JOB_RESPONSES)
def get_trailer_job(request: HttpRequest, job_id: int):
    try:
        job = Job.trailer.get(pk=job_id)
    except Job.DoesNotExist:
        raise NotFoundError("Trailer job not found", error_code="TRAILER_JOB_NOT_FOUND") from None
    return _ok({"job": job.serialize(include_log=True)})


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
    from tmdbv3api import Discover, TMDb

    tmdb_api_key = Settings.get("trailers.tmdb_api_key") or ""
    _require_tmdb_key(tmdb_api_key)
    TMDb().api_key = tmdb_api_key

    current_year = datetime.now().year
    discover_params = {
        "sort_by": str(filters.sort_by),
        "include_adult": False,
        "region": "GB",
        "primary_release_date.gte": f"{filters.year_from or current_year}-01-01",
        "primary_release_date.lte": f"{filters.year_to or current_year + 1}-12-31",
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
    try:
        results_list = list(Discover().discover_movies(discover_params) or [])
    except Exception as e:
        logger.exception("Failed to preview trailers")
        raise UnprocessableEntityError(f"Failed to preview trailers: {str(e)}", error_code="PREVIEW_FAILED") from e

    existing_tmdb_ids = set(Trailer.objects.values_list("tmdbid", flat=True))
    preview_items = []
    already_have_count = 0
    for movie in results_list[: filters.limit]:
        try:
            movie_id = _tmdb_get(movie, "id")
            if not movie_id:
                continue
            already_downloaded = movie_id in existing_tmdb_ids
            already_have_count += already_downloaded

            year = month = None
            release_date = _tmdb_get(movie, "release_date")
            if release_date:
                try:
                    parsed = datetime.strptime(str(release_date), "%Y-%m-%d")
                    year, month = parsed.year, parsed.month
                except ValueError:
                    pass

            preview_items.append(
                {
                    "tmdb_id": movie_id,
                    "title": _tmdb_get(movie, "title", "Unknown"),
                    "year": year,
                    "month": month,
                    "genres": [
                        GENRE_MAP[int(gid)] for gid in _tmdb_get(movie, "genre_ids", []) if int(gid) in GENRE_MAP
                    ],
                    "rating": _tmdb_get(movie, "vote_average"),
                    "popularity": _tmdb_get(movie, "popularity"),
                    "certification": None,
                    "already_downloaded": already_downloaded,
                }
            )
        except Exception as e:
            logger.warning(f"Error processing movie in preview: {e}")

    return {
        "message": f"Found {len(results_list)} trailers matching criteria",
        "data": {
            "trailers": preview_items,
            "total_found": len(results_list),
            "will_fetch": min(len(results_list), filters.limit) - already_have_count,
            "already_have": already_have_count,
        },
    }


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
    from cinefin.api.services.trailer_matching import Criteria, _rank, build_pool

    movie = None
    if movie_id:
        movie = Movie.objects.filter(pk=movie_id).first()
        if movie is None:
            raise NotFoundError("Movie not found")

    criteria = Criteria(
        reference_movie=movie,
        genre_ids=[int(g) for g in genre_ids.split(",") if g.strip().isdigit()],
        certificate_ceiling=certificate_ceiling,
        year_from=year_from,
        year_to=year_to,
        tag=TrailerTag.objects.filter(pk=tag_id).first() if tag_id else None,
    )
    ranked = _rank(build_pool(criteria), criteria)
    top_ids = {t.id for t in ranked[:count]}

    return {
        "data": {
            "movie_id": movie.id if movie else None,
            "movie_title": movie.title if movie else None,
            "matched": len(ranked),
            "requested": count,
            "trailers": [
                {
                    "id": t.id,
                    "title": t.title,
                    "year": t.year,
                    "content_rating": t.content_rating or "",
                    "will_play": t.id in top_ids,
                }
                for t in ranked[:50]
            ],
        }
    }


@trailer_api.get("/stats", response={200: TrailerStatsResponseSchema, 500: ErrorResponseSchema})
def get_trailer_stats(request: HttpRequest):
    return {
        "message": "Trailer statistics retrieved successfully",
        "data": {"statistics": TrailerService().get_statistics()},
    }


def _file_state(t: Trailer) -> tuple[bool, int]:
    """(file exists, size) — trailers don't store a size, so it's read live from the file."""
    abs_path = usermedia_abs_path(t.file_path) if t.file_path else ""
    exists = bool(abs_path and os.path.exists(abs_path))
    return exists, os.path.getsize(abs_path) if exists else 0


def _trailer_tag_list(trailer: Trailer) -> list[dict]:
    return [{"id": tg.id, "name": tg.name} for tg in trailer.trailer_tags.all()]


def _trailer_row(t, exists, valid, file_size=0, movie_tmdbids=frozenset()):
    return {
        "id": t.id,
        "title": t.title,
        "year": t.year,
        "month": t.month,
        "duration": t.duration,
        "file_size": file_size,
        "content_rating": t.content_rating,
        "rating_ok": bool(t.content_rating) and t.content_rating in valid,
        "tmdbid": t.tmdbid,
        "director": t.director,
        "file_path": t.file_path,
        "file_name": os.path.basename(t.file_path) if t.file_path else "",
        "file_exists": exists,
        "stream_url": f"/stream/trailer/{t.id}/",
        "has_movie": t.associated_movie_id is not None or t.tmdbid in movie_tmdbids,
        "genres": [g.name for g in t.genres.all()],
        "trailer_tags": _trailer_tag_list(t),
    }


LIBRARY_SORTS = {"-year", "year", "title", "-title", "content_rating", "-content_rating", "duration", "-duration"}


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
    valid = Settings.get_valid_ratings()
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
    # file_size is read live from the file, so it's sorted in Python below.
    size_sort = sort in ("file_size", "-file_size")
    order = sort if sort in LIBRARY_SORTS else "-year"
    base = base.distinct().order_by(order, "title").prefetch_related("genres", "trailer_tags")

    all_rows = list(Trailer.objects.values("file_path", "content_rating"))
    total_lib = len(all_rows)
    with_file = sum(1 for t in all_rows if t["file_path"] and os.path.exists(usermedia_abs_path(t["file_path"])))
    issues = sum(1 for t in all_rows if not t["content_rating"] or t["content_rating"] not in valid)

    rows = []
    for t in base:
        exists, size = _file_state(t)
        if not (missing and exists):
            rows.append((t, exists, size))
    if size_sort:
        rows.sort(key=lambda r: r[2], reverse=sort.startswith("-"))

    movie_tmdbids = set(Movie.objects.exclude(tmdbid=0).values_list("tmdbid", flat=True))
    return _ok(
        {
            "trailers": [
                _trailer_row(t, exists, valid, size, movie_tmdbids) for t, exists, size in rows[offset : offset + limit]
            ],
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
                "ratings": sorted({(t["content_rating"] or "") for t in all_rows} - {""}),
                "genres": sorted(Genre.objects.filter(trailer__isnull=False).values_list("name", flat=True).distinct()),
                "valid_ratings": sorted(valid),
                "trailer_tags": [
                    {"id": t.id, "name": t.name, "trailer_count": t.n}
                    for t in TrailerTag.objects.annotate(n=Count("trailers")).order_by("name")
                ],
            },
        }
    )


def _trailer_detail(t: Trailer) -> dict:
    exists, size = _file_state(t)
    movie = t.linked_movie()
    return {
        **_trailer_row(t, exists, Settings.get_valid_ratings(), size),
        "certificates": t.certificates or {},
        "rating_lookups": t.rating_lookups or {},
        "has_movie": movie is not None,
        "associated_movie": (
            {"id": movie.id, "title": movie.title, "year": movie.year, "tmdbid": movie.tmdbid} if movie else None
        ),
    }


@trailer_api.get("/library/{int:trailer_id}")
def trailer_library_detail(request: HttpRequest, trailer_id: int):
    return _ok({"trailer": _trailer_detail(_get_trailer(trailer_id))})


@trailer_api.patch("/library/{int:trailer_id}")
def update_trailer(request: HttpRequest, trailer_id: int, payload: TrailerPatchSchema):
    t = _get_trailer(trailer_id)
    if payload.content_rating is not None:
        # A manual edit targets the ACTIVE display system's certificate slot.
        system = Settings.get_ratings_system()
        value = payload.content_rating.strip()
        t.set_certificate(system, value, active_system=system)
        if value:
            t.mark_rating_lookup(system, "matched")
    t.save()
    return _ok({"trailer": _trailer_detail(t)})


@trailer_api.delete("/library/{int:trailer_id}")
def delete_trailer(request: HttpRequest, trailer_id: int, delete_file: bool = False):
    trailer = _get_trailer(trailer_id)
    removed_file = False
    if delete_file and trailer.file_path and os.path.exists(usermedia_abs_path(trailer.file_path)):
        try:
            os.remove(usermedia_abs_path(trailer.file_path))
            removed_file = True
        except OSError as e:
            raise UnprocessableEntityError(f"Could not delete file: {e}", error_code="FILE_DELETE_FAILED") from e
    trailer.delete()
    return _ok({"deleted": True, "title": trailer.title, "file_removed": removed_file})


@trailer_api.post("/library/bulk-delete")
def bulk_delete_trailers(request: HttpRequest, payload: TrailerBulkIdsSchema):
    """Delete multiple trailers; missing IDs and un-removable files are reported back, not fatal."""
    _check_bulk_ids(payload.ids)
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
    trailer = TrailerService().import_uploaded_trailer(file, title=title, tmdbid=tmdbid, tag_names=tag_names)
    return Status(201, _ok({"trailer": _trailer_detail(trailer)}))


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

    rows = []
    for movie in list(results or [])[: max(1, min(limit, 20))]:
        movie_id = _tmdb_get(movie, "id")
        if not movie_id:
            continue
        release_date = _tmdb_get(movie, "release_date") or ""
        poster_path = _tmdb_get(movie, "poster_path") or ""
        rows.append(
            {
                "tmdbid": movie_id,
                "title": _tmdb_get(movie, "title") or "Unknown",
                "year": int(release_date[:4]) if release_date[:4].isdigit() else None,
                "poster_url": f"https://image.tmdb.org/t/p/w92{poster_path}" if poster_path else None,
            }
        )

    ids = [r["tmdbid"] for r in rows]
    with_trailer = set(Trailer.objects.filter(tmdbid__in=ids).values_list("tmdbid", flat=True))
    in_library = set(Movie.objects.filter(tmdbid__in=ids).values_list("tmdbid", flat=True))
    for r in rows:
        r["has_trailer"] = r["tmdbid"] in with_trailer
        r["in_library"] = r["tmdbid"] in in_library
    return _ok({"results": rows, "api_key_configured": True})


@trailer_api.get("/tmdb-videos")
def tmdb_videos(request: HttpRequest, tmdbid: int):
    """List a movie's YouTube videos from TMDB, trailers first (official before fan uploads, newest first)."""
    service = TrailerService()
    _require_tmdb_key(service.tmdb.api_key)
    try:
        details = service.tmdb_movie.details(int(tmdbid), append_to_response="videos")
    except Exception as e:
        raise UnprocessableEntityError(
            f"Could not fetch TMDB videos for id {tmdbid}: {e}", error_code="TMDB_FETCH_FAILED"
        ) from e

    videos = [
        {
            "key": _tmdb_get(v, "key"),
            "name": _tmdb_get(v, "name") or "Untitled",
            "type": _tmdb_get(v, "type") or "",
            "size": _tmdb_get(v, "size"),
            "official": bool(_tmdb_get(v, "official")),
            "published_at": _tmdb_get(v, "published_at") or "",
        }
        for v in _tmdb_get(_tmdb_get(details, "videos") or {}, "results") or []
        if _tmdb_get(v, "site") == "YouTube" and _tmdb_get(v, "key")
    ]
    type_rank = {"Trailer": 0, "Teaser": 1}
    # Stable sorts: date pass first, then the grouping pass.
    videos.sort(key=lambda v: v["published_at"], reverse=True)
    videos.sort(key=lambda v: (type_rank.get(v["type"], 2), not v["official"]))
    return _ok({"videos": videos})


# Trailer tags — a vocabulary separate from the user-media Tag model.


def _tag_dict(tag: TrailerTag, count: int | None = None) -> dict:
    return {"id": tag.id, "name": tag.name, "trailer_count": tag.trailers.count() if count is None else count}


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


def _resolve_assign_tag(payload: TrailerTagAssignSchema) -> TrailerTag:
    if payload.tag_id:
        try:
            return TrailerTag.objects.get(pk=payload.tag_id)
        except TrailerTag.DoesNotExist:
            raise NotFoundError("Trailer tag not found", error_code="TRAILER_TAG_NOT_FOUND") from None
    name = (payload.name or "").strip()
    if not name:
        raise ValidationError("Provide tag_id or name", error_code="TAG_NAME_REQUIRED")
    return TrailerTag.objects.filter(name__iexact=name).first() or TrailerTag.objects.create(name=name)


@trailer_api.post("/library/{int:trailer_id}/tags")
def add_trailer_tag(request: HttpRequest, trailer_id: int, payload: TrailerTagAssignSchema):
    trailer = _get_trailer(trailer_id)
    trailer.trailer_tags.add(_resolve_assign_tag(payload))
    return _ok({"trailer_tags": _trailer_tag_list(trailer)})


@trailer_api.delete("/library/{int:trailer_id}/tags/{int:tag_id}")
def remove_trailer_tag(request: HttpRequest, trailer_id: int, tag_id: int):
    trailer = _get_trailer(trailer_id)
    trailer.trailer_tags.remove(tag_id)
    return _ok({"trailer_tags": _trailer_tag_list(trailer)})


@trailer_api.post("/library/bulk-tag")
def bulk_tag_trailers(request: HttpRequest, payload: TrailerBulkTagSchema):
    """Attach one tag to many trailers; missing IDs are reported back."""
    _check_bulk_ids(payload.ids)
    tag = _resolve_assign_tag(payload)
    trailers = list(Trailer.objects.filter(id__in=payload.ids))
    tag.trailers.add(*trailers)
    missing = sorted(set(payload.ids) - {t.id for t in trailers})
    return _ok({"tagged": len(trailers), "missing": missing, "tag": _tag_dict(tag)})


@trailer_api.post("/library/rename")
def rename_trailers(request: HttpRequest, dry_run: bool = True):
    """Rename trailers to the configured naming template; returns the plan (dry_run) or result counts."""
    service = TrailerService()
    if not dry_run:
        success = service.rename_existing_trailers()
        return _ok({"dry_run": False, "counts": dict(service.sync_counts or {}), "success": success})

    changes = []
    for trailer, old, new in service.iter_rename_targets():
        if old == new:
            continue
        rel_old = os.path.basename(old) if old else "(no file)"
        rel_new = os.path.relpath(new, service.trailer_dir)
        if not old or not os.path.exists(old):
            action, detail = "skip", f"missing: {rel_old}"
        elif os.path.exists(new):
            action, detail = "conflict", f"target exists: {rel_new}"
        else:
            action, detail = "update", f"{rel_old} → {rel_new}"
        changes.append({"action": action, "label": trailer.title, "detail": detail})
    return _ok({"dry_run": True, "plan": {"total": Trailer.objects.count(), "changes": changes}})
