"""Paths to bundled app assets (cinefin/assets/, settings.CINEFIN_ASSETS_DIR)."""

import os

from django.conf import settings


def asset_path(*parts: str) -> str:
    return os.path.join(settings.CINEFIN_ASSETS_DIR, *parts)


def system_black_path() -> str:
    return asset_path("system", "black.mp4")


def _system_stream_url(name: str, token_id: int) -> str:
    from cinefin.api.utils.stream_token import make_stream_token
    from cinefin.api.utils.urls import cinefin_base_url

    return f"{cinefin_base_url()}/stream/system/{name}/?t={make_stream_token('system', token_id)}"


def system_black_stream_url() -> str:
    return _system_stream_url("black", 0)


# The System Ident is a 4 s intro then a seamless 30 s loop, which a player holds by looping this range (mpv
# ab-loop-a / ab-loop-b), in seconds. Rendered by frontend/tools/system-ident/, whose page uses the same numbers.
SYSTEM_IDENT_LOOP = (4.0, 34.0)


def system_ident_path() -> str:
    return asset_path("system", "ident.mp4")


def system_ident_stream_url() -> str:
    return _system_stream_url("ident", 1)


def rating_card_path(ratings_system: str, certification: str) -> str | None:
    """Background image for a certification card, or None: the user's MEDIA_ROOT/ratings/<system>/<cert>.jpg,
    the legacy flat MEDIA_ROOT/ratings/<cert>.jpg, then the bundled one."""
    candidates = (
        os.path.join(settings.MEDIA_ROOT, "ratings", ratings_system, f"{certification}.jpg"),
        os.path.join(settings.MEDIA_ROOT, "ratings", f"{certification}.jpg"),
        asset_path("ratings", ratings_system, f"{certification}.jpg"),
    )
    return next((c for c in candidates if os.path.exists(c)), None)


def rating_card_video_path(ratings_system: str, certification: str) -> str | None:
    """User-supplied static certification video, or None: used directly, no per-film generation."""
    path = os.path.join(settings.MEDIA_ROOT, "ratings", ratings_system, f"{certification}.mp4")
    return path if os.path.exists(path) else None
