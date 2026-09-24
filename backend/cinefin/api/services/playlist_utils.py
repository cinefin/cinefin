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
        content_obj = playlist_item.content_object

        item_data = {
            "order": playlist_item.order,
            "file_path": playlist_item.file,
            "duration": 0.0,
            "title": "Unknown",
            "type": playlist_item.content_type,
            "programme_block_id": playlist_item.programme_block_id,
            "content_id": None,
            "audio_track": None,
            "subtitle_track": None,
            "metadata": {},
        }

        if playlist_item.content_type == "movie" and hasattr(content_obj, "movie"):
            movie = content_obj.movie
            item_data.update(
                {
                    "duration": movie.duration or 0.0,
                    "title": movie.title,
                    "content_id": movie.id,
                    "audio_track": content_obj.audio_track_index,
                    "subtitle_track": content_obj.subtitle_track_index,
                    "metadata": {
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
                }
            )
        elif playlist_item.content_type == "trailer" and content_obj:
            item_data.update(
                {
                    "duration": content_obj.duration or 0.0,
                    "title": content_obj.title,
                    "content_id": content_obj.id,
                    # Stored generation-time metadata rides on top of recomputable trailer facts.
                    "metadata": {
                        "trailer_title": content_obj.title,
                        "tmdb_id": getattr(content_obj, "tmdbid", None),
                        "year": getattr(content_obj, "year", None),
                        "certification": getattr(content_obj, "content_rating", None),
                        # Trailers have no artwork — borrow the advertised film's poster if in the library.
                        "thumbnail_url": (
                            content_obj.associated_movie.thumbnail_url if content_obj.associated_movie else None
                        ),
                        **(playlist_item.metadata or {}),
                    },
                }
            )
        elif playlist_item.content_type == "bumper" and content_obj:
            item_data.update(
                {
                    "duration": content_obj.duration or 0.0,
                    "title": content_obj.title,
                    "content_id": content_obj.id,
                    "metadata": {
                        "bumper_title": content_obj.title,
                        "tags": [tag.name for tag in content_obj.tags.all()] if hasattr(content_obj, "tags") else [],
                        "random_selection": getattr(content_obj, "random_selection", False),
                        "selection_criteria": getattr(content_obj, "selection_criteria", None),
                    },
                }
            )
        elif playlist_item.content_type == "command" and content_obj:
            item_data.update(
                {
                    "duration": content_obj.duration or 0.0,
                    "title": content_obj.name,
                    "content_id": content_obj.id,
                    "metadata": {"command_name": content_obj.name, "provider": content_obj.provider},
                }
            )
        elif playlist_item.content_type == "certification" and content_obj:
            # content_obj is either a Certification object or a Movie used for certification
            if hasattr(content_obj, "movie"):
                movie_title = content_obj.movie.title if content_obj.movie else ""
                movie_id = content_obj.movie.id if content_obj.movie else None
                certification = content_obj.certification
                duration = float(CertificationService.CARD_SECONDS)
            else:
                movie_title = content_obj.title
                movie_id = content_obj.id
                certification = content_obj.certification
                duration = float(CertificationService.CARD_SECONDS)

            item_data.update(
                {
                    "duration": duration,
                    "title": f"Certification: {certification}",
                    "content_id": content_obj.id,
                    "metadata": {
                        "certification": certification,
                        "movie_title": movie_title,
                        "movie_id": movie_id,
                        "certification_id": content_obj.id,
                    },
                }
            )

        return item_data

    @classmethod
    def _get_item_duration(cls, item: PlaylistItem) -> float:
        content_obj = item.content_object

        if item.content_type == "movie" and hasattr(content_obj, "movie"):
            return content_obj.movie.duration or 0.0
        elif content_obj and hasattr(content_obj, "duration"):
            return content_obj.duration or 0.0
        elif item.content_type == "certification":
            return float(CertificationService.CARD_SECONDS)

        return 0.0

    @classmethod
    def calculate_playlist_timing(
        cls,
        playlist_items: QuerySet[PlaylistItem],
        current_position: int | None = None,
        current_time_pos: float | None = None,
    ) -> dict[str, float]:
        total_duration = 0.0
        elapsed_time = 0.0

        for item in playlist_items:
            duration = cls._get_item_duration(item)
            total_duration += duration

            if current_position is not None:
                if item.order < current_position:
                    elapsed_time += duration
                elif item.order == current_position and current_time_pos is not None:
                    elapsed_time += min(current_time_pos, duration)

        remaining_time = max(0, total_duration - elapsed_time)

        return {"total_duration": total_duration, "elapsed_time": elapsed_time, "remaining_time": remaining_time}

    @classmethod
    def enhance_mpv_playlist_item(cls, mpv_item: dict[str, Any], playlist: Playlist | None = None) -> dict[str, Any]:
        """Enhance an MPV playlist item with database metadata."""
        enhanced_item = dict(mpv_item)

        if playlist and enhanced_item.get("programme_position") is not None:
            try:
                programme_position = enhanced_item["programme_position"]
                db_item = playlist.items.get(order=programme_position)

                item_details = cls.build_playlist_item_details(db_item)

                enhanced_item.update(
                    {
                        "type": item_details["type"],
                        "duration": item_details["duration"],
                        "title": item_details["title"],
                        "details": {
                            "programme_block_id": item_details["programme_block_id"],
                            "content_id": item_details["content_id"],
                            "audio_track": item_details["audio_track"],
                            "subtitle_track": item_details["subtitle_track"],
                            "metadata": item_details["metadata"],
                        },
                    }
                )

            except Exception as e:
                logger.warning(f"Could not enhance playlist item {programme_position}: {e}")
                enhanced_item["duration"] = None
                enhanced_item["details"] = {}
        else:
            enhanced_item["duration"] = None
            enhanced_item["details"] = {}

        return enhanced_item
