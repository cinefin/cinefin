"""Cinefin's own base URL (reachable by the playout host) for building streamed-media links."""


def cinefin_base_url() -> str:
    """``playout.server_url``, else the ``CINEFIN_SERVER_URL`` Django setting, without a trailing slash."""
    from django.conf import settings as django_settings

    try:
        from cinefin.api.models import Settings

        configured = (Settings.get("playout.server_url") or "").strip()
    except Exception:  # noqa: BLE001 — never let a settings lookup break URL building
        configured = ""
    base = configured or getattr(django_settings, "CINEFIN_SERVER_URL", "") or ""
    return base.rstrip("/")
