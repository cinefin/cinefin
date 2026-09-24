"""Kiosk display content — public, read-only films and screenings for a wall display."""

import os

from django.utils import timezone


def film_dict(movie) -> dict:
    return {
        "id": movie.id,
        "title": movie.title,
        "year": movie.year,
        "cert": movie.certification or "",
        "runtime": movie.runtime or 0,
        "genres": [g.name for g in movie.genres.all()[:3]],
        "synopsis": movie.description or "",
        "poster": movie.thumbnail_url,
        "director": movie.director or "",
    }


def build_kiosk_content() -> tuple[list[dict], list[dict]]:
    """The kiosk's films and upcoming screenings, as plain dicts."""
    from datetime import timedelta

    from cinefin.api.models import Movie, ProgrammeBlock, ProgrammeSchedule, Settings

    now = timezone.now()
    source = Settings.get("kiosk.content_source") or "flagged"

    if source == "all":
        movie_qs = Movie.objects.all()
    else:
        movie_qs = Movie.objects.filter(kiosk_display=True)
    movies = movie_qs.prefetch_related("genres").order_by("-year", "title")[:30]
    films = [film_dict(m) for m in movies]

    schedules = (
        ProgrammeSchedule.objects.filter(
            start_time__gt=now - timedelta(hours=12),  # include long-running screenings
            status__in=["scheduled", "running"],
        )
        .select_related("programme")
        .order_by("start_time")
    )

    screenings = []
    for schedule in schedules:
        end_time = schedule.start_time + timedelta(minutes=schedule.runtime)
        if end_time <= now:
            continue

        features, seen = [], set()
        blocks = (
            ProgrammeBlock.objects.filter(programme=schedule.programme, content_type="movie", movie__isnull=False)
            .select_related("movie")
            .prefetch_related("movie__genres")
            .order_by("order")
        )
        for block in blocks:
            if block.movie.id not in seen:
                seen.add(block.movie.id)
                features.append(film_dict(block.movie))

        screenings.append(
            {
                "id": schedule.id,
                "programme": schedule.programme.name,
                "start": schedule.start_time.isoformat(),
                "end": end_time.isoformat(),
                "runtime": schedule.runtime,
                "status": schedule.status,
                "feature": features[0] if features else None,
                "features": features,
            }
        )
        if len(screenings) >= 12:
            break

    if source == "scheduled":
        # Only booked films: the screenings' features, soonest first, de-duplicated.
        films, seen = [], set()
        for screening in screenings:
            feature = screening["feature"]
            if feature and feature["id"] not in seen:
                seen.add(feature["id"])
                films.append(feature)

    return films, screenings


def spa_reload_key() -> str:
    """Deploy stamp (version + index.html mtime) for the SPA kiosk's self-reload."""
    from django.conf import settings as django_settings

    from cinefin.version import get_version

    key = get_version()
    try:
        index = os.path.join(django_settings.FRONTEND_BUILD_DIR, "index.html")
        key += f":{int(os.path.getmtime(index))}"
    except OSError:
        pass
    return key
