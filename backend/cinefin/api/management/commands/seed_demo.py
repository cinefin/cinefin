"""Seed a believable, entirely offline demo dataset (DEV/DEMO tool).

Demo rows are tagged so ``--clear`` is precise and can never touch real data:
every seeded title carries the DEMO_PREFIX marker, so we only delete our own rows.
"""

import random

from django.conf import settings as django_settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from cinefin.api.models import (
    Bumper,
    Genre,
    Movie,
    Programme,
    ProgrammeBlock,
    ProgrammeSchedule,
    ProgrammeTemplate,
    ProgrammeTemplateItem,
    Settings,
    SyncSource,
    TicketIssue,
)

# Marker to tag and later reclaim every demo row (kept in the title so --clear is precise).
DEMO_PREFIX = "[Demo] "
DEMO_SOURCE_NAME = "Demo"

_DEMO_MOVIES = [
    ("The Midnight Archive", 2019, 124, "15", ["Thriller", "Mystery"]),
    ("Coral Skies", 2021, 98, "PG", ["Adventure", "Family"]),
    ("Iron Harvest", 2016, 141, "12A", ["Action", "Drama"]),
    ("A Quiet Orbit", 2020, 109, "PG", ["Sci-Fi", "Drama"]),
    ("Paper Lanterns", 2018, 92, "U", ["Animation", "Family"]),
    ("The Long Winter", 2015, 133, "15", ["Drama", "History"]),
    ("Neon Alley", 2022, 105, "18", ["Crime", "Thriller"]),
    ("Windward", 2017, 118, "12A", ["Adventure", "Romance"]),
    ("Static Bloom", 2023, 96, "15", ["Horror", "Mystery"]),
    ("Cartographers", 2014, 127, "PG", ["Documentary", "History"]),
    ("Ember & Ash", 2021, 112, "12A", ["Fantasy", "Adventure"]),
    ("The Last Projectionist", 2019, 88, "U", ["Comedy", "Drama"]),
    ("Glasshouse", 2020, 101, "15", ["Thriller", "Drama"]),
    ("Verdant", 2016, 115, "PG", ["Family", "Adventure"]),
    ("Signal Lost", 2022, 107, "15", ["Sci-Fi", "Thriller"]),
    ("Marigold Street", 2018, 94, "U", ["Comedy", "Romance"]),
]

_DEMO_BUMPERS = [
    ("Feature Presentation Ident", 12),
    ("Silence Your Phones", 8),
    ("Dolby Atmos Intro", 30),
    ("Now Showing Sting", 6),
]


