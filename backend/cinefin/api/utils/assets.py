"""Paths to bundled app assets (cinefin/assets/, settings.CINEFIN_ASSETS_DIR)."""

import os

from django.conf import settings


def asset_path(*parts: str) -> str:
    return os.path.join(settings.CINEFIN_ASSETS_DIR, *parts)


def system_black_path() -> str:
    return asset_path("system", "black.mp4")


def system_black_stream_url() -> str:
    from cinefin.api.utils.stream_token import make_stream_token
    from cinefin.api.utils.urls import cinefin_base_url

    return f"{cinefin_base_url()}/stream/system/black/?t={make_stream_token('system', 0)}"


def system_ident_path() -> str:
    return asset_path("system", "ident.mp4")


def system_ident_stream_url() -> str:
    from cinefin.api.utils.stream_token import make_stream_token
    from cinefin.api.utils.urls import cinefin_base_url

    return f"{cinefin_base_url()}/stream/system/ident/?t={make_stream_token('system', 1)}"


def rating_card_path(ratings_system: str, certification: str) -> str | None:
    """Background image for a certification card, or None. Resolution: user
    MEDIA_ROOT/ratings/<system>/<cert>.jpg, legacy flat, then bundled."""
    for candidate in (
        os.path.join(settings.MEDIA_ROOT, "ratings", ratings_system, f"{certification}.jpg"),
        os.path.join(settings.MEDIA_ROOT, "ratings", f"{certification}.jpg"),
        asset_path("ratings", ratings_system, f"{certification}.jpg"),
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def rating_card_video_path(ratings_system: str, certification: str) -> str | None:
    """User-supplied static certification video, or None: used directly, no per-film generation."""
    path = os.path.join(settings.MEDIA_ROOT, "ratings", ratings_system, f"{certification}.mp4")
    return path if os.path.exists(path) else None


def branding_path(name: str) -> str:
    return asset_path("branding", name)
