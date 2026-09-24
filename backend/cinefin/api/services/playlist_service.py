import logging
import os
import random
from typing import Any

import requests

from cinefin.api.models import (
    Bumper,
    Certification,
    Command,
    Movie,
    MoviePlayback,
    Playlist,
    PlaylistItem,
    Programme,
    ProgrammeBlock,
    Trailer,
    TrailerRule,
)
from cinefin.api.utils.assets import system_black_path, system_black_stream_url
from cinefin.api.utils.media_paths import usermedia_abs_path
from cinefin.api.utils.programme_utils import build_filter_description_from_block, build_random_movie_query

from .block_types import resolve_block_entity, resolve_media_path

logger = logging.getLogger(__name__)


class PlaylistService:
    PREFLIGHT_TIMEOUT = 4

    @staticmethod
    def _preflight_item_title(item: PlaylistItem) -> str:
        obj = item.content_object
        if obj is not None:
            if hasattr(obj, "title"):
                return obj.title
            if hasattr(obj, "movie"):
                return obj.movie.title
        return os.path.basename((item.file or "").split("?")[0]) or f"item {item.order + 1}"

    @classmethod
    def verify_playlist_availability(cls, playlist: Playlist) -> list[str]:
        """Pre-flight reachability check run at load time so problems surface before Run, not mid-screening."""
        warnings: list[str] = []
        session = requests.Session()

        for item in playlist.items.all().order_by("order"):
            if item.content_type in ("command", "system"):
                continue
            path = item.file or ""
            if not path:
                continue

            title = cls._preflight_item_title(item)

            if path.startswith(("http://", "https://")):
                try:
                    resp = session.head(path, timeout=cls.PREFLIGHT_TIMEOUT, allow_redirects=True)
                    if resp.status_code == 405:
                        # Server disallows HEAD (some media servers do) — probe one byte
                        resp = session.get(
                            path,
                            timeout=cls.PREFLIGHT_TIMEOUT,
                            stream=True,
                            headers={"Range": "bytes=0-0"},
                        )
                        resp.close()
                    if resp.status_code >= 400:
                        warnings.append(f"{title}: HTTP {resp.status_code}")
                except requests.RequestException as exc:
                    warnings.append(f"{title}: {exc.__class__.__name__}")
            elif not os.path.exists(path):
                warnings.append(f"{title}: file missing on disk")

        if warnings:
            logger.warning(
                f"Playlist pre-flight for '{playlist.programme.name}': {len(warnings)} unreachable item(s): {warnings}"
            )
        return warnings

    @staticmethod
    def build_playlist_from_programme(programme: Programme) -> list[dict[str, Any]]:
        """Two-pass build: pre-select random_movie blocks, then resolve all blocks to streaming-URL items."""
        playlist_items = []
        blocks = list(programme.blocks.all().order_by("order"))

        logger.info(f"Building playlist for '{programme.name}'")

        random_movie_selections = {}
        for block in blocks:
            if block.content_type == "random_movie":
                selected_movies = PlaylistService._select_random_movies(block)
                if selected_movies:
                    random_movie_selections[block.order] = selected_movies
                    logger.info(
                        f"Pre-selected {len(selected_movies)} movie(s) for random_movie block {block.id} (order {block.order})"
                    )

        # used_trailer_ids de-dupes trailer selections across every rule block in this programme.
        used_trailer_ids: set[int] = set()
        for block in blocks:
            if block.content_type == "random_movie":
                selected_movies = random_movie_selections.get(block.order, [])
                block_items = PlaylistService._process_random_movie_block_with_selection(block, selected_movies)
            elif block.content_type == "certification":
                block_items = PlaylistService._process_certification_block(block, random_movie_selections)
            elif block.content_type == "trailer_rule":
                block_items = PlaylistService._process_trailer_rule_block(
                    block, random_movie_selections, used_trailer_ids
                )
            else:
                block_items = PlaylistService._process_programme_block(block)
            playlist_items.extend(block_items)

        # Append black video at end - prevents MPV going idle.
        if os.path.exists(system_black_path()):
            playlist_items.append({"type": "system", "file_path": system_black_stream_url(), "title": "Black"})

        logger.info(f"Built playlist for programme '{programme.name}' with {len(playlist_items)} items")
        return playlist_items

    @staticmethod
    def save_playlist_to_database(programme: Programme, playlist_items: list[dict[str, Any]]) -> Playlist:
        try:
            existing_playlist = Playlist.objects.get(programme=programme)
            existing_playlist.delete()
            logger.info(f"Deleted existing playlist for programme {programme.id}")
        except Playlist.DoesNotExist:
            pass

        playlist = Playlist.objects.create(programme=programme)

        # Instant command cues ("command_cue") get no item of their own — they attach to the next
        # real item's order so the DB playlist stays strictly 1:1 with what MPV is given.
        from cinefin.api.models import PlaylistCue

        pending_cues: list[dict[str, Any]] = []
        order = -1
        for item in playlist_items:
            if item.get("type") == "command_cue":
                pending_cues.append(item)
                continue
            order += 1

            playlist_item = PlaylistItem(
                playlist=playlist,
                order=order,
                file=item.get("file_path", ""),
                content_type=item.get("type", ""),
                programme_block_id=item.get("programme_block_id"),
                metadata=item.get("metadata") or {},
            )

            content_id = item.get("content_id")
            if content_id:
                if item["type"] == "movie":
                    movie = Movie.objects.get(pk=content_id)

                    credits_command_id = None
                    programme_block_id = item.get("programme_block_id")
                    if programme_block_id:
                        try:
                            block = ProgrammeBlock.objects.get(pk=programme_block_id)
                            if block.credits_command_id:
                                credits_command_id = block.credits_command_id
                        except ProgrammeBlock.DoesNotExist:
                            pass

                    playlist_item.movie_playback = MoviePlayback.objects.create(
                        movie=movie,
                        audio_track_index=item.get("audio_track", 0),
                        subtitle_track_index=item.get("subtitle_track"),
                        credits_command_id=credits_command_id,
                    )
                elif item["type"] == "trailer":
                    playlist_item.trailer = Trailer.objects.get(pk=content_id)
                elif item["type"] == "bumper":
                    playlist_item.bumper = Bumper.objects.get(pk=content_id)
                elif item["type"] == "command":
                    playlist_item.command = Command.objects.get(pk=content_id)
                elif item["type"] == "certification":
                    playlist_item.certification = Certification.objects.get(pk=content_id)

            playlist_item.save()

            for seq, cue in enumerate(pending_cues):
                PlaylistCue.objects.create(
                    playlist=playlist,
                    command_id=cue.get("content_id"),
                    command_name=cue.get("title", ""),
                    fires_before_order=order,
                    seq=seq,
                )
            pending_cues = []

        if pending_cues:
            # No item follows (black sentinel missing on disk) — these can never fire.
            logger.warning(
                f"Dropping {len(pending_cues)} trailing command cue(s) for '{programme.name}': "
                f"no playlist item follows them"
            )

        logger.info(
            f"Saved playlist for programme '{programme.name}': {order + 1} items, {playlist.cues.count()} command cues"
        )
        return playlist

    @staticmethod
    def _process_programme_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        items = []

        try:
            if block.content_type == "movie":
                items.extend(PlaylistService._process_movie_block(block))

            elif block.content_type == "trailer":
                items.extend(PlaylistService._process_trailer_block(block))

            elif block.content_type == "bumper":
                # A "bumper" block is RANDOM when it carries a tag (or count > 1), else it plays the specific clip.
                if block.random_tag or block.random_count > 1:
                    items.extend(PlaylistService._process_random_bumper_block(block))
                else:
                    items.extend(PlaylistService._process_bumper_block(block))

            elif block.content_type == "audio_bumper":
                items.extend(PlaylistService._process_audio_bumper_block(block))

            elif block.content_type == "command":
                items.extend(PlaylistService._process_command_block(block))

            # trailer_rule / certification / random_movie are dispatched to dedicated handlers upstream.
            else:
                logger.warning(f"Unknown block type: {block.content_type}")

        except Exception as e:
            logger.error(f"Error processing block {block.id} ({block.content_type}): {e}")

        return items

    @staticmethod
    def _process_movie_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        try:
            movie = resolve_block_entity(block, "movie")
            if not movie:
                logger.error(f"No movie found for block {block.id}")
                return []

            file_path = resolve_media_path(movie)

            if not file_path:
                logger.warning(f"Movie {movie.id} has no file path")
                return []

            return [
                {
                    "type": "movie",
                    "file_path": file_path,
                    "title": movie.title,
                    "duration": movie.duration,
                    "programme_block_id": block.id,
                    "content_id": movie.id,
                    "audio_track": block.audio_track_index or 0,
                    "subtitle_track": block.subtitle_track_index,
                    "metadata": {
                        "movie_id": movie.id,
                        "movie_title": movie.title,
                        "year": movie.year,
                        "genres": [genre.name for genre in movie.genres.all()],
                        "certification": movie.certification,
                        "thumbnail_url": movie.thumbnail_url,
                    },
                }
            ]

        except Exception as e:
            logger.error(f"Error processing movie block {block.id}: {e}", exc_info=True)
            return []

    @staticmethod
    def _process_trailer_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        try:
            trailer = resolve_block_entity(block, "trailer")
            if not trailer:
                logger.error(f"No trailer found for block {block.id}")
                return []

            file_path = resolve_media_path(trailer)

            if not file_path:
                logger.warning(f"Trailer {trailer.id} has no file path")
                return []

            return [
                {
                    "type": "trailer",
                    "file_path": file_path,
                    "title": trailer.title,
                    "duration": trailer.duration,
                    "programme_block_id": block.id,
                    "content_id": trailer.id,
                    "metadata": {"trailer_title": trailer.title, "tmdb_id": trailer.tmdbid},
                }
            ]

        except Exception as e:
            logger.error(f"Error processing trailer block {block.id}: {e}")
            return []

    @staticmethod
    def _process_bumper_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        try:
            bumper = resolve_block_entity(block, "bumper")
            if not bumper:
                logger.error(f"No bumper found for block {block.id}")
                return []

            file_path = resolve_media_path(bumper)

            if not file_path:
                logger.warning(f"Bumper {bumper.id} has no file path")
                return []

            return [
                {
                    "type": "bumper",
                    "file_path": file_path,
                    "title": bumper.title,
                    "duration": bumper.duration,
                    "programme_block_id": block.id,
                    "content_id": bumper.id,
                    "metadata": {"bumper_title": bumper.title, "tags": [tag.name for tag in bumper.tags.all()]},
                }
            ]

        except Exception as e:
            logger.error(f"Error processing bumper block {block.id}: {e}")
            return []

    # Raw audio-track codecs -> our format keys (see models.AUDIO_FORMATS).
    _AUDIO_CODEC_MAP = {
        "ac3": "dolby_digital",
        "ac-3": "dolby_digital",
        "eac3": "dolby_digital",
        "e-ac-3": "dolby_digital",
        "ec-3": "dolby_digital",
        "truehd": "dolby_truehd",
        "mlp": "dolby_truehd",
        "dts": "dts",
        "dca": "dts",
        "dts-hd": "dts_hd",
        "dtshd": "dts_hd",
        "dts_hd": "dts_hd",
        "dtsx": "dts_x",
        "dts:x": "dts_x",
    }

    @staticmethod
    def _detect_audio_format(movie, track_index):
        """Best-effort audio format of the track that will play for a feature."""
        tracks = list(movie.audio_tracks.all())
        if not tracks:
            return None
        track = next((t for t in tracks if t.index == (track_index or 0)), tracks[0])
        codec = (track.codec or "").lower().strip()
        fmt = PlaylistService._AUDIO_CODEC_MAP.get(codec)
        # Atmos rides on TrueHD (and E-AC-3) — flag it when the track is object-based wide.
        if fmt == "dolby_truehd" and ((track.channels or 0) >= 8 or "atmos" in (track.title or "").lower()):
            fmt = "dolby_atmos"
        return fmt

    @staticmethod
    def _process_audio_bumper_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        """Audio-format intro: explicit override, else a random bumper matching the bound (or next) feature's format."""
        if block.bumper is not None:
            bumper = block.bumper
            if not bumper.file_path:
                logger.info(f"Audio bumper block {block.id}: override '{bumper.title}' has no file, skipping")
                return []
            file_path = resolve_media_path(bumper)
            logger.info(f"Audio bumper: {bumper.title} (explicit override)")
            return [
                {
                    "type": "bumper",
                    "file_path": file_path,
                    "title": bumper.title,
                    "duration": bumper.duration,
                    "programme_block_id": block.id,
                    "content_id": bumper.id,
                    "metadata": {"bumper_title": bumper.title, "override": True},
                }
            ]

        if block.movie is not None:
            movie = block.movie
            # The bound feature's own block carries the audio-track choice.
            movie_block = (
                ProgrammeBlock.objects.filter(programme=block.programme, content_type="movie", movie=movie)
                .order_by("order")
                .first()
            )
            track_index = movie_block.audio_track_index if movie_block else None
        else:
            next_movie_block = (
                ProgrammeBlock.objects.filter(programme=block.programme, content_type="movie", order__gt=block.order)
                .order_by("order")
                .first()
            )
            movie = next_movie_block.movie if next_movie_block else None
            track_index = next_movie_block.audio_track_index if next_movie_block else None
        if movie is None:
            logger.info(f"Audio bumper block {block.id}: no feature to match, skipping")
            return []
        fmt = PlaylistService._detect_audio_format(movie, track_index)
        if not fmt:
            logger.info(f"Audio bumper block {block.id}: no audio format for {movie.title}, skipping")
            return []
        bumper = (
            Bumper.objects.filter(audio_format=fmt)
            .exclude(file_path__isnull=True)
            .exclude(file_path="")
            .order_by("?")
            .first()
        )
        if not bumper:
            logger.info(f"Audio bumper block {block.id}: no bumper marked '{fmt}', skipping")
            return []
        file_path = resolve_media_path(bumper)
        logger.info(f"Audio bumper: {bumper.title} ({fmt}) before {movie.title}")
        return [
            {
                "type": "bumper",
                "file_path": file_path,
                "title": bumper.title,
                "duration": bumper.duration,
                "programme_block_id": block.id,
                "content_id": bumper.id,
                "metadata": {"bumper_title": bumper.title, "audio_format": fmt, "feature": movie.title},
            }
        ]

    @staticmethod
    def _process_random_bumper_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        count = block.random_count or 1
        tag = block.random_tag

        bumpers_query = Bumper.objects.exclude(file_path__isnull=True).exclude(file_path="")
        if tag:
            bumpers_query = bumpers_query.filter(tags=tag)

        available_bumpers = list(bumpers_query.distinct())
        if not available_bumpers:
            logger.warning(f"No bumpers found for random selection in block {block.id}")
            return []

        selected_count = min(count, len(available_bumpers))
        selected_bumpers = random.sample(available_bumpers, selected_count)

        items = []
        for bumper in selected_bumpers:
            file_path = resolve_media_path(bumper)
            items.append(
                {
                    "type": "bumper",
                    "file_path": file_path,
                    "title": bumper.title,
                    "duration": bumper.duration,
                    "programme_block_id": block.id,
                    "content_id": bumper.id,
                    "metadata": {
                        "bumper_title": bumper.title,
                        "tags": [t.name for t in bumper.tags.all()],
                        "random_selection": True,
                        "selection_criteria": tag.name if tag else "Any",
                    },
                }
            )

        return items

    @staticmethod
    def _process_command_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        """hold_black -> a real black-loop item (until command done + duration); else a "command_cue" marker (no MPV entry)."""
        try:
            command = resolve_block_entity(block, "command")
            if not command:
                logger.error(f"No command found for block {block.id}")
                return []

            hold_seconds = float(command.duration or 0)
            if block.hold_black:
                if not os.path.exists(system_black_path()):
                    logger.warning(
                        f"Command block {block.id}: hold requested but the black clip is missing; firing as instant cue"
                    )
                elif hold_seconds <= 0:
                    logger.info(
                        f"Command block {block.id}: '{command.name}' has no duration set; "
                        f"black will hold until the command completes"
                    )
                if os.path.exists(system_black_path()):
                    return [
                        {
                            "type": "command",
                            "file_path": system_black_stream_url(),
                            "title": command.name,
                            "duration": hold_seconds,
                            "programme_block_id": block.id,
                            "content_id": command.id,
                            "metadata": {"command_name": command.name, "provider": command.provider},
                        }
                    ]

            return [
                {
                    "type": "command_cue",
                    "file_path": "",
                    "title": command.name,
                    "duration": 0,
                    "programme_block_id": block.id,
                    "content_id": command.id,
                    "metadata": {"command_name": command.name, "provider": command.provider},
                }
            ]

        except Exception as e:
            logger.error(f"Error processing command block {block.id}: {e}")
            return []

    @staticmethod
    def _exclude_own_trailer(trailers_query, ref_movie):
        from cinefin.api.services.trailer_matching import exclude_own_trailer

        return exclude_own_trailer(trailers_query, ref_movie)

    @staticmethod
    def _process_trailer_rule_block(
        block: ProgrammeBlock,
        random_movie_selections: dict[int, list[Movie]] = None,
        used_trailer_ids: set[int] | None = None,
    ) -> list[dict[str, Any]]:
        """used_trailer_ids (mutated in place) de-dupes across trailer-rule blocks so two rules never pick the same trailer."""
        from cinefin.api.services.trailer_matching import Criteria, select_trailers

        default_count = TrailerRule.DEFAULT_COUNT
        used_trailer_ids = used_trailer_ids if used_trailer_ids is not None else set()

        if block.trailer_rule:
            rule = block.trailer_rule
            criteria = Criteria.from_rule(rule)
            count = rule.number_of_trailers or default_count
        elif block.bound_to_block_order is not None and random_movie_selections:
            selected_movies = random_movie_selections.get(block.bound_to_block_order, [])
            if not selected_movies:
                logger.warning(
                    f"No random movie selected for trailer rule block {block.id} "
                    f"(bound to order {block.bound_to_block_order})"
                )
                return []
            criteria = Criteria.from_movie(
                selected_movies[0],
                match_genres=block.trailer_match_genres,
                match_certification=block.trailer_match_certification,
                year_delta=block.trailer_year_delta or 5,
            )
            criteria.tag = block.trailer_tag
            count = block.random_count or default_count
            logger.info(f"Trailer rule block {block.id} using random movie: {selected_movies[0].title}")
        else:
            logger.error(f"No trailer rule or bound block found for block {block.id}")
            return []

        selected_trailers, match_info = select_trailers(criteria, count, exclude_ids=used_trailer_ids)
        used_trailer_ids.update(t.id for t in selected_trailers)
        ref_movie = criteria.reference_movie
        trailer_tag = criteria.tag
        logger.info(
            f"Trailer rule block {block.id}: {match_info['matched']} match "
            f"{f'for {ref_movie.title}' if ref_movie else '(criteria only)'}"
            f"{f' (tag: {trailer_tag.name})' if trailer_tag else ''}, selected {len(selected_trailers)}"
        )

        items = []
        for trailer in selected_trailers:
            file_path = resolve_media_path(trailer)
            items.append(
                {
                    "type": "trailer",
                    "file_path": file_path,
                    "title": trailer.title,
                    "duration": trailer.duration,
                    "programme_block_id": block.id,
                    "content_id": trailer.id,
                    "metadata": {
                        "rule_based_selection": True,
                        "reference_movie": ref_movie.title if ref_movie else None,
                        "tag_filter": trailer_tag.name if trailer_tag else None,
                        "matched": match_info["matched"],
                        "requested": match_info["requested"],
                    },
                }
            )

        return items

    @staticmethod
    def _process_certification_block(
        block: ProgrammeBlock, random_movie_selections: dict[int, list[Movie]] = None
    ) -> list[dict[str, Any]]:
        """For certs linked to a random movie (no content_object), match by filter criteria then generate dynamically."""
        from .certification_service import CertificationService

        movie = block.movie
        if movie is None:
            # Match a random-movie block by its filter criteria (usually 1:1 by order).
            if random_movie_selections:
                for block_order, selected_movies in random_movie_selections.items():
                    if selected_movies:
                        try:
                            random_block = ProgrammeBlock.objects.get(
                                programme=block.programme, order=block_order, content_type="random_movie"
                            )
                            block_genres = set(block.random_movie_genres.values_list("id", flat=True))
                            random_genres = set(random_block.random_movie_genres.values_list("id", flat=True))
                            filters_match = (
                                block_genres == random_genres
                                and block.random_movie_certification == random_block.random_movie_certification
                                and block.random_movie_year_from == random_block.random_movie_year_from
                                and block.random_movie_year_to == random_block.random_movie_year_to
                            )
                            if filters_match:
                                movie = selected_movies[0]
                                logger.info(f"Matched certification block {block.id} to random movie: {movie.title}")
                                break
                        except ProgrammeBlock.DoesNotExist:
                            continue

        if not movie:
            logger.warning(f"No movie found for certification block {block.id}")
            return []

        certification = CertificationService.get_or_create_certification(movie)

        if not certification:
            logger.warning(f"Could not get/create certification for movie {movie.title} in block {block.id}")
            return []

        if not certification.file_path or not os.path.exists(usermedia_abs_path(certification.file_path)):
            logger.warning(f"Certification file not found: {certification.file_path}")
            return []

        file_path = resolve_media_path(certification)

        return [
            {
                "type": "certification",
                "file_path": file_path,
                "title": f"Certification: {certification.certification}",
                "duration": 5.0,
                "programme_block_id": block.id,
                "content_id": certification.id,
                "metadata": {
                    "certification": certification.certification,
                    "movie_title": movie.title,
                    "movie_id": movie.id,
                    "certification_id": certification.id,
                    "dynamically_generated": block.movie is None,
                },
            }
        ]

    @staticmethod
    def _build_random_movie_playlist_item(movie: Movie, block: ProgrammeBlock) -> dict[str, Any]:
        file_path = resolve_media_path(movie)

        return {
            "type": "movie",
            "file_path": file_path,
            "title": movie.title,
            "duration": movie.duration,
            "programme_block_id": block.id,
            "content_id": movie.id,
            "audio_track": 0,
            "subtitle_track": None,
            "metadata": {
                "movie_id": movie.id,
                "movie_title": movie.title,
                "year": movie.year,
                "genres": [genre.name for genre in movie.genres.all()],
                "certification": movie.certification,
                "thumbnail_url": movie.thumbnail_url,
                "random_selection": True,
                "selection_criteria": {
                    "filter_text": build_filter_description_from_block(block),
                    "genre_ids": [g.id for g in block.random_movie_genres.all()],
                    "certification": block.random_movie_certification or None,
                    "year_from": block.random_movie_year_from,
                    "year_to": block.random_movie_year_to,
                    "runtime_from": block.random_movie_runtime_from,
                    "runtime_to": block.random_movie_runtime_to,
                },
            },
        }

    @staticmethod
    def _select_random_movies(block: ProgrammeBlock) -> list[Movie]:
        count = block.random_count or 1

        movies_query = build_random_movie_query(block, exclude_empty_paths=True)

        available_movies = list(movies_query)
        if not available_movies:
            return []

        selected_count = min(count, len(available_movies))
        return random.sample(available_movies, selected_count)

    @staticmethod
    def _process_random_movie_block_with_selection(
        block: ProgrammeBlock, selected_movies: list[Movie]
    ) -> list[dict[str, Any]]:
        return [PlaylistService._build_random_movie_playlist_item(movie, block) for movie in selected_movies]
