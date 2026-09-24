"""ProgrammeService smoke tests."""

import pytest

from cinefin.api.exceptions import NotFoundError, ValidationError
from cinefin.api.models import Playlist, Programme, ProgrammeBlock, TrailerRule
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


class TestCreateProgramme:
    def test_create_with_items(self):
        movie = MovieFactory()
        bumper = BumperFactory()
        command = CommandFactory()

        programme, preview = ProgrammeService.create_programme(
            name="Friday Night",
            description="desc",
            items=[
                {"type": "command", "command_id": command.id},
                {"type": "bumper", "bumper_id": bumper.id},
                {"type": "movie", "movie_id": movie.id, "audio_track": 1},
            ],
        )

        assert programme is not None
        assert programme.name == "Friday Night"
        blocks = list(programme.blocks.order_by("order"))
        assert [b.content_type for b in blocks] == ["command", "bumper", "movie"]
        assert blocks[0].content_object == command
        assert blocks[1].content_object == bumper
        assert blocks[2].content_object == movie
        assert blocks[2].audio_track_index == 1
        assert preview["playlist_generated"] is True
        assert Playlist.objects.filter(programme=programme).exists()

    def test_command_hold_black_round_trips(self):
        command = CommandFactory()
        programme, _ = ProgrammeService.create_programme(
            name="Held",
            items=[{"type": "command", "command_id": command.id, "hold_black": True}],
        )
        block = programme.blocks.get()
        assert block.hold_black is True
        programme2, _ = ProgrammeService.create_programme(
            name="Instant", items=[{"type": "command", "command_id": command.id}]
        )
        assert programme2.blocks.get().hold_black is False

    def test_trailer_rule_item_creates_rule(self):
        genre = GenreFactory()
        movie = MovieFactory(genres=[genre])
        TrailerFactory(genres=[genre], content_rating=movie.certification, year=movie.year)

        programme, _ = ProgrammeService.create_programme(
            name="With Trailers",
            items=[
                {"type": "trailer_rule", "reference_movie_id": movie.id, "count": 2},
                {"type": "movie", "movie_id": movie.id},
            ],
        )

        block = programme.blocks.get(content_type="trailer_rule")
        assert block.trailer_rule is not None
        assert block.trailer_rule.reference_movie == movie
        assert block.trailer_rule.number_of_trailers == 2
        assert TrailerRule.objects.filter(reference_movie=movie).exists()

    def test_preview_does_not_persist(self):
        movie = MovieFactory()
        programme, preview = ProgrammeService.create_programme(
            name="Preview", items=[{"type": "movie", "movie_id": movie.id}], preview=True
        )
        assert programme is None
        assert preview["preview"] is True
        assert preview["total_blocks"] == 1
        assert not Programme.objects.filter(name="Preview").exists()

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ProgrammeService.create_programme(name="   ", items=[])

    def test_missing_movie_raises_not_found(self):
        with pytest.raises(NotFoundError):
            ProgrammeService.create_programme(name="Bad", items=[{"type": "movie", "movie_id": 999999}])


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
            name="Templated",
            template_id=template.id,
            movies={"1": {"id": movie.id}},
        )

        assert programme is not None
        assert programme.template == template
        blocks = list(programme.blocks.order_by("order"))
        assert [b.content_type for b in blocks] == ["bumper", "trailer_rule", "movie"]
        assert blocks[2].content_object == movie
        assert blocks[1].trailer_rule.reference_movie == movie
        assert preview["template_name"] == template.name
        assert Playlist.objects.filter(programme=programme).exists()

    def test_missing_feature_movie_skips_feature_blocks(self):
        """Locked in: a missing feature movie skips its blocks, doesn't fail creation."""
        template = self._template()
        programme, _ = ProgrammeService.create_programme_from_template(name="X", template_id=template.id, movies={})
        assert programme is not None
        assert [b.content_type for b in programme.blocks.order_by("order")] == ["bumper"]


class TestUpdateProgramme:
    def test_update_items_replaces_blocks_and_refreshes_playlist(self):
        movie = MovieFactory()
        other = MovieFactory()
        programme, _ = ProgrammeService.create_programme(
            name="Rebuild", items=[{"type": "movie", "movie_id": movie.id}]
        )

        updated = ProgrammeService.update_programme(
            programme.id,
            items=[{"type": "movie", "movie_id": other.id}],
        )

        blocks = list(updated.blocks.all())
        assert len(blocks) == 1
        assert blocks[0].content_object == other
        assert updated.playlist_stale is False
        files = [item.file for item in Playlist.objects.get(programme=updated).items.all()]
        assert any(f"/stream/movie/{other.id}/" in f for f in files)
        assert not any(f"/stream/movie/{movie.id}/" in f for f in files)

    def test_failed_regeneration_keeps_edit_and_marks_stale(self, monkeypatch):
        movie = MovieFactory()
        other = MovieFactory()
        programme, _ = ProgrammeService.create_programme(
            name="Fragile", items=[{"type": "movie", "movie_id": movie.id}]
        )

        from cinefin.api.services.playlist_service import PlaylistService

        def boom(programme):
            raise RuntimeError("generation exploded")

        monkeypatch.setattr(PlaylistService, "build_playlist_from_programme", staticmethod(boom))
        updated = ProgrammeService.update_programme(
            programme.id,
            items=[{"type": "movie", "movie_id": other.id}],
        )

        assert [b.content_object for b in updated.blocks.all()] == [other]
        assert updated.playlist_stale is True


