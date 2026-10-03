"""Programme creation, editing, duplication and running."""

import logging
from typing import Any

from django.db import transaction
from django.db.models import Avg

from cinefin.api.exceptions import NotFoundError, UnprocessableEntityError, ValidationError
from cinefin.api.models import (
    Bumper,
    Certification,
    Command,
    Genre,
    Movie,
    Programme,
    ProgrammeBlock,
    ProgrammeTemplate,
    Settings,
    Tag,
    Trailer,
    TrailerRule,
    TrailerTag,
)
from cinefin.api.utils.assets import rating_card_path, rating_card_video_path
from cinefin.api.utils.media_paths import to_usermedia_relative
from cinefin.api.utils.programme_utils import build_filter_description

from .block_types import fetch_block_entity
from .playlist_service import PlaylistService
from .trailer_matching import Criteria, match_stats

logger = logging.getLogger(__name__)

RANDOM_FILTER_KEYS = ("certification", "year_from", "year_to", "runtime_from", "runtime_to")


def _block(order, type_, runtime, title, **details):
    return {"order": order, "type": type_, "runtime": runtime, "title": title, "details": details}


def _movie_block(order, movie, audio_track, subtitle_track, credits_command_id, **extra):
    return _block(
        order,
        "movie",
        (movie.duration or 0) / 60.0,
        movie.title,
        movie_id=movie.id,
        movie_title=movie.title,
        duration=movie.duration,
        audio_track=audio_track,
        subtitle_track=subtitle_track,
        credits_command_id=credits_command_id,
        **extra,
    )


def _clip_block(order, kind, clip):
    """A specific trailer or user media item."""
    return _block(
        order,
        kind,
        (clip.duration or 0) / 60.0,
        clip.title,
        **{f"{kind}_id": clip.id, f"{kind}_title": clip.title, "duration": clip.duration},
    )


def _random_bumper_block(order, tag, count):
    avg = tag.bumper_set.aggregate(avg=Avg("duration"))["avg"] or 30.0
    return _block(
        order,
        "bumper",
        avg * count / 60.0,
        f"Random user media ({tag.name})",
        tag_id=tag.id,
        tag_name=tag.name,
        count=count,
        estimated_duration=avg * count,
    )


def _command_block(order, command, hold_black):
    return _block(
        order,
        "command",
        # Instant cues take no screen time; hold blocks occupy the command's duration.
        (command.duration or 0) / 60.0 if hold_black else 0.0,
        command.name,
        command_id=command.id,
        command_name=command.name,
        provider=command.provider,
        hold_black=hold_black,
        duration=command.duration,
    )


def _avg_trailer_duration():
    return Trailer.objects.aggregate(avg=Avg("duration"))["avg"] or 150.0


def _tag_suffix(tag):
    return f" (tag: {tag.name})" if tag else ""


def _get_programme(programme_id) -> Programme:
    try:
        return Programme.objects.get(pk=programme_id)
    except Programme.DoesNotExist:
        raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None


