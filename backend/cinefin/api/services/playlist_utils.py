"""Shared playlist operation helpers."""

import logging
from typing import Any

from django.db.models import QuerySet

from cinefin.api.models import Playlist, PlaylistItem
from cinefin.api.services.certification_service import CertificationService

logger = logging.getLogger(__name__)


class PlaylistUtils:
    @classmethod
    def build_playlist_item_details(cls, playlist_item: PlaylistItem) -> dict[str, Any]:
        obj = playlist_item.content_object
        kind = playlist_item.content_type
        item_data = {
            "order": playlist_item.order,
            "file_path": playlist_item.file,
            "duration": 0.0,
            "title": "Unknown",
            "type": kind,
            "programme_block_id": playlist_item.programme_block_id,
            "content_id": None,
            "audio_track": None,
            "subtitle_track": None,
            "metadata": {},
        }
        if obj is None:
            return item_data

        if kind == "movie":
            movie = obj.movie
            item_data.update(
                duration=movie.duration or 0.0,
                title=movie.title,
                content_id=movie.id,
                audio_track=obj.audio_track_index,
                subtitle_track=obj.subtitle_track_index,
                metadata={
                    "movie_title": movie.title,
                    "year": movie.year,
                    "genres": [genre.name for genre in movie.genres.all()],
                    "certification": movie.certification,
                    "director": movie.director,
                    "description": movie.description or "",
                    "tmdb_id": movie.tmdbid,
                    "resolution": movie.resolution,
                    "file_size": movie.file_size,
                    "thumbnail_url": movie.thumbnail_url,
                },
            )
        elif kind == "trailer":
            item_data.update(
                duration=obj.duration or 0.0,
                title=obj.title,
                content_id=obj.id,
                # Stored generation-time metadata rides on top of recomputable trailer facts.
                metadata={
                    "trailer_title": obj.title,
                    "tmdb_id": obj.tmdbid,
                    "year": obj.year,
                    "certification": obj.content_rating,
                    # Trailers have no artwork: borrow the advertised film's poster if in the library.
                    "thumbnail_url": getattr(obj.linked_movie(), "thumbnail_url", None),
                    **(playlist_item.metadata or {}),
                },
            )
        elif kind == "bumper":
            item_data.update(
                duration=obj.duration or 0.0,
                title=obj.title,
                content_id=obj.id,
                metadata={
                    "bumper_title": obj.title,
                    "tags": [tag.name for tag in obj.tags.all()],
                    "random_selection": False,
                    "selection_criteria": None,
                },
            )
        elif kind == "command":
            item_data.update(
                duration=obj.duration or 0.0,
                title=obj.name,
                content_id=obj.id,
                metadata={"command_name": obj.name, "provider": obj.provider},
            )
        elif kind == "certification":
            movie = obj.movie
            item_data.update(
                duration=float(CertificationService.CARD_SECONDS),
                title=f"Certification: {obj.certification}",
                content_id=obj.id,
                metadata={
                    "certification": obj.certification,
                    "movie_title": movie.title if movie else "",
                    "movie_id": movie.id if movie else None,
                    "certification_id": obj.id,
                },
            )
        return item_data

    @staticmethod
    def _get_item_duration(item: PlaylistItem) -> float:
        obj = item.content_object
        if item.content_type == "movie" and obj is not None:
            return obj.movie.duration or 0.0
        if item.content_type == "certification":
            return float(CertificationService.CARD_SECONDS)
        if obj is not None and hasattr(obj, "duration"):
            return obj.duration or 0.0
        return 0.0

    @classmethod
    def calculate_playlist_timing(
        cls,
        playlist_items: QuerySet[PlaylistItem],
        current_position: int | None = None,
        current_time_pos: float | None = None,
    ) -> dict[str, float]:
        total_duration = elapsed_time = 0.0
        for item in playlist_items:
            duration = cls._get_item_duration(item)
            total_duration += duration
            if current_position is not None:
                if item.order < current_position:
                    elapsed_time += duration
                elif item.order == current_position and current_time_pos is not None:
                    elapsed_time += min(current_time_pos, duration)
        return {
            "total_duration": total_duration,
            "elapsed_time": elapsed_time,
            "remaining_time": max(0, total_duration - elapsed_time),
        }

    @classmethod
    def enhance_mpv_playlist_item(cls, mpv_item: dict[str, Any], playlist: Playlist | None = None) -> dict[str, Any]:
        """An MPV playlist entry with its database item's details."""
        enhanced = {**mpv_item, "duration": None, "details": {}}
        position = enhanced.get("programme_position")
        if not playlist or position is None:
            return enhanced
        try:
            d = cls.build_playlist_item_details(playlist.items.get(order=position))
        except Exception as e:
            logger.warning(f"Could not enhance playlist item {position}: {e}")
            return enhanced
        enhanced.update(
            type=d["type"],
            duration=d["duration"],
            title=d["title"],
            details={
                k: d[k] for k in ("programme_block_id", "content_id", "audio_track", "subtitle_track", "metadata")
            },
        )
        return enhanced