class TestDeleteProgramme:
    def test_delete(self):
        movie = MovieFactory()
        programme, _ = ProgrammeService.create_programme(name="Doomed", items=[{"type": "movie", "movie_id": movie.id}])
        result = ProgrammeService.delete_programme(programme.id)
        assert result["programme_id"] == programme.id
        assert not Programme.objects.filter(pk=programme.id).exists()


class TestDuplicateProgramme:
    def _rich_programme(self):
        movie = MovieFactory()
        command = CommandFactory()
        genre = GenreFactory()
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
            name="Rule",
            reference_movie=movie,
            certificate_ceiling="15",
            year_from=2018,
            year_to=2022,
            number_of_trailers=2,
        )
        rule.genres.set([genre])
        ProgrammeBlock.objects.create(programme=programme, order=2, content_type="trailer_rule", trailer_rule=rule)
        random_block = ProgrammeBlock.objects.create(
            programme=programme,
            order=3,
            content_type="random_movie",
            random_movie_certification="PG",
            random_movie_year_from=2000,
            random_movie_year_to=2100,
            random_movie_runtime_from=60,
            random_movie_runtime_to=240,
            random_count=1,
            trailer_match_genres=False,
            trailer_year_delta=7,
            bound_to_block_order=None,
        )
        random_block.random_movie_genres.set([genre])
        movie.genres.set([genre])
        return programme, movie, command, rule, genre

    def test_duplicate_copies_blocks_and_all_config(self):
        programme, movie, command, rule, genre = self._rich_programme()

        copy = ProgrammeService.duplicate_programme(programme.id)

        assert copy.id != programme.id
        assert copy.name == "Original (copy)"
        assert copy.description == "the original"
        assert copy.last_played_at is None

        blocks = list(copy.blocks.order_by("order"))
        assert [b.content_type for b in blocks] == ["movie", "command", "trailer_rule", "random_movie"]

        assert blocks[0].movie == movie
        assert blocks[0].audio_track_index == 1
        assert blocks[0].subtitle_track_index == 2
        assert blocks[0].credits_command == command
        assert blocks[0].cached_title == movie.title

        assert blocks[1].command == command
        assert blocks[1].hold_black is True

        assert blocks[2].trailer_rule is not None
        assert blocks[2].trailer_rule.id != rule.id
        assert blocks[2].trailer_rule.reference_movie == movie
        assert blocks[2].trailer_rule.certificate_ceiling == "15"
        assert blocks[2].trailer_rule.year_from == 2018
        assert blocks[2].trailer_rule.year_to == 2022
        assert blocks[2].trailer_rule.number_of_trailers == 2
        assert list(blocks[2].trailer_rule.genres.all()) == [genre]

        assert blocks[3].random_movie_certification == "PG"
        assert blocks[3].random_movie_year_from == 2000
        assert blocks[3].random_movie_year_to == 2100
        assert blocks[3].random_movie_runtime_from == 60
        assert blocks[3].random_movie_runtime_to == 240
        assert blocks[3].random_count == 1
        assert blocks[3].trailer_match_genres is False
        assert blocks[3].trailer_year_delta == 7
        assert list(blocks[3].random_movie_genres.all()) == [genre]

        assert programme.blocks.count() == 4
        programme.refresh_from_db()
        assert programme.name == "Original"


class TestAudioBumperItem:
    def test_bound_and_override_round_trip(self):
        movie = MovieFactory(title="Bound Feature")
        sting = BumperFactory(title="Atmos Sting")
        programme, _ = ProgrammeService.create_programme(
            name="Audio",
            items=[
                {"type": "audio_bumper", "reference_movie_id": movie.id, "bumper_id": sting.id},
                {"type": "movie", "movie_id": movie.id},
            ],
        )
        block = programme.blocks.get(content_type="audio_bumper")
        assert block.movie_id == movie.id
        assert block.bumper_id == sting.id


class TestUserMediaItem:
    """A "bumper" item has two modes: a specific clip (bumper_id) or random from a tag."""

    def test_specific_clip_round_trips_to_bumper_fk(self):
        clip = BumperFactory(title="Sponsor sting")
        programme, _ = ProgrammeService.create_programme(
            name="Specific",
            items=[{"type": "bumper", "bumper_id": clip.id}],
        )
        block = programme.blocks.get(content_type="bumper")
        assert block.bumper_id == clip.id
        assert block.random_tag_id is None

    def test_tag_makes_it_random(self):
        tag = TagFactory(name="Idents")
        BumperFactory(tags=[tag])
        programme, _ = ProgrammeService.create_programme(
            name="Random",
            items=[{"type": "bumper", "tag_id": tag.id, "count": 3}],
        )
        block = programme.blocks.get(content_type="bumper")
        assert block.bumper_id is None
        assert block.random_tag_id == tag.id
        assert block.random_count == 3


class TestProcessItemValidation:
    """A missing required id is a ValidationError (400), not an unhandled KeyError (500)."""

    @pytest.mark.parametrize(
        "item",
        [
            {"type": "movie"},
            {"type": "trailer"},
            {"type": "bumper"},
            {"type": "command"},
            {"type": "certification"},
        ],
    )
    def test_missing_required_id_raises_validation_error(self, item):
        with pytest.raises(ValidationError):
            ProgrammeService.process_programme_item(item, 0)
