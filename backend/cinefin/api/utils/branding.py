"""Web (navbar) branding logo helpers."""

import os
import re

from django.conf import settings

WEB_LOGO_SUBDIR = "branding_web"

ACCENT_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def web_logo_abs_path(stored_path: str | None) -> str | None:
    if not stored_path:
        return None
    if os.path.isabs(stored_path):
        return stored_path
    return os.path.join(settings.MEDIA_ROOT, stored_path)


def web_logo_url(stored_path: str | None) -> str | None:
    abs_path = web_logo_abs_path(stored_path)
    if not abs_path or not os.path.exists(abs_path):
        return None
    rel = os.path.relpath(abs_path, settings.MEDIA_ROOT)
    if rel.startswith(".."):
        return None  # outside MEDIA_ROOT — not web-servable
    return settings.MEDIA_URL + rel.replace(os.sep, "/")


def valid_accent_color(value: str | None) -> str | None:
    if isinstance(value, str) and ACCENT_COLOR_RE.match(value):
        return value.lower()
    return None
