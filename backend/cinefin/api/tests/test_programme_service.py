import pytest

from cinefin.api.exceptions import NotFoundError, ValidationError
from cinefin.api.models import Playlist, Programme, ProgrammeBlock, TrailerRule
from cinefin.api.services.playlist_service import PlaylistService
from cinefin.api.services.programme_service import ProgrammeService

from .factories import (
    BumperFactory,
    CommandFactory,
    GenreFactory,
    MovieFactory,
    ProgrammeTemplateFactory,
    ProgrammeTemplateItemFactory,
    TagFactory,
    TrailerFactory,
)

pytestmark = pytest.mark.django_db


def _create(*items, **kw):
    return ProgrammeService.create_programme(name=kw.pop("name", "P"), items=list(items), **kw)


class TestCreateProgramme:
    def test_create_with_items(self):
        movie, bumper, command = MovieFactory(), BumperFactory(), CommandFactory()
        tag = TagFactory()
        programme, preview = _create(
            {"type": "command", "command_id": command.id, "hold_black": True},
            {"type": "command", "command_id": command.id},
            {"type": "bumper", "bumper_id": bumper.id},
            {"type": "bumper", "tag_id": tag.id, "count": 3},
            {"type": "audio_bumper", "reference_movie_id": movie.id, "bumper_id": bumper.id},
            {"type": "movie", "movie_id": movie.id, "audio_track": 1},
        )
        held, instant, clip, random_clip, audio, feature = programme.blocks.order_by("order")
        assert (held.command, held.hold_black, instant.hold_black) == (command, True, False)
        assert (clip.bumper, clip.random_tag_id) == (bumper, None)
        assert (random_clip.bumper_id, random_clip.random_tag_id, random_clip.random_count) == (None, tag.id, 3)
        assert (audio.movie, audio.bumper) == (movie, bumper)
        assert (feature.content_object, feature.audio_track_index) == (movie, 1)
        assert preview["playlist_generated"] is True
        assert Playlist.objects.filter(programme=programme).exists()

    def test_trailer_rule_item_creates_rule(self):
        genre = GenreFactory()
        movie = MovieFactory(genres=[genre])
        TrailerFactory(genres=[genre], content_rating=movie.certification, year=movie.year)
        programme, _ = _create(
            {"type": "trailer_rule", "reference_movie_id": movie.id, "count": 2},
            {"type": "movie", "movie_id": movie.id},
        )
        rule = programme.blocks.get(content_type="trailer_rule").trailer_rule
        assert (rule.reference_movie, rule.number_of_trailers) == (movie, 2)

    def test_empty_name_and_missing_movie(self):
        with pytest.raises(ValidationError):
            ProgrammeService.create_programme(name="   ", items=[])
        with pytest.raises(NotFoundError):
            _create({"type": "movie", "movie_id": 999999})


class TestCreateFromTemplate:
    def _template(self):
        template = ProgrammeTemplateFactory(number_of_features=1)
        ProgrammeTemplateItemFactory(template=template, order=0, item_type="bumper", bumper=BumperFactory())
        ProgrammeTemplateItemFactory(
            template=template, order=1, item_type="trailer_rule", bound_to_feature=1, trailer_count=2
        )
        ProgrammeTemplateItemFactory(template=template, order=2, item_type="feature", feature_number=1)
        return template

    def test_create_from_template(self):
        genre = GenreFactory()
        movie = MovieFactory(genres=[genre])
        TrailerFactory(genres=[genre], content_rating=movie.certification, year=movie.year)
        template = self._template()
        programme, preview = ProgrammeService.create_programme_from_template(
            name="Templated", template_id=template.id, movies={"1": {"id": movie.id}}
        )
        assert programme.template == template
        blocks = list(programme.blocks.order_by("order"))
        assert [b.content_type for b in blocks] == ["bumper", "trailer_rule", "movie"]
        assert blocks[2].content_object == movie
        assert blocks[1].trailer_rule.reference_movie == movie
        assert preview["template_name"] == template.name

    def test_missing_feature_movie_skips_feature_blocks(self):
        programme, _ = ProgrammeService.create_programme_from_template(
            name="X", template_id=self._template().id, movies={}
        )
        assert [b.content_type for b in programme.blocks.order_by("order")] == ["bumper"]


