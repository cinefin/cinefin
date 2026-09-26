"""Shared Jellyfin helpers used by the sync plugin, poster fetch and installer probe."""


def auth_header(token: str) -> str:
    """The ``Authorization`` value for Jellyfin's ``MediaBrowser`` scheme.

    Jellyfin 10.9+ (and 12.x) reject the legacy ``X-Emby-Token`` header with a 401,
    so the token rides the standard ``Authorization`` header everywhere we talk to
    Jellyfin. This form is accepted across supported versions."""
    return f'MediaBrowser Client="Cinefin", Device="Cinefin", DeviceId="cinefin", Version="1.0", Token="{token}"'