class ProgrammeService:
    @staticmethod
    def validate_programme_name(name: str) -> None:
        if not name or not name.strip():
            raise ValidationError("Programme name is required", error_code="PROGRAMME_NAME_REQUIRED")

    @staticmethod
    def process_programme_item(item_data: dict[str, Any], order: int) -> dict[str, Any]:
        """A rundown item from the API → the block dict previews show and saving builds from."""
        item_type = item_data.get("type")
        if not item_type:
            raise ValidationError("Item type is required", error_code="ITEM_TYPE_REQUIRED")

        def _req(key: str):
            # A missing key is a client error (400), not an unhandled KeyError → 500.
            value = item_data.get(key)
            if value is None:
                raise ValidationError(f"{key} is required for a '{item_type}' item", error_code="MISSING_FIELD")
            return value

        if item_type == "movie":
            return _movie_block(
                order,
                fetch_block_entity("movie", _req("movie_id")),
                item_data.get("audio_track_index", item_data.get("audio_track", 0)),
                item_data.get("subtitle_track_index", item_data.get("subtitle_track")),
                item_data.get("credits_command_id"),
            )

        if item_type == "trailer":
            return _clip_block(order, "trailer", fetch_block_entity("trailer", _req("trailer_id")))

        if item_type == "bumper":
            # A tag_id/tag_name means a random pick; otherwise a specific clip.
            tag_id, tag_name = item_data.get("tag_id"), item_data.get("tag_name")
            if tag_id or tag_name:
                try:
                    tag = Tag.objects.get(pk=tag_id) if tag_id else Tag.objects.get(name=tag_name)
                except Tag.DoesNotExist:
                    raise NotFoundError("Tag not found", error_code="TAG_NOT_FOUND") from None
                return _random_bumper_block(order, tag, item_data.get("count", 1))
            return _clip_block(order, "bumper", fetch_block_entity("bumper", _req("bumper_id")))

        if item_type == "random_movie":
            genre_ids = item_data.get("genre_ids", [])
            filters = {k: item_data.get(k) for k in RANDOM_FILTER_KEYS}
            count = item_data.get("count", 1)
            genres = list(Genre.objects.filter(pk__in=genre_ids)) if genre_ids else []
            filter_text = build_filter_description(genres=genres, default_text="Any", **filters)

            movies = Movie.objects.all()
            for genre in genres:
                movies = movies.filter(genres=genre)
            if filters["certification"]:
                movies = movies.filter(certification__iexact=filters["certification"])
            for key, lookup in (
                ("year_from", "year__gte"),
                ("year_to", "year__lte"),
                ("runtime_from", "runtime__gte"),
                ("runtime_to", "runtime__lte"),
            ):
                if filters[key]:
                    movies = movies.filter(**{lookup: filters[key]})

            avg_runtime = movies.aggregate(avg=Avg("runtime"))["avg"] or 120.0
            return _block(
                order,
                "random_movie",
                avg_runtime * count / 60.0,
                f"Random movie ({filter_text})",
                genre_ids=genre_ids,
                genre_names=[g.name for g in genres],
                **filters,
                count=count,
                estimated_duration=avg_runtime * count,
                matching_movies=movies.count(),
            )

        if item_type == "command":
            return _command_block(
                order, fetch_block_entity("command", _req("command_id")), bool(item_data.get("hold_black"))
            )

        if item_type == "trailer_rule":
            ref_id = item_data.get("reference_movie_id")
            ref_movie = fetch_block_entity("movie", ref_id) if ref_id else None
            count = item_data.get("count", 3)
            # Resolved leniently: a dangling id drops the filter rather than failing the save.
            tag_id = item_data.get("trailer_tag_id")
            trailer_tag = TrailerTag.objects.filter(pk=tag_id).first() if tag_id else None
            avg = _avg_trailer_duration()
            return _block(
                order,
                "trailer_rule",
                avg * count / 60.0,
                f"Trailers for {ref_movie.title if ref_movie else 'criteria'}" + _tag_suffix(trailer_tag),
                reference_movie_id=ref_movie.id if ref_movie else None,
                reference_movie_title=ref_movie.title if ref_movie else None,
                count=count,
                genre_ids=item_data.get("genre_ids") or [],
                certificate_ceiling=item_data.get("certificate_ceiling") or "",
                year_from=item_data.get("year_from"),
                year_to=item_data.get("year_to"),
                trailer_tag_id=trailer_tag.id if trailer_tag else None,
                trailer_tag_name=trailer_tag.name if trailer_tag else None,
                estimated_duration=avg * count,
                # A rule bound to a random-movie feature defers resolution to playlist
                # generation; these must be threaded through or the bound branch never fires.
                bound_to_block_order=item_data.get("bound_to_block_order"),
                match_genres=item_data.get("match_genres", True),
                match_certification=item_data.get("match_certification", True),
                year_delta=item_data.get("year_delta", 5),
            )

        if item_type == "certification":
            movie = fetch_block_entity("movie", _req("movie_id"))
            return _block(
                order,
                "certification",
                0.5,
                f"Certification for {movie.title}",
                movie_id=movie.id,
                movie_title=movie.title,
                certification=item_data.get("certification") or movie.certification,
            )

        if item_type == "audio_bumper":
            details = {}
            title = "Audio bumper"
            if item_data.get("reference_movie_id"):
                movie = fetch_block_entity("movie", item_data["reference_movie_id"])
                details.update(reference_movie_id=movie.id, reference_movie_title=movie.title)
                title = f"Audio intro for {movie.title}"
            if item_data.get("bumper_id"):
                bumper = fetch_block_entity("bumper", item_data["bumper_id"])
                details.update(bumper_id=bumper.id, bumper_title=bumper.title)
                title = bumper.title
            return _block(order, "audio_bumper", 0.25, title, **details)

        raise ValidationError(f"Unknown item type: {item_type}", error_code="UNKNOWN_ITEM_TYPE")

    @classmethod
    def _save_new(cls, blocks, preview_data, **fields):
        """Create the programme and its blocks, then build its playlist."""
        programme = Programme.objects.create(**fields)
        for block_data in blocks:
            cls._create_programme_block(programme, block_data)
        item_count = cls.refresh_playlist(programme)
        preview_data["playlist_generated"] = item_count is not None
        preview_data["playlist_items"] = item_count or 0
        if item_count is not None:
            logger.info(f"Created programme: {programme.name} with {len(blocks)} blocks and {item_count} items")
        return programme, preview_data

    @classmethod
    def create_programme(
        cls, name: str, description: str = "", items: list[dict[str, Any]] = None, preview: bool = False
    ) -> tuple[Programme | None, dict[str, Any]]:
        with transaction.atomic():
            if not preview:
                cls.validate_programme_name(name)
            blocks = [cls.process_programme_item(item, order) for order, item in enumerate(items or [])]
            preview_data = {
                "name": name.strip(),
                "description": description or "",
                "total_runtime": sum(b["runtime"] for b in blocks),
                "total_blocks": len(blocks),
                "blocks": blocks,
                "preview": preview,
            }
            if preview:
                return None, preview_data
            return cls._save_new(blocks, preview_data, name=name.strip(), description=description or "")

    @classmethod
    def create_programme_from_template(
        cls,
        name: str,
        template_id: int,
        movies: dict[str, dict[str, Any]],
        description: str = "",
        preview: bool = False,
    ) -> tuple[Programme | None, dict[str, Any]]:
        with transaction.atomic():
            if not preview:
                cls.validate_programme_name(name)
            try:
                template = ProgrammeTemplate.objects.get(pk=template_id)
            except ProgrammeTemplate.DoesNotExist:
                raise NotFoundError("Template not found", error_code="TEMPLATE_NOT_FOUND") from None

            feature_movies = {}
            for feature_key, movie_data in movies.items():
                try:
                    feature_num = int(feature_key)
                    if movie_data.get("type") == "random_movie":
                        feature_movies[feature_num] = {
                            "type": "random_movie",
                            "genre_ids": movie_data.get("genre_ids", []),
                            **{k: movie_data.get(k) for k in RANDOM_FILTER_KEYS},
                        }
                    else:
                        feature_movies[feature_num] = {
                            "type": "movie",
                            "movie": Movie.objects.get(pk=movie_data["id"]),
                            "audio_track": movie_data.get("audio_track_index", 0),
                            "subtitle_track": movie_data.get("subtitle_track_index"),
                            "credits_command_id": movie_data.get("credits_command_id"),
                        }
                except (ValueError, Movie.DoesNotExist):
                    raise ValidationError(
                        f"Invalid movie data for feature {feature_key}", error_code="INVALID_MOVIE_DATA"
                    ) from None

            blocks = cls._process_template_items(template.items.all().order_by("order"), feature_movies)
            preview_data = {
                "name": name.strip(),
                "description": description or "",
                "total_runtime": sum(b["runtime"] for b in blocks),
                "total_blocks": len(blocks),
                "blocks": blocks,
                "preview": preview,
                "template_id": template.id,
                "template_name": template.name,
            }
            if preview:
                return None, preview_data
            return cls._save_new(
                blocks, preview_data, name=name.strip(), description=description or "", template=template
            )

    @staticmethod
    def _template_feature_block(item, feature_num, feature):
        if feature.get("type") != "random_movie":
            return _movie_block(
                item.order,
                feature["movie"],
                feature["audio_track"],
                feature["subtitle_track"],
                item.credits_command_id or feature.get("credits_command_id"),
                feature_number=feature_num,
            )
        avg_duration = Movie.objects.aggregate(avg=Avg("duration"))["avg"] or 7200.0
        genre_ids = feature.get("genre_ids", [])
        genres = list(Genre.objects.filter(pk__in=genre_ids)) if genre_ids else []
        filters = {k: feature.get(k) for k in RANDOM_FILTER_KEYS}
        filter_text = build_filter_description(genres=genres, default_text="Any Movie", **filters)
        return _block(
            item.order,
            "random_movie",
            avg_duration / 60.0,
            f"Random movie ({filter_text})",
            genre_ids=genre_ids,
            **filters,
            filter_text=filter_text,
            feature_number=feature_num,
        )

    @staticmethod
    def _template_trailer_rule_block(item, ref, feature_order_by_number, ref_feature):
        count = item.trailer_count or TrailerRule.DEFAULT_COUNT
        avg = _avg_trailer_duration()
        tag = item.trailer_tag
        tag_details = {"trailer_tag_id": item.trailer_tag_id, "trailer_tag_name": tag.name if tag else None}

        if ref.get("type") == "random_movie":
            return _block(
                item.order,
                "trailer_rule",
                avg * count / 60.0,
                "Trailers for random movie" + _tag_suffix(tag),
                reference_movie_id=None,
                # Resolved from the template items (not the partly built list) so a
                # rule placed before its feature keeps its binding.
                bound_to_block_order=feature_order_by_number.get(ref_feature),
                count=count,
                match_genres=item.match_genre,
                match_certification=item.match_certification,
                match_year=item.match_year,
                year_delta=item.year_delta or 5,
                **tag_details,
                certification_feature=item.certification_feature,
                estimated_duration=avg * count,
            )

        movie = ref["movie"]
        # The template's toggles as explicit criteria, so the preview shows what generation will find.
        delta = item.year_delta or 5
        by_year = item.match_year and movie.year
        genre_ids = list(movie.genres.values_list("id", flat=True)) if item.match_genre else []
        cert = (movie.certification or "") if item.match_certification else ""
        year_from = movie.year - delta if by_year else None
        year_to = movie.year + delta if by_year else None
        stats = match_stats(
            Criteria(
                reference_movie=movie,
                genre_ids=genre_ids,
                certificate_ceiling=cert,
                year_from=year_from,
                year_to=year_to,
                tag=tag,
            )
        )
        if stats["matched"] and stats["avg_duration"]:
            avg = stats["avg_duration"]
        return _block(
            item.order,
            "trailer_rule",
            avg * count / 60.0,
            f"Trailers for {movie.title}" + _tag_suffix(tag),
            reference_movie_id=movie.id,
            reference_movie_title=movie.title,
            count=count,
            matched_count=stats["matched"],
            genre_ids=genre_ids,
            certificate_ceiling=cert,
            year_from=year_from,
            year_to=year_to,
            **tag_details,
            certification_feature=item.certification_feature,
            estimated_duration=avg * count,
        )

    @staticmethod
    def _template_certification_block(item, cert_feature, feature):
        if feature.get("type") == "random_movie":
            return _block(
                item.order,
                "certification",
                0.5,
                f"Certification for random movie (feature {cert_feature})",
                movie_id=None,
                movie_title=None,
                certification=None,
                certification_feature=cert_feature,
                for_random_movie=True,
                random_movie_filters={
                    "genre_ids": feature.get("genre_ids", []),
                    **{k: feature.get(k) for k in RANDOM_FILTER_KEYS},
                },
            )
        movie = feature["movie"]
        system = Settings.get_ratings_system()
        cert = movie.certificate_for(system) or movie.certification
        # The preview reports whether a card CAN be produced, and from what.
        if not cert:
            card_status = "no_certificate"
        elif cert not in Settings.get_valid_ratings(system):
            card_status = "invalid_certificate"
        elif rating_card_video_path(system, cert):
            card_status = "ready"  # user-supplied static card
        elif Certification.objects.filter(movie=movie, ratings_system=system, certification=cert).exists():
            card_status = "ready"  # already generated
        elif rating_card_path(system, cert):
            card_status = "will_generate"
        else:
            card_status = "no_card_source"
        return _block(
            item.order,
            "certification",
            0.5,
            f"Certification for {movie.title}",
            movie_id=movie.id,
            movie_title=movie.title,
            certification=cert,
            ratings_system=system,
            card_status=card_status,
            certification_feature=cert_feature,
        )

    @classmethod
    def _process_template_items(cls, template_items, feature_movies: dict[int, dict]) -> list[dict[str, Any]]:
        blocks = []
        feature_order_by_number = {
            (it.feature_number or 1): it.order for it in template_items if it.item_type == "feature"
        }
        for item in template_items:
            try:
                block = None
                kind = item.item_type
                if kind == "feature":
                    feature_num = item.feature_number or 1
                    if feature_num not in feature_movies:
                        raise ValidationError(
                            f"Movie required for feature {feature_num}", error_code="MISSING_FEATURE_MOVIE"
                        )
                    block = cls._template_feature_block(item, feature_num, feature_movies[feature_num])
                elif kind == "trailer_rule":
                    ref_feature = item.bound_to_feature or 1
                    if ref_feature in feature_movies:
                        block = cls._template_trailer_rule_block(
                            item, feature_movies[ref_feature], feature_order_by_number, ref_feature
                        )
                elif kind == "command":
                    if item.command:
                        block = _command_block(item.order, item.command, item.hold_black)
                elif kind == "bumper":
                    # A tag = random pick, else a specific clip.
                    if item.tag:
                        block = _random_bumper_block(item.order, item.tag, item.count or 1)
                    elif item.bumper:
                        block = _clip_block(item.order, "bumper", item.bumper)
                elif kind == "trailer":
                    if item.trailer:
                        block = _clip_block(item.order, "trailer", item.trailer)
                elif kind == "certification":
                    cert_feature = item.certification_feature or item.bound_to_feature or 1
                    if cert_feature in feature_movies:
                        block = cls._template_certification_block(item, cert_feature, feature_movies[cert_feature])
                elif kind == "audio_bumper":
                    block = _block(item.order, "audio_bumper", 0.25, "Audio bumper")
                if block:
                    blocks.append(block)
            except Exception as e:
                logger.error(f"Error processing template item {item.id}: {e}")
        return blocks

    @staticmethod
    def _create_programme_block(programme, block_data):
        """Save one block dict as a ProgrammeBlock (None when it was skipped)."""
        block_type = block_data["type"]
        details = block_data["details"]
        random_filters = None  # random_movie_* criteria, applied to the block

        block = ProgrammeBlock(programme=programme, order=block_data["order"], content_type=block_type)

        if block_type == "movie":
            block.movie = Movie.objects.get(pk=details["movie_id"])
            block.audio_track_index = details.get("audio_track", 0)
            block.subtitle_track_index = details.get("subtitle_track")
            # Check the FK first: a dangling id only surfaces as a "FOREIGN KEY
            # constraint failed" at commit time under SQLite's deferred checks.
            credits_command_id = details.get("credits_command_id")
            if credits_command_id:
                if Command.objects.filter(pk=credits_command_id).exists():
                    block.credits_command_id = credits_command_id
                else:
                    logger.warning(
                        f"credits_command {credits_command_id} not found - "
                        f"leaving block {block_data['order']} without a credits command"
                    )

        elif block_type == "bumper":
            if details.get("tag_id"):
                block.random_tag = Tag.objects.get(pk=details["tag_id"])
                block.random_count = details.get("count", 1)
            else:
                block.bumper = Bumper.objects.get(pk=details["bumper_id"])

        elif block_type == "command":
            block.command = Command.objects.get(pk=details["command_id"])
            block.hold_black = bool(details.get("hold_black"))

        elif block_type == "trailer":
            block.trailer = Trailer.objects.get(pk=details["trailer_id"])

        elif block_type == "random_movie":
            random_filters = details
            block.random_count = details.get("count", 1)

        elif block_type == "trailer_rule":
            default_count = TrailerRule.DEFAULT_COUNT
            # Resolved leniently: a dangling id drops the filter rather than failing the save.
            tag_id = details.get("trailer_tag_id")
            trailer_tag = TrailerTag.objects.filter(pk=tag_id).first() if tag_id else None

            if details.get("bound_to_block_order") is None:
                # An explicit rule: the reference movie is optional (it seeds and ranks);
                # the hard criteria live on the rule.
                ref_id = details.get("reference_movie_id")
                reference_movie = Movie.objects.get(pk=ref_id) if ref_id else None
                ref_name = reference_movie.title if reference_movie else "criteria"
                rule = TrailerRule.objects.create(
                    name=f"Trailers for {ref_name} (Programme: {programme.name})",
                    reference_movie=reference_movie,
                    certificate_ceiling=details.get("certificate_ceiling") or "",
                    year_from=details.get("year_from"),
                    year_to=details.get("year_to"),
                    number_of_trailers=details.get("count", default_count),
                    trailer_tag=trailer_tag,
                )
                genre_ids = details.get("genre_ids") or []
                if genre_ids:
                    rule.genres.set(Genre.objects.filter(id__in=genre_ids))
                block.trailer_rule = rule
            else:
                block.bound_to_block_order = details.get("bound_to_block_order")
                block.trailer_match_genres = details.get("match_genres", True)
                block.trailer_match_certification = details.get("match_certification", True)
                block.trailer_year_delta = details.get("year_delta", 5)
                block.trailer_tag = trailer_tag
                block.random_count = details.get("count", default_count)

        elif block_type == "audio_bumper":
            # Both lenient: a dangling id falls back to auto behaviour at playlist build.
            if details.get("reference_movie_id"):
                block.movie = Movie.objects.filter(pk=details["reference_movie_id"]).first()
            if details.get("bumper_id"):
                block.bumper = Bumper.objects.filter(pk=details["bumper_id"]).first()

        elif block_type == "certification":
            movie_id = details.get("movie_id")
            if movie_id:
                # Generate a specific film's card now (a random feature's is made at playlist build).
                from .certification_service import CertificationService

                block.movie = Movie.objects.get(pk=movie_id)
                if not CertificationService.get_or_create_certification(block.movie):
                    logger.warning(f"Could not create certification for movie {block.movie.title} - skipping block")
                    return None
            else:
                random_filters = details.get("random_movie_filters", {})

        if random_filters is not None:
            block.random_movie_certification = random_filters.get("certification") or ""
            block.random_movie_year_from = random_filters.get("year_from")
            block.random_movie_year_to = random_filters.get("year_to")
            block.random_movie_runtime_from = random_filters.get("runtime_from")
            block.random_movie_runtime_to = random_filters.get("runtime_to")

        block.save()
        if random_filters and random_filters.get("genre_ids"):
            block.random_movie_genres.set(Genre.objects.filter(pk__in=random_filters["genre_ids"]))
        return block

    @classmethod
    def update_programme(
        cls,
        programme_id: int,
        name: str | None = None,
        description: str | None = None,
        items: list[dict[str, Any]] | None = None,
        title_template_id: int | None = None,
        title_background_type: str | None = None,
        title_background_color: str | None = None,
        title_background_file: str | None = None,
        title_fade_in: float | None = None,
        title_fade_out: float | None = None,
        title_hold: bool | None = None,
    ) -> Programme:
        with transaction.atomic():
            programme = _get_programme(programme_id)

            if name is not None:
                cls.validate_programme_name(name)
                programme.name = name.strip()
            if description is not None:
                programme.description = description

            if title_template_id == 0:
                # 0 unlinks the template and clears the generated title.
                programme.title_template = None
                programme.title_file = ""
            elif title_template_id is not None:
                from ..models import ProgrammeTitleTemplate

                template = ProgrammeTitleTemplate.objects.filter(pk=title_template_id).first()
                if template:
                    programme.title_template = template
                else:
                    logger.warning(f"Title template {title_template_id} not found")

            if title_background_type is not None:
                programme.title_background_type = title_background_type
            if title_background_color is not None:
                programme.title_background_color = title_background_color
            if title_background_file is not None:
                programme.title_background_file = to_usermedia_relative(title_background_file)
            if title_fade_in is not None:
                programme.title_fade_in = max(0.0, title_fade_in)
            if title_fade_out is not None:
                programme.title_fade_out = max(0.0, title_fade_out)
            if title_hold is not None:
                programme.title_hold = title_hold

            if items is not None:
                programme.blocks.all().delete()
                for order, item_data in enumerate(items):
                    try:
                        cls._create_programme_block(programme, cls.process_programme_item(item_data, order))
                    except (ValidationError, NotFoundError):
                        continue
                programme.playlist_stale = True

            programme.save()
            logger.info(f"Updated programme: {programme.name}")

        # Outside the atomic block: the edits commit even if regeneration fails, and
        # the stale flag stays set so the UI can offer a manual retry.
        if programme.playlist_stale:
            cls.refresh_playlist(programme)
        return programme

    @classmethod
    def refresh_playlist(cls, programme: Programme) -> int | None:
        """Single generation path: regenerate/persist the playlist, clearing the stale flag on success."""
        try:
            with transaction.atomic():
                playlist_items = PlaylistService.build_playlist_from_programme(programme)
                PlaylistService.save_playlist_to_database(programme, playlist_items)
            programme.playlist_stale = False
            programme.save(update_fields=["playlist_stale"])
            logger.info(f"Regenerated playlist for programme {programme.name} ({len(playlist_items)} items)")
            return len(playlist_items)
        except Exception:
            logger.exception(f"Automatic playlist regeneration failed for programme {programme.name}")
            if not programme.playlist_stale:
                programme.playlist_stale = True
                programme.save(update_fields=["playlist_stale"])
            return None

    @classmethod
    def run_programme(cls, programme_id: int) -> dict[str, Any]:
        """Load a programme into the player and start playback."""
        from cinefin.api.models import Playlist
        from cinefin.api.mpv_service import mpv_service
        from cinefin.api.services.playout_agent_service import playout_agent_service
        from cinefin.api.services.playout_service import mark_programme_played

        programme = _get_programme(programme_id)
        if not programme.blocks.exists():
            raise ValidationError("Programme has no content to play", error_code="EMPTY_PROGRAMME")

        if not Playlist.objects.filter(programme=programme).exists() or programme.playlist_stale:
            if cls.refresh_playlist(programme) is None:
                raise UnprocessableEntityError(
                    "Failed to generate playlist — check the application logs",
                    error_code="PLAYLIST_GENERATION_FAILED",
                )

        playout_agent_service.ensure_mpv_running()
        if not mpv_service.load_programme(programme):
            raise UnprocessableEntityError(
                "Failed to load programme into playout system", error_code="PROGRAMME_LOAD_FAILED"
            )
        if not mpv_service.start_programme():
            raise UnprocessableEntityError("Failed to start playback", error_code="PROGRAMME_RUN_FAILED")

        mark_programme_played(programme.id)
        logger.info("Started programme: %s", programme.name)
        return {
            "programme_id": programme.id,
            "programme_name": programme.name,
            "message": f"Programme '{programme.name}' started",
        }

    @classmethod
    def duplicate_programme(cls, programme_id: int) -> Programme:
        original = _get_programme(programme_id)

        def _as_new(obj):
            obj.pk = obj.id = None
            obj._state.adding = True

        with transaction.atomic():
            # Re-fetched so mutating it for the insert can't touch `original`.
            copy = Programme.objects.get(pk=programme_id)
            _as_new(copy)
            copy.name = f"{original.name} (copy)"
            copy.title_file = ""
            copy.playlist_stale = False
            copy.last_played_at = None
            copy.save()

            # The M2M and the per-block TrailerRule row are copied explicitly so the
            # copy gets its own editable rule.
            for block in original.blocks.all().order_by("order"):
                genres = list(block.random_movie_genres.all())
                if block.trailer_rule_id:
                    rule = block.trailer_rule
                    rule_genres = list(rule.genres.all())
                    _as_new(rule)
                    rule.save()
                    rule.genres.set(rule_genres)
                    block.trailer_rule = rule
                _as_new(block)
                block.programme = copy
                block.save()
                if genres:
                    block.random_movie_genres.set(genres)

        cls.refresh_playlist(copy)
        logger.info(f"Duplicated programme {original.name!r} -> {copy.name!r} (id {copy.id})")
        return copy

    @classmethod
    def delete_programme(cls, programme_id: int) -> dict[str, Any]:
        programme = _get_programme(programme_id)
        name = programme.name
        programme.delete()
        logger.info(f"Deleted programme: {name}")
        return {
            "programme_id": programme_id,
            "programme_name": name,
            "message": f"Programme '{name}' deleted successfully",
        }
