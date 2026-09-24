"""Live poster art fetched from the media server on demand; nothing is written to disk."""

from __future__ import annotations

import logging
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

POSTER_WIDTH = 400
POSTER_HEIGHT = 600

FETCH_TIMEOUT = 10


def poster_request(movie) -> tuple[str, dict] | None:
    """The ``(url, headers)`` a provider poster is fetched with, or None."""
    if not movie.poster_key or not movie.sync_source:
        return None
    builder = {"plex": _plex_request, "jellyfin": _jellyfin_request}.get(movie.sync_source.sync_type)
    return builder(movie) if builder else None


def fetch_poster(movie) -> bytes | None:
    """The movie's poster bytes from its media server, or None. Never raises."""
    request = poster_request(movie)
    if request is None:
        return None
    url, headers = request
    try:
        response = requests.get(url, headers=headers, timeout=FETCH_TIMEOUT)
    except requests.RequestException as e:
        logger.info("Poster fetch failed for '%s': %s", movie.title, e)
        return None
    if response.status_code != 200 or not response.content:
        logger.info("Poster fetch for '%s' returned HTTP %s", movie.title, response.status_code)
        return None
    return response.content


def _plex_request(movie) -> tuple[str, dict]:
    # Route through /photo/:/transcode for a right-sized poster; upscale=0 keeps small sources as-is.
    base = movie.sync_source.url.rstrip("/")
    token = movie.sync_source.token
    inner = quote(movie.poster_key, safe="")
    url = (
        f"{base}/photo/:/transcode"
        f"?width={POSTER_WIDTH}&height={POSTER_HEIGHT}&minSize=1&upscale=0"
        f"&url={inner}&X-Plex-Token={quote(token, safe='')}"
    )
    return url, {}


def _jellyfin_request(movie) -> tuple[str, dict]:
    # poster_key is the Primary image tag (a content hash): pins the version and lets Jellyfin cache.
    base = movie.sync_source.url.rstrip("/")
    url = (
        f"{base}/Items/{movie.jellyfin_item_id}/Images/Primary"
        f"?maxWidth={POSTER_WIDTH}&tag={quote(movie.poster_key, safe='')}"
    )
    return url, {"X-Emby-Token": movie.sync_source.token}
