"""Streaming URL resolution for provider-backed movies (the Plex path opens a live connection)."""

import logging

logger = logging.getLogger(__name__)


def get_movie_stream_url(movie) -> dict:
    """Streaming URL for a movie: from the provider origin, else Django-served."""
    providers = {"plex": _get_plex_stream_url, "jellyfin": _get_jellyfin_stream_url}
    provider = providers.get(movie.sync_source.sync_type) if movie.sync_source else None
    if provider is not None:
        result = provider(movie)
        if result.get("stream_url"):
            return result
        logger.info(
            "Provider stream URL unavailable for '%s' (%s); serving from Django", movie.title, result.get("error")
        )
    return movie.get_stream_url()


def _get_jellyfin_stream_url(movie) -> dict:
    if not movie.jellyfin_item_id:
        return {"error": "No Jellyfin item ID", "file_path": movie.file_path}
    base_url = movie.sync_source.url.rstrip("/")
    # static=true = no transcoding
    stream_url = f"{base_url}/Videos/{movie.jellyfin_item_id}/stream?static=true&api_key={movie.sync_source.token}"
    return {"stream_url": stream_url, "direct": True, "provider": "jellyfin"}


def _get_plex_stream_url(movie) -> dict:
    try:
        from plexapi.server import PlexServer  # lazy: heavy import

        plex = PlexServer(movie.sync_source.url, movie.sync_source.token)
        results = plex.library.search(guid=f"tmdb://{movie.tmdbid}") or plex.library.search(
            title=movie.title, year=movie.year, libtype="movie"
        )
        if not results:
            return {"error": "Movie not found in Plex library"}

        plex_movie = results[0]
        media = plex_movie.media[0]
        return {
            "stream_url": plex.url(media.parts[0].key, includeToken=True),
            "direct": True,
            "provider": "plex",
            "plex_metadata": {
                "rating_key": plex_movie.ratingKey,
                "duration": plex_movie.duration,
                "bitrate": media.bitrate,
                "container": media.container,
                "video_codec": media.videoCodec,
                "audio_codec": media.audioCodec,
            },
        }
    except Exception as e:
        logger.exception(f"Plex stream error for movie {movie.id}")
        return {"error": str(e), "file_path": movie.file_path}
