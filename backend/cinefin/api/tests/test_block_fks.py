import pytest

from .factories import (
    MovieFactory,
    ProgrammeBlockFactory,
    ProgrammeFactory,
    block_for,
)

pytestmark = pytest.mark.django_db


def test_block_content_object_follows_content_type():
    movie = MovieFactory()
    assert block_for(ProgrammeFactory(), 0, "movie", movie).content_object == movie
    assert block_for(ProgrammeFactory(), 0, "certification", movie).content_object == movie
    assert ProgrammeBlockFactory(content_type="bumper", movie=movie).content_object is None


def test_block_survives_movie_deletion_with_snapshot_and_cascades_with_programme():
    movie = MovieFactory(title="Gone Girl", year=2014)
    programme = ProgrammeFactory()
    block = block_for(programme, 0, "movie", movie)
    movie.delete()
    block.refresh_from_db()
    assert (block.movie, block.content_object, block.cached_title, block.cached_year) == (None, None, "Gone Girl", 2014)
    programme.delete()
    assert not type(block).objects.filter(pk=block.pk).exists()
