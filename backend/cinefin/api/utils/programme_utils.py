"""Shared helpers for programme queries and display text."""

import logging
from typing import Any

from django.db.models import QuerySet

from cinefin.api.models import Movie, ProgrammeBlock

logger = logging.getLogger(__name__)


def build_random_movie_query(block: ProgrammeBlock, exclude_empty_paths: bool = True) -> QuerySet:
    """Movie queryset for a block's random-movie criteria; genres match with AND logic."""
    if exclude_empty_paths:
        movies_query = Movie.objects.exclude(file_path__isnull=True).exclude(file_path="")
    else:
        movies_query = Movie.objects.all()

    # ALL genres must match - chain filters for AND
    genres = block.random_movie_genres.all()
    if genres.exists():
        for genre in genres:
            movies_query = movies_query.filter(genres=genre)
        logger.debug(f"Filtering by genres (ALL must match): {', '.join(g.name for g in genres)}")

    if block.random_movie_certification:
        movies_query = movies_query.filter(certification__iexact=block.random_movie_certification)
        logger.debug(f"Filtering by certification: {block.random_movie_certification}")

    if block.random_movie_year_from:
        movies_query = movies_query.filter(year__gte=block.random_movie_year_from)
        logger.debug(f"Filtering by year >= {block.random_movie_year_from}")

    if block.random_movie_year_to:
        movies_query = movies_query.filter(year__lte=block.random_movie_year_to)
        logger.debug(f"Filtering by year <= {block.random_movie_year_to}")

    if block.random_movie_runtime_from:
        movies_query = movies_query.filter(runtime__gte=block.random_movie_runtime_from)
        logger.debug(f"Filtering by runtime >= {block.random_movie_runtime_from} min")

    if block.random_movie_runtime_to:
        movies_query = movies_query.filter(runtime__lte=block.random_movie_runtime_to)
        logger.debug(f"Filtering by runtime <= {block.random_movie_runtime_to} min")

    return movies_query.distinct()


def build_filter_description(
    genres: list[Any] = None,
    certification: str = None,
    year_from: int = None,
    year_to: int = None,
    runtime_from: int = None,
    runtime_to: int = None,
    default_text: str = "Any movie",
) -> str:
    """Human-readable filter description for random movie criteria (e.g. "Comedy, PG-13, 2020-2024")."""
    filters = []

    if genres:
        genre_names = []
        for g in genres:
            if hasattr(g, "name"):
                genre_names.append(g.name)
            elif isinstance(g, str):
                genre_names.append(g)
        if genre_names:
            filters.append(", ".join(genre_names))

    if certification:
        filters.append(certification)

    if year_from and year_to:
        filters.append(f"{year_from}-{year_to}")
    elif year_from:
        filters.append(f"{year_from}+")
    elif year_to:
        filters.append(f"≤{year_to}")

    if runtime_from and runtime_to:
        filters.append(f"{runtime_from}-{runtime_to} min")
    elif runtime_from:
        filters.append(f"≥{runtime_from} min")
    elif runtime_to:
        filters.append(f"≤{runtime_to} min")

    return ", ".join(filters) if filters else default_text


def build_filter_description_from_block(block: ProgrammeBlock, default_text: str = "Any movie") -> str:
    """build_filter_description() sourced from a block's random_movie_* fields."""
    return build_filter_description(
        genres=list(block.random_movie_genres.all()),
        certification=block.random_movie_certification,
        year_from=block.random_movie_year_from,
        year_to=block.random_movie_year_to,
        runtime_from=block.random_movie_runtime_from,
        runtime_to=block.random_movie_runtime_to,
        default_text=default_text,
    )