class TestUpdateAndDelete:
    def test_update_items_replaces_blocks_and_refreshes_playlist(self):
        movie, other = MovieFactory(), MovieFactory()
        programme, _ = _create({"type": "movie", "movie_id": movie.id})
        updated = ProgrammeService.update_programme(programme.id, items=[{"type": "movie", "movie_id": other.id}])
        assert [b.content_object for b in updated.blocks.all()] == [other]
        assert updated.playlist_stale is False
        files = [item.file for item in Playlist.objects.get(programme=updated).items.all()]
        assert any(f"/stream/movie/{other.id}/" in f for f in files)
        assert not any(f"/stream/movie/{movie.id}/" in f for f in files)

    def test_failed_regeneration_keeps_edit_and_marks_stale(self, monkeypatch):
        movie, other = MovieFactory(), MovieFactory()
        programme, _ = _create({"type": "movie", "movie_id": movie.id})

        def boom(programme):
            raise RuntimeError("generation exploded")

        monkeypatch.setattr(PlaylistService, "build_playlist_from_programme", staticmethod(boom))
        updated = ProgrammeService.update_programme(programme.id, items=[{"type": "movie", "movie_id": other.id}])
        assert [b.content_object for b in updated.blocks.all()] == [other]
        assert updated.playlist_stale is True


def test_duplicate_copies_blocks_and_all_config():
    movie, command, genre = MovieFactory(), CommandFactory(), GenreFactory()
    programme = Programme.objects.create(name="Original", description="the original")
    ProgrammeBlock.objects.create(
        programme=programme,
        order=0,
        content_type="movie",
        movie=movie,
        audio_track_index=1,
        subtitle_track_index=2,
        credits_command=command,
    )
    ProgrammeBlock.objects.create(
        programme=programme, order=1, content_type="command", command=command, hold_black=True
    )
    rule = TrailerRule.objects.create(
        name="Rule", reference_movie=movie, certificate_ceiling="15", year_from=2018, year_to=2022, number_of_trailers=2
    )
    rule.genres.set([genre])
    ProgrammeBlock.objects.create(programme=programme, order=2, content_type="trailer_rule", trailer_rule=rule)
    random_block = ProgrammeBlock.objects.create(
        programme=programme,
        order=3,
        content_type="random_movie",
        random_movie_certification="PG",
        random_movie_runtime_from=60,
        random_count=1,
        trailer_match_genres=False,
        trailer_year_delta=7,
    )
    random_block.random_movie_genres.set([genre])

    copy = ProgrammeService.duplicate_programme(programme.id)

    assert (copy.name, copy.description, copy.last_played_at) == ("Original (copy)", "the original", None)
    feature, held, trailers, random_movie = copy.blocks.order_by("order")
    assert (feature.movie, feature.audio_track_index, feature.subtitle_track_index) == (movie, 1, 2)
    assert (feature.credits_command, feature.cached_title) == (command, movie.title)
    assert (held.command, held.hold_black) == (command, True)
    copied_rule = trailers.trailer_rule
    assert copied_rule.id != rule.id
    assert (copied_rule.certificate_ceiling, copied_rule.year_from, copied_rule.year_to) == ("15", 2018, 2022)
    assert list(copied_rule.genres.all()) == [genre]
    assert (random_movie.random_movie_certification, random_movie.random_movie_runtime_from) == ("PG", 60)
    assert (random_movie.trailer_match_genres, random_movie.trailer_year_delta) == (False, 7)
    assert list(random_movie.random_movie_genres.all()) == [genre]
    assert programme.blocks.count() == 4
