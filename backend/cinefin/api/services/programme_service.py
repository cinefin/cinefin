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


class ProgrammeService:
    @staticmethod
    def validate_programme_name(name: str) -> None:
        if not name or not name.strip():
            raise ValidationError("Programme name is required", error_code="PROGRAMME_NAME_REQUIRED")

    @staticmethod
    def process_programme_item(item_data: dict[str, Any], order: int) -> dict[str, Any]:
        item_type = item_data.get("type")
        if not item_type:
            raise ValidationError("Item type is required", error_code="ITEM_TYPE_REQUIRED")

        def _req(key: str):
            # A missing key is a client error (400), not an unhandled KeyError → 500.
            value = item_data.get(key)
            if value is None:
                raise ValidationError(f"{key} is required for a '{item_type}' item", error_code="MISSING_FIELD")
            return value

        try:
            if item_type == "movie":
                movie = fetch_block_entity("movie", _req("movie_id"))
                runtime = (movie.duration or 0) / 60.0

                return {
                    "order": order,
                    "type": "movie",
                    "runtime": runtime,
                    "title": movie.title,
                    "details": {
                        "movie_id": movie.id,
                        "movie_title": movie.title,
                        "duration": movie.duration,
                        "audio_track": item_data.get("audio_track_index", item_data.get("audio_track", 0)),
                        "subtitle_track": item_data.get("subtitle_track_index", item_data.get("subtitle_track")),
                        "credits_command_id": item_data.get("credits_command_id"),
                    },
                }

            elif item_type == "trailer":
                trailer = fetch_block_entity("trailer", _req("trailer_id"))
                runtime = (trailer.duration or 0) / 60.0

                return {
                    "order": order,
                    "type": "trailer",
                    "runtime": runtime,
                    "title": trailer.title,
                    "details": {"trailer_id": trailer.id, "trailer_title": trailer.title, "duration": trailer.duration},
                }

            elif item_type == "bumper":
                # A tag_id/tag_name means a random pick; otherwise a specific clip.
                tag_id = item_data.get("tag_id")
                tag_name = item_data.get("tag_name")

                if tag_id or tag_name:
                    count = item_data.get("count", 1)
                    tag = Tag.objects.get(pk=tag_id) if tag_id else Tag.objects.get(name=tag_name)

                    avg_duration = tag.bumper_set.aggregate(avg=Avg("duration"))["avg"] or 30.0
                    estimated_runtime = (avg_duration * count) / 60.0

                    return {
                        "order": order,
                        "type": "bumper",
                        "runtime": estimated_runtime,
                        "title": f"Random user media ({tag.name})",
                        "details": {
                            "tag_id": tag.id,
                            "tag_name": tag.name,
                            "count": count,
                            "estimated_duration": avg_duration * count,
                        },
                    }

                bumper = fetch_block_entity("bumper", _req("bumper_id"))
                runtime = (bumper.duration or 0) / 60.0

                return {
                    "order": order,
                    "type": "bumper",
                    "runtime": runtime,
                    "title": bumper.title,
                    "details": {"bumper_id": bumper.id, "bumper_title": bumper.title, "duration": bumper.duration},
                }

            elif item_type == "random_movie":
                genre_ids = item_data.get("genre_ids", [])
                certification = item_data.get("certification")
                year_from = item_data.get("year_from")
                year_to = item_data.get("year_to")
                runtime_from = item_data.get("runtime_from")
                runtime_to = item_data.get("runtime_to")
                count = item_data.get("count", 1)

                genres = list(Genre.objects.filter(pk__in=genre_ids)) if genre_ids else []
                genre_names = [g.name for g in genres]

                filter_text = build_filter_description(
                    genres=genres,
                    certification=certification,
                    year_from=year_from,
                    year_to=year_to,
                    runtime_from=runtime_from,
                    runtime_to=runtime_to,
                    default_text="Any",
                )

                movies_qs = Movie.objects.all()
                for genre in genres:
                    movies_qs = movies_qs.filter(genres=genre)
                if certification:
                    movies_qs = movies_qs.filter(certification__iexact=certification)
                if year_from:
                    movies_qs = movies_qs.filter(year__gte=year_from)
                if year_to:
                    movies_qs = movies_qs.filter(year__lte=year_to)
                if runtime_from:
                    movies_qs = movies_qs.filter(runtime__gte=runtime_from)
                if runtime_to:
                    movies_qs = movies_qs.filter(runtime__lte=runtime_to)

                avg_runtime = movies_qs.aggregate(avg=Avg("runtime"))["avg"] or 120.0
                estimated_runtime = (avg_runtime * count) / 60.0
                matching_count = movies_qs.count()

                return {
                    "order": order,
                    "type": "random_movie",
                    "runtime": estimated_runtime,
                    "title": f"Random movie ({filter_text})",
                    "details": {
                        "genre_ids": genre_ids,
                        "genre_names": genre_names,
                        "certification": certification,
                        "year_from": year_from,
                        "year_to": year_to,
                        "runtime_from": runtime_from,
                        "runtime_to": runtime_to,
                        "count": count,
                        "estimated_duration": avg_runtime * count,
                        "matching_movies": matching_count,
                    },
                }

            elif item_type == "command":
                command = fetch_block_entity("command", _req("command_id"))
                hold_black = bool(item_data.get("hold_black"))

                return {
                    "order": order,
                    "type": "command",
                    # Instant cues take no screen time; hold blocks occupy the command's duration.
                    "runtime": (command.duration or 0) / 60.0 if hold_black else 0.0,
                    "title": command.name,
                    "details": {
                        "command_id": command.id,
                        "command_name": command.name,
                        "provider": command.provider,
                        "hold_black": hold_black,
                        "duration": command.duration,
                    },
                }

            elif item_type == "trailer_rule":
                ref_id = item_data.get("reference_movie_id")
                ref_movie = fetch_block_entity("movie", ref_id) if ref_id else None
                count = item_data.get("count", 3)

                # Optional filter resolved leniently: a dangling id drops the filter rather than failing the save.
                trailer_tag = None
                if item_data.get("trailer_tag_id"):
                    trailer_tag = TrailerTag.objects.filter(pk=item_data["trailer_tag_id"]).first()

                avg_duration = Trailer.objects.aggregate(avg=Avg("duration"))["avg"] or 150.0
                estimated_runtime = (avg_duration * count) / 60.0
                label = ref_movie.title if ref_movie else "criteria"

                return {
                    "order": order,
                    "type": "trailer_rule",
                    "runtime": estimated_runtime,
                    "title": f"Trailers for {label}" + (f" (tag: {trailer_tag.name})" if trailer_tag else ""),
                    "details": {
                        "reference_movie_id": ref_movie.id if ref_movie else None,
                        "reference_movie_title": ref_movie.title if ref_movie else None,
                        "count": count,
                        "genre_ids": item_data.get("genre_ids") or [],
                        "certificate_ceiling": item_data.get("certificate_ceiling") or "",
                        "year_from": item_data.get("year_from"),
                        "year_to": item_data.get("year_to"),
                        "trailer_tag_id": trailer_tag.id if trailer_tag else None,
                        "trailer_tag_name": trailer_tag.name if trailer_tag else None,
                        "estimated_duration": avg_duration * count,
                        # A rule bound to a random-movie feature defers resolution to playlist
                        # generation; these must be threaded through or the bound branch never fires.
                        "bound_to_block_order": item_data.get("bound_to_block_order"),
                        "match_genres": item_data.get("match_genres", True),
                        "match_certification": item_data.get("match_certification", True),
                        "year_delta": item_data.get("year_delta", 5),
                    },
                }

            elif item_type == "certification":
                movie = fetch_block_entity("movie", _req("movie_id"))

                return {
                    "order": order,
                    "type": "certification",
                    "runtime": 0.5,
                    "title": f"Certification for {movie.title}",
                    "details": {
                        "movie_id": movie.id,
                        "movie_title": movie.title,
                        "certification": item_data.get("certification") or movie.certification,
                    },
                }

            elif item_type == "audio_bumper":
                details = {}
                title = "Audio bumper"
                if item_data.get("reference_movie_id"):
                    movie = fetch_block_entity("movie", item_data["reference_movie_id"])
                    details["reference_movie_id"] = movie.id
                    details["reference_movie_title"] = movie.title
                    title = f"Audio intro for {movie.title}"
                if item_data.get("bumper_id"):
                    bumper = fetch_block_entity("bumper", item_data["bumper_id"])
                    details["bumper_id"] = bumper.id
                    details["bumper_title"] = bumper.title
                    title = bumper.title
                return {
                    "order": order,
                    "type": "audio_bumper",
                    "runtime": 0.25,
                    "title": title,
                    "details": details,
                }

            else:
                raise ValidationError(f"Unknown item type: {item_type}", error_code="UNKNOWN_ITEM_TYPE")

        except Tag.DoesNotExist:
            raise NotFoundError("Tag not found", error_code="TAG_NOT_FOUND") from None

    @classmethod
    def create_programme(
        cls, name: str, description: str = "", items: list[dict[str, Any]] = None, preview: bool = False
    ) -> tuple[Programme | None, dict[str, Any]]:
        with transaction.atomic():
            if not preview:
                cls.validate_programme_name(name)

            programme_blocks = []
            total_runtime = 0.0

            if items:
                for order, item_data in enumerate(items):
                    block_data = cls.process_programme_item(item_data, order)
                    programme_blocks.append(block_data)
                    total_runtime += block_data["runtime"]

            preview_data = {
                "name": name.strip(),
                "description": description or "",
                "total_runtime": total_runtime,
                "total_blocks": len(programme_blocks),
                "blocks": programme_blocks,
                "preview": preview,
            }

            if preview:
                return None, preview_data

            programme = Programme.objects.create(name=name.strip(), description=description or "")

            for block_data in programme_blocks:
                block = cls._create_programme_block(programme, block_data)
                if block is None:
                    logger.info(
                        f"Skipped creating block of type {block_data.get('type', 'unknown')} due to validation failure"
                    )

            item_count = cls.refresh_playlist(programme)
            preview_data["playlist_generated"] = item_count is not None
            preview_data["playlist_items"] = item_count or 0
            if item_count is not None:
                logger.info(
                    f"Created programme: {programme.name} with "
                    f"{len(programme_blocks)} blocks and {item_count} playlist items"
                )

            return programme, preview_data

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

            template_items = template.items.all().order_by("order")
            feature_movies = {}

            for feature_key, movie_data in movies.items():
                try:
                    feature_num = int(feature_key)

                    if movie_data.get("type") == "random_movie":
                        feature_movies[feature_num] = {
                            "type": "random_movie",
                            "genre_ids": movie_data.get("genre_ids", []),
                            "certification": movie_data.get("certification"),
                            "year_from": movie_data.get("year_from"),
                            "year_to": movie_data.get("year_to"),
                            "runtime_from": movie_data.get("runtime_from"),
                            "runtime_to": movie_data.get("runtime_to"),
                        }
                    else:
                        movie = Movie.objects.get(pk=movie_data["id"])
                        feature_movies[feature_num] = {
                            "type": "movie",
                            "movie": movie,
                            "audio_track": movie_data.get("audio_track_index", 0),
                            "subtitle_track": movie_data.get("subtitle_track_index"),
                            "credits_command_id": movie_data.get("credits_command_id"),
                        }
                except (ValueError, Movie.DoesNotExist):
                    raise ValidationError(
                        f"Invalid movie data for feature {feature_key}", error_code="INVALID_MOVIE_DATA"
                    ) from None

            programme_blocks = cls._process_template_items(template_items, feature_movies)
            total_runtime = sum(block["runtime"] for block in programme_blocks)

            preview_data = {
                "name": name.strip(),
                "description": description or "",
                "total_runtime": total_runtime,
                "total_blocks": len(programme_blocks),
                "blocks": programme_blocks,
                "preview": preview,
                "template_id": template.id,
                "template_name": template.name,
            }

            if preview:
                return None, preview_data

            programme = Programme.objects.create(
                name=name.strip(),
                description=description or "",
                template=template,
            )

            for block_data in programme_blocks:
                block = cls._create_programme_block(programme, block_data)
                if block is None:
                    logger.info(
                        f"Skipped creating block of type {block_data.get('type', 'unknown')} due to validation failure"
                    )

            item_count = cls.refresh_playlist(programme)
            preview_data["playlist_generated"] = item_count is not None
            preview_data["playlist_items"] = item_count or 0
            if item_count is not None:
                logger.info(
                    f"Created programme from template: {programme.name} with "
                    f"{len(programme_blocks)} blocks and {item_count} playlist items"
                )

            return programme, preview_data

    @staticmethod
    def _process_template_items(template_items, feature_movies: dict[int, dict]) -> list[dict[str, Any]]:
        programme_blocks = []

        # Lets a trailer rule bound to a random-movie feature resolve even when the rule
        # appears BEFORE that feature (the random_movie block isn't built yet at that point).
        feature_order_by_number = {
            (it.feature_number or 1): it.order for it in template_items if it.item_type == "feature"
        }

        for item in template_items:
            try:
                block_data = None

                if item.item_type == "feature":
                    feature_num = item.feature_number or 1
                    if feature_num not in feature_movies:
                        raise ValidationError(
                            f"Movie required for feature {feature_num}", error_code="MISSING_FEATURE_MOVIE"
                        )

                    feature_data = feature_movies[feature_num]

                    if feature_data.get("type") == "random_movie":
                        avg_duration = Movie.objects.aggregate(avg=Avg("duration"))["avg"] or 7200.0
                        runtime = avg_duration / 60.0

                        genre_ids = feature_data.get("genre_ids", [])
                        genres = list(Genre.objects.filter(pk__in=genre_ids)) if genre_ids else []
                        filter_text = build_filter_description(
                            genres=genres,
                            certification=feature_data.get("certification"),
                            year_from=feature_data.get("year_from"),
                            year_to=feature_data.get("year_to"),
                            runtime_from=feature_data.get("runtime_from"),
                            runtime_to=feature_data.get("runtime_to"),
                            default_text="Any Movie",
                        )

                        block_data = {
                            "order": item.order,
                            "type": "random_movie",
                            "runtime": runtime,
                            "title": f"Random movie ({filter_text})",
                            "details": {
                                "genre_ids": genre_ids,
                                "certification": feature_data.get("certification"),
                                "year_from": feature_data.get("year_from"),
                                "year_to": feature_data.get("year_to"),
                                "runtime_from": feature_data.get("runtime_from"),
                                "runtime_to": feature_data.get("runtime_to"),
                                "filter_text": filter_text,
                                "feature_number": feature_num,
                            },
                        }
                    else:
                        movie = feature_data["movie"]
                        runtime = (movie.duration or 0) / 60.0

                        block_data = {
                            "order": item.order,
                            "type": "movie",
                            "runtime": runtime,
                            "title": movie.title,
                            "details": {
                                "movie_id": movie.id,
                                "movie_title": movie.title,
                                "duration": movie.duration,
                                "audio_track": feature_data["audio_track"],
                                "subtitle_track": feature_data["subtitle_track"],
                                "feature_number": feature_num,
                                "credits_command_id": item.credits_command_id
                                if item.credits_command_id
                                else feature_data.get("credits_command_id"),
                            },
                        }

                elif item.item_type == "trailer_rule":
                    ref_feature = item.bound_to_feature or 1
                    if ref_feature not in feature_movies:
                        continue

                    ref_data = feature_movies[ref_feature]
                    count = item.trailer_count or TrailerRule.DEFAULT_COUNT

                    avg_duration = Trailer.objects.aggregate(avg=Avg("duration"))["avg"] or 150.0
                    estimated_runtime = (avg_duration * count) / 60.0

                    if ref_data.get("type") == "random_movie":
                        # Resolved from template items (not the partially-built list) so
                        # rule-before-feature ordering doesn't drop the binding.
                        random_movie_order = feature_order_by_number.get(ref_feature)

                        block_data = {
                            "order": item.order,
                            "type": "trailer_rule",
                            "runtime": estimated_runtime,
                            "title": "Trailers for random movie"
                            + (f" (tag: {item.trailer_tag.name})" if item.trailer_tag else ""),
                            "details": {
                                "reference_movie_id": None,
                                "bound_to_block_order": random_movie_order,
                                "count": count,
                                "match_genres": item.match_genre,
                                "match_certification": item.match_certification,
                                "match_year": item.match_year,
                                "year_delta": item.year_delta or 5,
                                "trailer_tag_id": item.trailer_tag_id,
                                "trailer_tag_name": item.trailer_tag.name if item.trailer_tag else None,
                                "certification_feature": item.certification_feature,
                                "estimated_duration": avg_duration * count,
                            },
                        }
                    else:
                        ref_movie = ref_data["movie"]

                        # Translate the template's toggles into explicit criteria so the preview
                        # shows what playlist generation will find.
                        crit_genre_ids = list(ref_movie.genres.values_list("id", flat=True)) if item.match_genre else []
                        crit_cert = (ref_movie.certification or "") if item.match_certification else ""
                        crit_year_from = (
                            (ref_movie.year - (item.year_delta or 5)) if (item.match_year and ref_movie.year) else None
                        )
                        crit_year_to = (
                            (ref_movie.year + (item.year_delta or 5)) if (item.match_year and ref_movie.year) else None
                        )
                        _crit = Criteria(
                            reference_movie=ref_movie,
                            genre_ids=crit_genre_ids,
                            certificate_ceiling=crit_cert,
                            year_from=crit_year_from,
                            year_to=crit_year_to,
                            tag=item.trailer_tag,
                        )
                        stats = match_stats(_crit)
                        if stats["matched"] and stats["avg_duration"]:
                            avg_duration = stats["avg_duration"]
                            estimated_runtime = (avg_duration * count) / 60.0

                        block_data = {
                            "order": item.order,
                            "type": "trailer_rule",
                            "runtime": estimated_runtime,
                            "title": f"Trailers for {ref_movie.title}"
                            + (f" (tag: {item.trailer_tag.name})" if item.trailer_tag else ""),
                            "details": {
                                "reference_movie_id": ref_movie.id,
                                "reference_movie_title": ref_movie.title,
                                "count": count,
                                "matched_count": stats["matched"],
                                "genre_ids": crit_genre_ids,
                                "certificate_ceiling": crit_cert,
                                "year_from": crit_year_from,
                                "year_to": crit_year_to,
                                "trailer_tag_id": item.trailer_tag_id,
                                "trailer_tag_name": item.trailer_tag.name if item.trailer_tag else None,
                                "certification_feature": item.certification_feature,
                                "estimated_duration": avg_duration * count,
                            },
                        }

                elif item.item_type == "command":
                    if not item.command:
                        continue

                    block_data = {
                        "order": item.order,
                        "type": "command",
                        "runtime": (item.command.duration or 0) / 60.0 if item.hold_black else 0.0,
                        "title": item.command.name,
                        "details": {
                            "command_id": item.command.id,
                            "command_name": item.command.name,
                            "provider": item.command.provider,
                            "hold_black": item.hold_black,
                            "duration": item.command.duration,
                        },
                    }

                elif item.item_type == "bumper":
                    # A tag = random pick, else a specific clip.
                    if item.tag:
                        count = item.count or 1
                        avg_duration = item.tag.bumper_set.aggregate(avg=Avg("duration"))["avg"] or 30.0
                        estimated_runtime = (avg_duration * count) / 60.0

                        block_data = {
                            "order": item.order,
                            "type": "bumper",
                            "runtime": estimated_runtime,
                            "title": f"Random user media ({item.tag.name})",
                            "details": {
                                "tag_id": item.tag.id,
                                "tag_name": item.tag.name,
                                "count": count,
                                "estimated_duration": avg_duration * count,
                            },
                        }
                    elif item.bumper:
                        runtime = (item.bumper.duration or 0) / 60.0

                        block_data = {
                            "order": item.order,
                            "type": "bumper",
                            "runtime": runtime,
                            "title": item.bumper.title,
                            "details": {
                                "bumper_id": item.bumper.id,
                                "bumper_title": item.bumper.title,
                                "duration": item.bumper.duration,
                            },
                        }
                    else:
                        continue

                elif item.item_type == "trailer":
                    if not item.trailer:
                        continue

                    runtime = (item.trailer.duration or 0) / 60.0

                    block_data = {
                        "order": item.order,
                        "type": "trailer",
                        "runtime": runtime,
                        "title": item.trailer.title,
                        "details": {
                            "trailer_id": item.trailer.id,
                            "trailer_title": item.trailer.title,
                            "duration": item.trailer.duration,
                        },
                    }

                elif item.item_type == "certification":
                    cert_feature = item.certification_feature or item.bound_to_feature or 1
                    if cert_feature not in feature_movies:
                        continue

                    feature_data = feature_movies[cert_feature]

                    if feature_data.get("type") == "random_movie":
                        block_data = {
                            "order": item.order,
                            "type": "certification",
                            "runtime": 0.5,
                            "title": f"Certification for random movie (feature {cert_feature})",
                            "details": {
                                "movie_id": None,
                                "movie_title": None,
                                "certification": None,
                                "certification_feature": cert_feature,
                                "for_random_movie": True,
                                "random_movie_filters": {
                                    "genre_ids": feature_data.get("genre_ids", []),
                                    "certification": feature_data.get("certification"),
                                    "year_from": feature_data.get("year_from"),
                                    "year_to": feature_data.get("year_to"),
                                    "runtime_from": feature_data.get("runtime_from"),
                                    "runtime_to": feature_data.get("runtime_to"),
                                },
                            },
                        }
                    else:
                        ref_movie = feature_data["movie"]
                        system = Settings.get_ratings_system()
                        cert_value = ref_movie.certificate_for(system) or ref_movie.certification

                        # The preview reports whether a card CAN be produced, and from what.
                        if not cert_value:
                            card_status = "no_certificate"
                        elif cert_value not in Settings.get_valid_ratings(system):
                            card_status = "invalid_certificate"
                        elif rating_card_video_path(system, cert_value):
                            card_status = "ready"  # user-supplied static card
                        elif Certification.objects.filter(
                            movie=ref_movie, ratings_system=system, certification=cert_value
                        ).exists():
                            card_status = "ready"  # already generated
                        elif rating_card_path(system, cert_value):
                            card_status = "will_generate"
                        else:
                            card_status = "no_card_source"

                        block_data = {
                            "order": item.order,
                            "type": "certification",
                            "runtime": 0.5,
                            "title": f"Certification for {ref_movie.title}",
                            "details": {
                                "movie_id": ref_movie.id,
                                "movie_title": ref_movie.title,
                                "certification": cert_value,
                                "ratings_system": system,
                                "card_status": card_status,
                                "certification_feature": cert_feature,
                            },
                        }

                elif item.item_type == "audio_bumper":
                    block_data = {
                        "order": item.order,
                        "type": "audio_bumper",
                        "runtime": 0.25,
                        "title": "Audio bumper",
                        "details": {},
                    }

                if block_data:
                    programme_blocks.append(block_data)

            except Exception as e:
                logger.error(f"Error processing template item {item.id}: {e}")
                continue

        return programme_blocks

    @staticmethod
    def _create_programme_block(programme, block_data):
        block_type = block_data["type"]
        details = block_data["details"]

        # For a specific-movie certification, pre-generate the certification first
        # (random-movie certs have movie_id None and are generated during playlist build).
        if block_type == "certification":
            movie_id = details.get("movie_id")

            if movie_id:
                from .certification_service import CertificationService

                movie = Movie.objects.get(pk=movie_id)

                certification = CertificationService.get_or_create_certification(movie)
                if not certification:
                    logger.warning(f"Could not create certification for movie {movie.title} - skipping block")
                    return None

        block = ProgrammeBlock(programme=programme, order=block_data["order"], content_type=block_type)

        if block_type == "movie":
            block.movie = Movie.objects.get(pk=details["movie_id"])
            block.audio_track_index = details.get("audio_track", 0)
            block.subtitle_track_index = details.get("subtitle_track")

            # Validate the FK exists first: a dangling id only surfaces as a "FOREIGN KEY
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
            # A tag means random (random_tag + count), else a specific clip (bumper FK).
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
            # genre_ids (M2M) is added after block.save()
            block.random_movie_certification = details.get("certification") or ""
            block.random_movie_year_from = details.get("year_from")
            block.random_movie_year_to = details.get("year_to")
            block.random_movie_runtime_from = details.get("runtime_from")
            block.random_movie_runtime_to = details.get("runtime_to")
            block.random_count = details.get("count", 1)

        elif block_type == "trailer_rule":
            reference_movie_id = details.get("reference_movie_id")
            default_count = TrailerRule.DEFAULT_COUNT

            # Resolved leniently: a dangling id drops the filter rather than failing the save.
            trailer_tag = None
            if details.get("trailer_tag_id"):
                trailer_tag = TrailerTag.objects.filter(pk=details["trailer_tag_id"]).first()

            if details.get("bound_to_block_order") is None:
                # Explicit rule: the reference movie is optional (it just seeds/ranks);
                # hard criteria live on the rule directly.
                reference_movie = Movie.objects.get(pk=reference_movie_id) if reference_movie_id else None
                ref_name = reference_movie.title if reference_movie else "criteria"
                rule_name = f"Trailers for {ref_name} (Programme: {programme.name})"

                trailer_rule = TrailerRule.objects.create(
                    name=rule_name,
                    reference_movie=reference_movie,
                    certificate_ceiling=details.get("certificate_ceiling") or "",
                    year_from=details.get("year_from"),
                    year_to=details.get("year_to"),
                    number_of_trailers=details.get("count", default_count),
                    trailer_tag=trailer_tag,
                )
                genre_ids = details.get("genre_ids") or []
                if genre_ids:
                    trailer_rule.genres.set(Genre.objects.filter(id__in=genre_ids))

                block.trailer_rule = trailer_rule
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
                block.movie = Movie.objects.get(pk=movie_id)
            else:
                cert_feature = details.get("certification_feature")
                filters = details.get("random_movie_filters", {})

                # Genre IDs are added via M2M after block.save().
                block.random_movie_certification = filters.get("certification") or ""
                block.random_movie_year_from = filters.get("year_from")
                block.random_movie_year_to = filters.get("year_to")
                block.random_movie_runtime_from = filters.get("runtime_from")
                block.random_movie_runtime_to = filters.get("runtime_to")

                logger.info(f"Created certification block for random movie feature {cert_feature}")

        block.save()

        if block_type == "random_movie":
            genre_ids = details.get("genre_ids", [])
            if genre_ids:
                genres = Genre.objects.filter(pk__in=genre_ids)
                block.random_movie_genres.set(genres)
        elif block_type == "certification" and not details.get("movie_id"):
            filters = details.get("random_movie_filters", {})
            genre_ids = filters.get("genre_ids", [])
            if genre_ids:
                genres = Genre.objects.filter(pk__in=genre_ids)
                block.random_movie_genres.set(genres)

        return block

    @classmethod
    def update_programme(
        cls,
        programme_id: int,
        name: str | None = None,
        description: str | None = None,
        items: list[dict[str, Any]] | None = None,
        title_template_id: int | None = None,
        title_duration: int | None = None,
        title_background_type: str | None = None,
        title_background_color: str | None = None,
        title_background_file: str | None = None,
        title_fade_in: float | None = None,
        title_fade_out: float | None = None,
    ) -> Programme:
        with transaction.atomic():
            try:
                programme = Programme.objects.get(pk=programme_id)
            except Programme.DoesNotExist:
                raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

            if name is not None:
                cls.validate_programme_name(name)
                programme.name = name.strip()

            if description is not None:
                programme.description = description

            if title_template_id is not None:
                from ..models import ProgrammeTitleTemplate

                if title_template_id == 0:
                    # 0 means remove template and clear generated title
                    programme.title_template = None
                    programme.title_file = ""
                    logger.info(f"Unlinked title template from programme {programme_id}")
                else:
                    try:
                        template = ProgrammeTitleTemplate.objects.get(pk=title_template_id)
                        programme.title_template = template
                        logger.info(f"Linked title template {template.name} to programme {programme_id}")
                    except ProgrammeTitleTemplate.DoesNotExist:
                        logger.warning(f"Title template {title_template_id} not found")

            if title_duration is not None:
                programme.title_duration = title_duration if title_duration > 0 else None

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

            if items is not None:
                programme.blocks.all().delete()

                for order, item_data in enumerate(items):
                    try:
                        block_data = cls.process_programme_item(item_data, order)
                        block = cls._create_programme_block(programme, block_data)
                        if block is None:
                            logger.info(
                                f"Skipped creating block of type {block_data.get('type', 'unknown')} due to validation failure"
                            )

                    except (ValidationError, NotFoundError):
                        continue

                programme.playlist_stale = True

            programme.save()
            logger.info(f"Updated programme: {programme.name}")

        # Runs outside the atomic block: the block edits commit even if regeneration
        # fails, and the stale flag stays set so the UI can offer a manual retry.
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
        """Load a programme into the player and start playback (mirrors POST /playout/load + /run)."""
        from cinefin.api.models import Playlist
        from cinefin.api.mpv_service import mpv_service
        from cinefin.api.services.playout_agent_service import playout_agent_service
        from cinefin.api.services.playout_service import mark_programme_played

        try:
            programme = Programme.objects.get(pk=programme_id)
        except Programme.DoesNotExist:
            raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

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
        try:
            original = Programme.objects.get(pk=programme_id)
        except Programme.DoesNotExist:
            raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

        with transaction.atomic():
            # Re-fetch so mutating for the insert can't touch `original`.
            copy = Programme.objects.get(pk=programme_id)
            copy.pk = None
            copy.id = None
            copy._state.adding = True
            copy.name = f"{original.name} (copy)"
            copy.title_file = ""
            copy.playlist_stale = False
            copy.last_played_at = None
            copy.save()

            # The M2M (random_movie_genres) and the per-block TrailerRule row must be
            # copied explicitly so the copy gets its own editable rule row.
            for block in original.blocks.all().order_by("order"):
                genres = list(block.random_movie_genres.all())
                if block.trailer_rule_id:
                    rule = block.trailer_rule
                    rule_genres = list(rule.genres.all())
                    rule.pk = None
                    rule.id = None
                    rule._state.adding = True
                    rule.save()
                    rule.genres.set(rule_genres)
                    block.trailer_rule = rule
                block.pk = None
                block.id = None
                block._state.adding = True
                block.programme = copy
                block.save()
                if genres:
                    block.random_movie_genres.set(genres)

        cls.refresh_playlist(copy)

        logger.info(f"Duplicated programme {original.name!r} -> {copy.name!r} (id {copy.id})")
        return copy

    @classmethod
    def delete_programme(cls, programme_id: int) -> dict[str, Any]:
        try:
            programme = Programme.objects.get(pk=programme_id)
        except Programme.DoesNotExist:
            raise NotFoundError("Programme not found", error_code="PROGRAMME_NOT_FOUND") from None

        programme_name = programme.name
        programme.delete()

        logger.info(f"Deleted programme: {programme_name}")

        return {
            "programme_id": programme_id,
            "programme_name": programme_name,
            "message": f"Programme '{programme_name}' deleted successfully",
        }
