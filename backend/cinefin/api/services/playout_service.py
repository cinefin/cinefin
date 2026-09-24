"""Programme timing helpers and the "just played" marker (outside the MPV state machine)."""

import logging

from cinefin.api.models import Programme

logger = logging.getLogger(__name__)


def mark_programme_played(programme_id: int) -> None:
    """Record that a programme just started. Queryset update avoids races and doesn't bump updated_at."""
    from django.utils import timezone

    Programme.objects.filter(pk=programme_id).update(last_played_at=timezone.now())


class PlayoutService:
    @staticmethod
    def calculate_programme_timing(
        playlist, programme_position: int | None, current_playback_position: float
    ) -> dict[str, float]:
        programme_total_duration = 0.0
        programme_elapsed_time = 0.0
        programme_time_percentage = 0.0

        playlist_items = list(playlist.items.all().order_by("order"))

        for item in playlist_items:
            item_duration = 0.0

            if item.content_type == "movie":
                # Movies store runtime in minutes; other content types store duration in seconds
                movie = item.content_object.movie if hasattr(item.content_object, "movie") else item.content_object
                if movie and hasattr(movie, "runtime") and movie.runtime:
                    item_duration = float(movie.runtime) * 60
            else:
                if hasattr(item.content_object, "duration") and item.content_object.duration:
                    item_duration = float(item.content_object.duration)

            programme_total_duration += item_duration

            if programme_position is not None and item.order < programme_position:
                programme_elapsed_time += item_duration

        if programme_position is not None and programme_position >= 0:
            programme_elapsed_time += current_playback_position

        if programme_total_duration > 0:
            programme_time_percentage = round((programme_elapsed_time / programme_total_duration) * 100, 1)

        programme_remaining_time = max(0, programme_total_duration - programme_elapsed_time)

        return {
            "total_duration": programme_total_duration,
            "elapsed_time": programme_elapsed_time,
            "remaining_time": programme_remaining_time,
            "time_percentage": programme_time_percentage,
        }
