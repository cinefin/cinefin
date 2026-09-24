"""Streaming URL resolution for provider-backed movies (the Plex path opens a live connection)."""

import logging

logger = logging.getLogger(__name__)


def get_movie_stream_url(movie) -> dict:
    """Streaming URL for a movie: from the provider origin, else Django-served."""
    providers = {
        "plex": _get_plex_stream_url,
        "jellyfin": _get_jellyfin_stream_url,
    }
    provider = providers.get(movie.sync_source.sync_type) if movie.sync_source else None
    if provider is not None:
        result = provider(movie)
        if result.get("stream_url"):
            return result
        logger.info(
            "Provider stream URL unavailable for '%s' (%s); serving from Django",
            movie.title,
            result.get("error"),
        )
    return movie.get_stream_url()


def _get_jellyfin_stream_url(movie) -> dict:
    if not movie.jellyfin_item_id:
        return {"error": "No Jellyfin item ID", "file_path": movie.file_path}

    try:
        base_url = movie.sync_source.url.rstrip("/")
        token = movie.sync_source.token

        # static=true = no transcoding
        stream_url = f"{base_url}/Videos/{movie.jellyfin_item_id}/stream?static=true&api_key={token}"

        return {"stream_url": stream_url, "direct": True, "provider": "jellyfin"}
    except Exception as e:
        logger.exception(f"Jellyfin stream error for movie {movie.id}")
        return {"error": str(e), "file_path": movie.file_path}


def _get_plex_stream_url(movie) -> dict:
    """Get streaming URL from Plex server (opens a live PlexServer connection)."""
    if not movie.sync_source or movie.sync_source.sync_type != "plex":
        return {"error": "Not a Plex source", "file_path": movie.file_path}

    try:
        # Lazy import: plexapi is an optional heavy dependency.
        from plexapi.server import PlexServer

        plex = PlexServer(movie.sync_source.url, movie.sync_source.token)

        search_results = plex.library.search(guid=f"tmdb://{movie.tmdbid}")
        if not search_results:
            search_results = plex.library.search(title=movie.title, year=movie.year, libtype="movie")

        if not search_results:
            return {"error": "Movie not found in Plex library"}

        plex_movie = search_results[0]

        part = plex_movie.media[0].parts[0]
        stream_url = plex.url(part.key, includeToken=True)

        return {
            "stream_url": stream_url,
            "direct": True,
            "provider": "plex",
            "plex_metadata": {
                "rating_key": plex_movie.ratingKey,
                "duration": plex_movie.duration,
                "bitrate": plex_movie.media[0].bitrate if plex_movie.media else None,
                "container": plex_movie.media[0].container if plex_movie.media else None,
                "video_codec": plex_movie.media[0].videoCodec if plex_movie.media else None,
                "audio_codec": plex_movie.media[0].audioCodec if plex_movie.media else None,
            },
        }
    except Exception as e:
        logger.exception(f"Plex stream error for movie {movie.id}")
        return {"error": str(e), "file_path": movie.file_path}
