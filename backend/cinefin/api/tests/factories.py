"""factory_boy factories for the core Cinefin models."""

from datetime import timedelta

import factory
from django.utils import timezone

from cinefin.api import models


class GenreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Genre
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Genre {n}")


class TagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Tag
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Tag {n}")


class TrailerTagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.TrailerTag
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Trailer Tag {n}")


class MovieFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Movie
        skip_postgeneration_save = True

    title = factory.Sequence(lambda n: f"Test Movie {n}")
    file_path = factory.Sequence(lambda n: f"/tmp/cinefin-tests/movies/movie-{n}.mkv")
    duration = 7200
    director = "Test Director"
    year = 2020
    certification = "PG"
    runtime = 120
    tmdbid = factory.Sequence(lambda n: 100000 + n)
    date_added = factory.LazyFunction(timezone.now)

    @factory.post_generation
    def genres(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.genres.set(extracted)


class TrailerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Trailer
        skip_postgeneration_save = True

    title = factory.Sequence(lambda n: f"Test Trailer {n}")
    file_path = factory.Sequence(lambda n: f"/tmp/cinefin-tests/trailers/trailer-{n}.mp4")
    duration = 150
    director = "Test Director"
    year = 2020
    month = 6
    content_rating = "PG"
    tmdbid = factory.Sequence(lambda n: 200000 + n)

    @factory.post_generation
    def genres(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.genres.set(extracted)

    @factory.post_generation
    def trailer_tags(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.trailer_tags.set(extracted)


class BumperFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Bumper
        skip_postgeneration_save = True

    title = factory.Sequence(lambda n: f"Test Bumper {n}")
    file_path = factory.Sequence(lambda n: f"/tmp/cinefin-tests/bumpers/bumper-{n}.mp4")
    duration = 30

    @factory.post_generation
    def tags(self, create, extracted, **kwargs):
        if not create or not extracted:
            return
        self.tags.set(extracted)


class CertificationFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Certification

    movie = factory.SubFactory(MovieFactory)
    certification = factory.LazyAttribute(lambda o: o.movie.certification or "PG")
    file_path = factory.Sequence(lambda n: f"/tmp/cinefin-tests/certs/cert-{n}.mp4")


class CommandFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Command

    name = factory.Sequence(lambda n: f"Test Command {n}")
    provider = "rest"
    config = {"url": "http://commands.invalid/fire"}


class ProgrammeTemplateFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ProgrammeTemplate

    name = factory.Sequence(lambda n: f"Test Template {n}")
    number_of_features = 1
    trailer_count_per_feature = 3


class ProgrammeTemplateItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ProgrammeTemplateItem

    template = factory.SubFactory(ProgrammeTemplateFactory)
    order = factory.Sequence(lambda n: n)
    item_type = "feature"
    feature_number = 1


class ProgrammeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Programme

    name = factory.Sequence(lambda n: f"Test Programme {n}")
    description = "A test programme"


class ProgrammeBlockFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ProgrammeBlock

    programme = factory.SubFactory(ProgrammeFactory)
    order = factory.Sequence(lambda n: n)
    content_type = ""


_BLOCK_FK_BY_MODEL = {
    models.Movie: "movie",
    models.Bumper: "bumper",
    models.Command: "command",
    models.Trailer: "trailer",
    models.Certification: "certification",
}


def block_for(programme, order, content_type, obj=None, **kwargs):
    block = models.ProgrammeBlock(programme=programme, order=order, content_type=content_type, **kwargs)
    if obj is not None:
        setattr(block, _BLOCK_FK_BY_MODEL[type(obj)], obj)
    block.save()
    return block


class TrailerRuleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.TrailerRule

    name = factory.Sequence(lambda n: f"Test Trailer Rule {n}")
    reference_movie = factory.SubFactory(MovieFactory)
    number_of_trailers = 3


class PlaylistFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Playlist

    programme = factory.SubFactory(ProgrammeFactory)


class PlaylistItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.PlaylistItem

    playlist = factory.SubFactory(PlaylistFactory)
    order = factory.Sequence(lambda n: n)
    content_type = "bumper"
    file = "/tmp/cinefin-tests/playlist-item.mp4"


class SyncSourceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.SyncSource

    name = factory.Sequence(lambda n: f"Test Source {n}")
    sync_type = "jellyfin"
    url = "http://jellyfin.invalid:8096"
    token = "test-token"
    libraries = "Films"
    enabled = True


class JobFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.Job

    kind = models.Job.KIND_SYNC
    source = factory.SubFactory(SyncSourceFactory)
    operation = "sync"


class ProgrammeScheduleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = models.ProgrammeSchedule

    programme = factory.SubFactory(ProgrammeFactory)
    start_time = factory.LazyFunction(lambda: timezone.now() + timedelta(days=1))
    runtime = 120