class Command(BaseCommand):
    help = (
        "Seed an offline demo dataset (movies, bumpers, templates, programmes, "
        "schedules, tickets, settings). Dev/demo tool — refuses to run against "
        "a populated non-demo database unless --force is given."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Seed even when the database already has movies or is in production (DEBUG off).",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete previously demo-seeded rows first (precise: only rows tagged as demo).",
        )
        parser.add_argument(
            "--movies",
            type=int,
            default=len(_DEMO_MOVIES),
            help=f"How many demo movies to create (max {len(_DEMO_MOVIES)}, default all).",
        )

    def handle(self, *args, **options):
        force = options["force"]
        clear = options["clear"]
        movie_count = max(1, min(options["movies"], len(_DEMO_MOVIES)))

        real_movies = Movie.objects.exclude(title__startswith=DEMO_PREFIX).exists()

        # Guardrails: never nuke or overwrite a real library by accident.
        if not force:
            if not django_settings.DEBUG and Movie.objects.exists():
                raise CommandError(
                    "Refusing to seed: DEBUG is off and the database already has movies. "
                    "Re-run with --force if you really mean to seed this database."
                )
            if real_movies:
                raise CommandError(
                    "Refusing to seed: the database already contains non-demo movies. "
                    "Re-run with --force to seed alongside them (existing rows are untouched)."
                )

        if clear:
            removed = self._clear_demo()
            self.stdout.write(f"Cleared {removed} previously seeded demo row(s).")

        random.seed(20240726)  # deterministic-ish demo output
        counts = self._seed(movie_count)

        summary = ", ".join(f"{k}: {v}" for k, v in counts.items())
        self.stdout.write(self.style.SUCCESS(f"Demo data seeded ({summary})."))
        self.stdout.write("Open http://127.0.0.1:8000/ to explore the demo cinema.")

    def _clear_demo(self) -> int:
        """Delete only demo-tagged rows. Cascades handle blocks/schedules."""
        removed = 0
        # Programmes/templates/tickets first (FKs), then movies/bumpers/source.
        removed += ProgrammeSchedule.objects.filter(programme__name__startswith=DEMO_PREFIX).delete()[0]
        removed += TicketIssue.objects.filter(title__startswith=DEMO_PREFIX).delete()[0]
        removed += Programme.objects.filter(name__startswith=DEMO_PREFIX).delete()[0]
        removed += ProgrammeTemplate.objects.filter(name__startswith=DEMO_PREFIX).delete()[0]
        removed += Bumper.objects.filter(title__startswith=DEMO_PREFIX).delete()[0]
        removed += Movie.objects.filter(title__startswith=DEMO_PREFIX).delete()[0]
        source = SyncSource.objects.filter(name=DEMO_SOURCE_NAME).first()
        if source:
            removed += source.delete()[0]
        return removed

    def _seed(self, movie_count: int) -> dict:
        counts = {
            "movies": 0,
            "bumpers": 0,
            "templates": 0,
            "programmes": 0,
            "schedules": 0,
            "tickets": 0,
        }

        Settings.set("cinema.name", "The Demo Roxy")
        Settings.set("setup.completed", True)

        source, _ = SyncSource.objects.get_or_create(
            name=DEMO_SOURCE_NAME,
            defaults={
                "sync_type": "jellyfin",
                "url": "http://demo.invalid:8096",
                "token": "demo",
                "libraries": "Films",
                "enabled": False,
            },
        )

        movies = []
        for title, year, runtime, cert, genre_names in _DEMO_MOVIES[:movie_count]:
            movie = Movie.objects.create(
                title=f"{DEMO_PREFIX}{title}",
                file_path=f"/demo/movies/{title.lower().replace(' ', '_')}.mkv",
                duration=runtime * 60,
                director="Demo Director",
                year=year,
                certification=cert,
                runtime=runtime,
                description=f"A demo feature: {title}.",
                resolution="1080p",
                kiosk_display=True,
                sync_source=source,
                date_added=timezone.now(),
            )
            genres = [Genre.objects.get_or_create(name=g)[0] for g in genre_names]
            movie.genres.set(genres)
            movies.append(movie)
            counts["movies"] += 1

        bumpers = []
        for name, duration in _DEMO_BUMPERS:
            bumper = Bumper.objects.create(
                title=f"{DEMO_PREFIX}{name}",
                file_path=f"/demo/bumpers/{name.lower().replace(' ', '_')}.mp4",
                duration=duration,
            )
            bumpers.append(bumper)
            counts["bumpers"] += 1

        templates = self._make_templates(bumpers)
        counts["templates"] = len(templates)

        programmes = self._make_programmes(templates, movies, bumpers)
        counts["programmes"] = len(programmes)

        counts["schedules"] = self._make_schedules(programmes)
        counts["tickets"] = self._make_tickets(programmes, movies)

        return counts

    def _make_templates(self, bumpers) -> list:
        specs = [
            ("Single Feature", 1, 3),
            ("Double Bill", 2, 2),
            ("Family Matinee", 1, 2),
        ]
        templates = []
        for name, features, trailers in specs:
            tmpl = ProgrammeTemplate.objects.create(
                name=f"{DEMO_PREFIX}{name}",
                description=f"Demo template: {name}.",
                number_of_features=features,
                trailer_count_per_feature=trailers,
            )
            order = 0
            if bumpers:
                ProgrammeTemplateItem.objects.create(template=tmpl, order=order, item_type="bumper", bumper=bumpers[0])
                order += 1
            for feature_no in range(1, features + 1):
                ProgrammeTemplateItem.objects.create(
                    template=tmpl,
                    order=order,
                    item_type="trailer_rule",
                    bound_to_feature=feature_no,
                    trailer_count=trailers,
                )
                order += 1
                ProgrammeTemplateItem.objects.create(
                    template=tmpl,
                    order=order,
                    item_type="feature",
                    feature_number=feature_no,
                )
                order += 1
            templates.append(tmpl)
        return templates

    def _make_programmes(self, templates, movies, bumpers) -> list:
        programmes = []
        titles = [
            "Friday Night Feature",
            "Saturday Double Bill",
            "Sunday Family Matinee",
            "Midweek Classics",
            "Late Night Screening",
        ]
        for idx, title in enumerate(titles):
            tmpl = templates[idx % len(templates)]
            programme = Programme.objects.create(
                name=f"{DEMO_PREFIX}{title}",
                description=f"A demo programme: {title}.",
                template=tmpl,
            )
            order = 0
            if bumpers:
                ProgrammeBlock.objects.create(
                    programme=programme,
                    order=order,
                    content_type="bumper",
                    bumper=random.choice(bumpers),
                )
                order += 1
            for _ in range(tmpl.number_of_features):
                movie = movies[(idx + order) % len(movies)]
                ProgrammeBlock.objects.create(
                    programme=programme,
                    order=order,
                    content_type="movie",
                    movie=movie,
                )
                order += 1
            programmes.append(programme)
        return programmes

    def _make_schedules(self, programmes) -> int:
        now = timezone.now()
        offsets = [
            timezone.timedelta(days=1, hours=1),
            timezone.timedelta(days=2, hours=3),
            timezone.timedelta(days=5),
            timezone.timedelta(days=-2),  # past
            timezone.timedelta(days=-7),  # past
        ]
        made = 0
        for idx, offset in enumerate(offsets):
            programme = programmes[idx % len(programmes)]
            start = now + offset
            status = "completed" if offset.days < 0 else "scheduled"
            ProgrammeSchedule.objects.create(
                programme=programme,
                start_time=start,
                runtime=programme.get_total_runtime_minutes() or 120,
                status=status,
            )
            made += 1
        return made

    def _make_tickets(self, programmes, movies) -> int:
        made = 0
        for i in range(6):
            if i % 2 == 0 and programmes:
                programme = programmes[i % len(programmes)]
                TicketIssue.issue(
                    kind=TicketIssue.KIND_PROGRAMME,
                    programme=programme,
                    title=programme.name,
                    seat=f"{chr(ord('A') + i)}{i + 1}",
                )
            else:
                movie = movies[i % len(movies)]
                TicketIssue.issue(
                    kind=TicketIssue.KIND_MOVIE,
                    movie=movie,
                    title=movie.title,
                    seat=f"{chr(ord('A') + i)}{i + 1}",
                )
            made += 1
        return made
