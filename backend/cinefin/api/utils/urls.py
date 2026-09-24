"""Resolving Cinefin's own base URL for building streamed-media links.

The base must be reachable by the remote playout host. Precedence: the
``playout.server_url`` application setting, else the ``CINEFIN_SERVER_URL``
Django setting/env.
"""


def cinefin_base_url() -> str:
    """Configured streaming base URL, without a trailing slash.

    A settings/DB lookup must never raise into URL building, so failures fall
    back to the Django setting.
    """
    from django.conf import settings as django_settings

    configured = ""
    try:
        from cinefin.api.models import Settings

        configured = (Settings.get("playout.server_url") or "").strip()
    except Exception:  # noqa: BLE001 — never let a settings lookup break URL building
        configured = ""
    base = configured or getattr(django_settings, "CINEFIN_SERVER_URL", "") or ""
    return base.rstrip("/")
