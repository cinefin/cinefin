"""Shared helpers for programme queries and display text."""

from typing import Any

from django.db.models import QuerySet

from cinefin.api.models import Movie, ProgrammeBlock


def build_random_movie_query(block: ProgrammeBlock, exclude_empty_paths: bool = True) -> QuerySet:
    """Movie queryset for a block's random-movie criteria; genres match with AND logic."""
    if exclude_empty_paths:
        movies_query = Movie.objects.exclude(file_path__isnull=True).exclude(file_path="")
    else:
        movies_query = Movie.objects.all()

    # ALL genres must match: one chained filter per genre.
    for genre in block.random_movie_genres.all():
        movies_query = movies_query.filter(genres=genre)
    if block.random_movie_certification:
        movies_query = movies_query.filter(certification__iexact=block.random_movie_certification)
    for value, lookup in (
        (block.random_movie_year_from, "year__gte"),
        (block.random_movie_year_to, "year__lte"),
        (block.random_movie_runtime_from, "runtime__gte"),
        (block.random_movie_runtime_to, "runtime__lte"),
    ):
        if value:
            movies_query = movies_query.filter(**{lookup: value})
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

    genre_names = [
        g.name if hasattr(g, "name") else g for g in genres or [] if hasattr(g, "name") or isinstance(g, str)
    ]
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
