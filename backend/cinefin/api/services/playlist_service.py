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

        # Pass 1 picks the random features, so certification and trailer-rule
        # blocks bound to them can resolve wherever they sit.
        random_movie_selections = {}
        for block in blocks:
            if block.content_type == "random_movie":
                available = list(build_random_movie_query(block, exclude_empty_paths=True))
                if available:
                    selected = random.sample(available, min(block.random_count or 1, len(available)))
                    random_movie_selections[block.order] = selected
                    logger.info(
                        f"Pre-selected {len(selected)} movie(s) for random_movie block {block.id} (order {block.order})"
                    )

        # De-dupes trailer selections across every rule block in this programme.
        used_trailer_ids: set[int] = set()
        for block in blocks:
            if block.content_type == "random_movie":
                block_items = [
                    PlaylistService._random_movie_item(movie, block)
                    for movie in random_movie_selections.get(block.order, [])
                ]
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
        Playlist.objects.filter(programme=programme).delete()
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

                    block_id = item.get("programme_block_id")
                    block = ProgrammeBlock.objects.filter(pk=block_id).first() if block_id else None
                    playlist_item.movie_playback = MoviePlayback.objects.create(
                        movie=movie,
                        audio_track_index=item.get("audio_track", 0),
                        subtitle_track_index=item.get("subtitle_track"),
                        credits_command_id=block.credits_command_id if block else None,
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
        """A movie, trailer, user media, audio bumper or command block's items (a
        failing block is skipped)."""
        kind = block.content_type
        try:
            if kind == "bumper":
                # RANDOM when it carries a tag (or count > 1), else the specific clip.
                if block.random_tag or block.random_count > 1:
                    return PlaylistService._process_random_bumper_block(block)
                return PlaylistService._process_clip_block(block, "bumper")
            if kind in ("movie", "trailer"):
                return PlaylistService._process_clip_block(block, kind)
            if kind == "audio_bumper":
                return PlaylistService._process_audio_bumper_block(block)
            if kind == "command":
                return PlaylistService._process_command_block(block)
            logger.warning(f"Unknown block type: {kind}")
        except Exception as e:
            logger.error(f"Error processing block {block.id} ({kind}): {e}", exc_info=True)
        return []

    @staticmethod
    def _process_clip_block(block: ProgrammeBlock, kind: str) -> list[dict[str, Any]]:
        """A specific movie, trailer or user media item."""
        obj = resolve_block_entity(block, kind)
        if not obj:
            logger.error(f"No {kind} found for block {block.id}")
            return []
        file_path = resolve_media_path(obj)
        if not file_path:
            logger.warning(f"{kind.capitalize()} {obj.id} has no file path")
            return []
        if kind == "movie":
            return [
                _item(
                    "movie",
                    obj,
                    block,
                    _movie_metadata(obj),
                    file_path,
                    audio_track=block.audio_track_index or 0,
                    subtitle_track=block.subtitle_track_index,
                )
            ]
        if kind == "trailer":
            return [_item("trailer", obj, block, {"trailer_title": obj.title, "tmdb_id": obj.tmdbid}, file_path)]
        return [_item("bumper", obj, block, {"bumper_title": obj.title, "tags": _tag_names(obj)}, file_path)]

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
        fmt = PlaylistService._AUDIO_CODEC_MAP.get((track.codec or "").lower().strip())
        # Atmos rides on TrueHD: flag it when the track is object-based wide.
        if fmt == "dolby_truehd" and ((track.channels or 0) >= 8 or "atmos" in (track.title or "").lower()):
            fmt = "dolby_atmos"
        return fmt

    @staticmethod
    def _process_audio_bumper_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        """Audio-format intro: explicit override, else a random bumper matching the bound feature's format."""
        if block.bumper is not None:
            bumper = block.bumper
            if not bumper.file_path:
                logger.info(f"Audio bumper block {block.id}: override '{bumper.title}' has no file, skipping")
                return []
            logger.info(f"Audio bumper: {bumper.title} (explicit override)")
            return [_item("bumper", bumper, block, {"bumper_title": bumper.title, "override": True})]

        movie = block.movie
        if movie is None:
            logger.info(f"Audio bumper block {block.id}: not bound to a feature, skipping")
            return []
        # The bound feature's own block carries the audio-track choice.
        movie_block = ProgrammeBlock.objects.filter(
            programme=block.programme, content_type="movie", movie=movie
        ).first()
        track_index = movie_block.audio_track_index if movie_block else None
        fmt = PlaylistService._detect_audio_format(movie, track_index)
        if not fmt:
            logger.info(f"Audio bumper block {block.id}: no audio format for {movie.title}, skipping")
            return []
        bumper = _playable_bumpers().filter(audio_format=fmt).order_by("?").first()
        if not bumper:
            logger.info(f"Audio bumper block {block.id}: no bumper marked '{fmt}', skipping")
            return []
        logger.info(f"Audio bumper: {bumper.title} ({fmt}) before {movie.title}")
        return [
            _item("bumper", bumper, block, {"bumper_title": bumper.title, "audio_format": fmt, "feature": movie.title})
        ]

    @staticmethod
    def _process_random_bumper_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        tag = block.random_tag
        query = _playable_bumpers()
        if tag:
            query = query.filter(tags=tag)
        available = list(query.distinct())
        if not available:
            logger.warning(f"No bumpers found for random selection in block {block.id}")
            return []
        return [
            _item(
                "bumper",
                bumper,
                block,
                {
                    "bumper_title": bumper.title,
                    "tags": _tag_names(bumper),
                    "random_selection": True,
                    "selection_criteria": tag.name if tag else "Any",
                },
            )
            for bumper in random.sample(available, min(block.random_count or 1, len(available)))
        ]

    @staticmethod
    def _process_command_block(block: ProgrammeBlock) -> list[dict[str, Any]]:
        """hold_black -> a real black-loop item (until command done + duration); else a "command_cue" marker (no MPV entry)."""
        command = resolve_block_entity(block, "command")
        if not command:
            logger.error(f"No command found for block {block.id}")
            return []
        hold_seconds = float(command.duration or 0)
        item = {
            "type": "command_cue",
            "file_path": "",
            "title": command.name,
            "duration": 0,
            "programme_block_id": block.id,
            "content_id": command.id,
            "metadata": {"command_name": command.name, "provider": command.provider},
        }
        if block.hold_black:
            if not os.path.exists(system_black_path()):
                logger.warning(
                    f"Command block {block.id}: hold requested but the black clip is missing; firing as instant cue"
                )
                return [item]
            if hold_seconds <= 0:
                logger.info(
                    f"Command block {block.id}: '{command.name}' has no duration set; "
                    f"black will hold until the command completes"
                )
            item.update(type="command", file_path=system_black_stream_url(), duration=hold_seconds)
        return [item]

    @staticmethod
    def _process_trailer_rule_block(
        block: ProgrammeBlock,
        random_movie_selections: dict[int, list[Movie]],
        used_trailer_ids: set[int],
    ) -> list[dict[str, Any]]:
        """used_trailer_ids (mutated in place) de-dupes across trailer-rule blocks so two rules never pick the same trailer."""
        from cinefin.api.services.trailer_matching import Criteria, select_trailers

        if block.trailer_rule:
            rule = block.trailer_rule
            criteria = Criteria.from_rule(rule)
            count = rule.number_of_trailers or TrailerRule.DEFAULT_COUNT
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
            count = block.random_count or TrailerRule.DEFAULT_COUNT
            logger.info(f"Trailer rule block {block.id} using random movie: {selected_movies[0].title}")
        else:
            logger.error(f"No trailer rule or bound block found for block {block.id}")
            return []

        selected, match_info = select_trailers(criteria, count, exclude_ids=used_trailer_ids)
        used_trailer_ids.update(t.id for t in selected)
        ref_movie, tag = criteria.reference_movie, criteria.tag
        logger.info(
            f"Trailer rule block {block.id}: {match_info['matched']} match "
            f"{f'for {ref_movie.title}' if ref_movie else '(criteria only)'}"
            f"{f' (tag: {tag.name})' if tag else ''}, selected {len(selected)}"
        )
        metadata = {
            "rule_based_selection": True,
            "reference_movie": ref_movie.title if ref_movie else None,
            "tag_filter": tag.name if tag else None,
            "matched": match_info["matched"],
            "requested": match_info["requested"],
        }
        return [_item("trailer", trailer, block, dict(metadata)) for trailer in selected]

    @staticmethod
    def _process_certification_block(
        block: ProgrammeBlock, random_movie_selections: dict[int, list[Movie]]
    ) -> list[dict[str, Any]]:
        """A certification card for the block's film, or (with no film) for the
        random feature whose filters it shares."""
        from .certification_service import CertificationService

        movie = block.movie
        if movie is None:
            genres = set(block.random_movie_genres.values_list("id", flat=True))
            for block_order, selected_movies in random_movie_selections.items():
                if not selected_movies:
                    continue
                random_block = ProgrammeBlock.objects.filter(
                    programme=block.programme, order=block_order, content_type="random_movie"
                ).first()
                if random_block is None:
                    continue
                if genres == set(random_block.random_movie_genres.values_list("id", flat=True)) and all(
                    getattr(block, f) == getattr(random_block, f)
                    for f in ("random_movie_certification", "random_movie_year_from", "random_movie_year_to")
                ):
                    movie = selected_movies[0]
                    logger.info(f"Matched certification block {block.id} to random movie: {movie.title}")
                    break

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

        return [
            {
                "type": "certification",
                "file_path": resolve_media_path(certification),
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
    def _random_movie_item(movie: Movie, block: ProgrammeBlock) -> dict[str, Any]:
        metadata = _movie_metadata(movie)
        metadata["random_selection"] = True
        metadata["selection_criteria"] = {
            "filter_text": build_filter_description_from_block(block),
            "genre_ids": [g.id for g in block.random_movie_genres.all()],
            "certification": block.random_movie_certification or None,
            "year_from": block.random_movie_year_from,
            "year_to": block.random_movie_year_to,
            "runtime_from": block.random_movie_runtime_from,
            "runtime_to": block.random_movie_runtime_to,
        }
        return _item("movie", movie, block, metadata, audio_track=0, subtitle_track=None)


def _item(kind, obj, block, metadata, file_path=None, **extra):
    """One playlist item for a clip (``file_path`` defaults to its stream URL)."""
    return {
        "type": kind,
        "file_path": resolve_media_path(obj) if file_path is None else file_path,
        "title": obj.title,
        "duration": obj.duration,
        "programme_block_id": block.id,
        "content_id": obj.id,
        **extra,
        "metadata": metadata,
    }


def _movie_metadata(movie):
    return {
        "movie_id": movie.id,
        "movie_title": movie.title,
        "year": movie.year,
        "genres": [genre.name for genre in movie.genres.all()],
        "certification": movie.certification,
        "thumbnail_url": movie.thumbnail_url,
    }


def _tag_names(bumper):
    return [tag.name for tag in bumper.tags.all()]


def _playable_bumpers():
    return Bumper.objects.exclude(file_path__isnull=True).exclude(file_path="")
