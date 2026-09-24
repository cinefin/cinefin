"""
Trailer matching for trailer-rule blocks, shared by playlist generation, preview and the editor's live match-count.

Certificate/year/tag are hard filters. Genres are best-effort match-any (sharing more ranks higher) so a rule never
starves the way match-all would. The reference movie only excludes its own trailer and drives ranking.
"""

import logging
import random
from dataclasses import dataclass, field

from django.db.models import Count, Q

from cinefin.api.models import Movie, Settings, Trailer

logger = logging.getLogger(__name__)


@dataclass
class Criteria:
    reference_movie: Movie | None = None
    genre_ids: list[int] = field(default_factory=list)
    certificate_ceiling: str = ""
    year_from: int | None = None
    year_to: int | None = None
    tag: object = None  # TrailerTag instance or id

    @classmethod
    def from_rule(cls, rule) -> "Criteria":
        return cls(
            reference_movie=rule.reference_movie,
            genre_ids=list(rule.genres.values_list("id", flat=True)),
            certificate_ceiling=rule.certificate_ceiling or "",
            year_from=rule.year_from,
            year_to=rule.year_to,
            tag=rule.trailer_tag,
        )

    @classmethod
    def from_movie(
        cls,
        movie: Movie,
        *,
        match_genres: bool = True,
        match_certification: bool = True,
        year_delta: int | None = 5,
    ) -> "Criteria":
        """Criteria seeded from a film (a random-movie binding); flags mirror the template toggles."""
        return cls(
            reference_movie=movie,
            genre_ids=list(movie.genres.values_list("id", flat=True)) if match_genres else [],
            certificate_ceiling=(movie.certification or "") if match_certification else "",
            year_from=(movie.year - year_delta) if (year_delta and movie.year) else None,
            year_to=(movie.year + year_delta) if (year_delta and movie.year) else None,
        )


def ratings_at_or_below(certification: str, system: str | None = None) -> list[str]:
    """Certificates at or below `certification`; unknown ones fall back to an exact match."""
    order = Settings.get_ratings_order(system)
    if certification not in order:
        return [certification]
    return list(order[: order.index(certification) + 1])


def exclude_own_trailer(trailers_query, ref_movie: Movie):
    # tmdbid=0 means "not synced", so guard on it else every unmatched trailer is excluded; title is a fallback.
    if ref_movie.tmdbid:
        trailers_query = trailers_query.exclude(tmdbid=ref_movie.tmdbid)
    if ref_movie.title:
        trailers_query = trailers_query.exclude(title__iexact=ref_movie.title.strip())
    return trailers_query


def build_pool(criteria: Criteria, exclude_ids: set[int] | None = None):
    pool = Trailer.objects.exclude(file_path__isnull=True).exclude(file_path="")
    if criteria.reference_movie is not None:
        pool = exclude_own_trailer(pool, criteria.reference_movie)
    if exclude_ids:
        pool = pool.exclude(id__in=exclude_ids)
    if criteria.tag is not None:
        pool = pool.filter(trailer_tags=criteria.tag)
    if criteria.genre_ids:
        pool = pool.filter(genres__id__in=criteria.genre_ids)
    if criteria.certificate_ceiling:
        pool = pool.filter(content_rating__in=ratings_at_or_below(criteria.certificate_ceiling))
    if criteria.year_from is not None:
        pool = pool.filter(year__gte=criteria.year_from)
    if criteria.year_to is not None:
        pool = pool.filter(year__lte=criteria.year_to)
    return pool.distinct()


def _rank(pool, criteria: Criteria) -> list[Trailer]:
    # Best-first: shared ranking genres, then year-proximity, then newest; ties shuffled.
    ref = criteria.reference_movie
    rank_genre_ids = criteria.genre_ids or (list(ref.genres.values_list("id", flat=True)) if ref else [])
    if rank_genre_ids:
        pool = pool.annotate(genre_overlap=Count("genres", filter=Q(genres__id__in=rank_genre_ids), distinct=True))
    trailers = list(pool)
    random.shuffle(trailers)  # tiebreak baseline

    ref_year = ref.year if ref else None

    def sort_key(t: Trailer):
        year_gap = abs((t.year or 0) - ref_year) if (ref_year and t.year) else 10_000
        overlap = getattr(t, "genre_overlap", 0)
        return (year_gap, -overlap, -(t.year or 0))

    trailers.sort(key=sort_key)
    return trailers


def select_trailers(criteria: Criteria, count: int, exclude_ids: set[int] | None = None) -> tuple[list[Trailer], dict]:
    pool = build_pool(criteria, exclude_ids)
    ranked = _rank(pool, criteria)
    selected = ranked[:count]
    matched = len(ranked)
    info = {
        "matched": matched,
        "requested": count,
        "selected": len(selected),
        "short": matched < count,
    }
    if info["short"]:
        who = criteria.reference_movie.title if criteria.reference_movie else "criteria-only rule"
        logger.info(f"Trailer rule ({who}): only {matched} match for {count} requested")
    return selected, info


def match_stats(criteria: Criteria) -> dict:
    from django.db.models import Avg

    agg = build_pool(criteria).aggregate(n=Count("id", distinct=True), avg_duration=Avg("duration"))
    return {"matched": agg["n"] or 0, "avg_duration": agg["avg_duration"]}
