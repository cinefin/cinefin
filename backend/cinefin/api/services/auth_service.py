"""Optional single-user authentication for Cinefin.

Lockout-safe: enabling auth requires a password first, and ``auth_is_active`` fails
open (flag True but no usable User → behaves as disabled and warns, never bricks)."""

import logging
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError

from cinefin.api.models import Settings

logger = logging.getLogger(__name__)

DEFAULT_USERNAME = "admin"


def has_usable_account() -> bool:
    """Whether at least one active User with a usable password exists (the fail-open check)."""
    return any(u.has_usable_password() for u in get_user_model().objects.filter(is_active=True).only("password"))


def auth_is_active(_request=None) -> bool:
    """Single source of truth for the auth gate: True only when enabled AND a usable account exists."""
    if not bool(Settings.get("security.auth_enabled")):
        return False
    if not has_usable_account():
        # Fail open: a misconfiguration (flag set outside the proper flow) — warn loudly but stay usable.
        logger.warning(
            "security.auth_enabled is True but no usable account exists — "
            "treating auth as DISABLED so you are not locked out. Set a "
            "password in Settings → Security (or run "
            "`manage.py set_admin_password`) to actually enable it."
        )
        return False
    return True


# Read-only endpoints a public kiosk display may reach without a session (nothing state-changing).
KIOSK_PUBLIC_API_PATHS = (
    "/api/v2/schedules/list",
    "/api/v2/playout/status",
    "/api/v2/kiosk/display",
)


# Scoped to the read-only poster proxy so an unauthenticated wall display's posters don't 401.
KIOSK_PUBLIC_API_PATTERN = re.compile(r"^/api/v2/movies/\d+/poster/?$")


def is_kiosk_public_request(request) -> bool:
    """Whether ``request`` is a read-only kiosk poll exempt from the gate."""
    if request is None or getattr(request, "method", None) not in ("GET", "HEAD"):
        return False
    if not bool(Settings.get("security.kiosk_public")):
        return False
    path = getattr(request, "path", "")
    return path.startswith(KIOSK_PUBLIC_API_PATHS) or bool(KIOSK_PUBLIC_API_PATTERN.match(path))


def get_single_user():
    """Return the single account (first active User), or None if there is none."""
    return get_user_model().objects.filter(is_active=True).order_by("id").first()


def api_key_user(request):
    """Resolve a valid API key on ``request`` to the single account User, else None (memoised)."""
    if request is None:
        return None
    cached = getattr(request, "_cinefin_api_key_user", False)
    if cached is not False:
        return cached

    from cinefin.api.models import APIKey

    user = None
    header = request.META.get("HTTP_AUTHORIZATION", "") if hasattr(request, "META") else ""
    token = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else ""
    if token and APIKey.resolve(token) is not None:
        user = get_single_user()
    try:
        request._cinefin_api_key_user = user
    except (AttributeError, TypeError):
        pass  # unusual request object (tests) — just don't cache
    return user


def set_password(new_password: str, username: str | None = None):
    """Create or update the single (superuser) account. Any non-empty password; raises on empty."""
    User = get_user_model()
    password = (new_password or "").strip()
    if not password:
        raise DjangoValidationError("Password cannot be empty.")

    user = get_single_user()
    desired_username = (username or "").strip() or (user.username if user else DEFAULT_USERNAME)

    if user is None:
        return User.objects.create_superuser(username=desired_username, password=password)
    user.username = desired_username
    user.set_password(password)
    user.is_active = True
    user.save()
    return user


def enable_auth() -> None:
    """Turn the auth gate on. Refuses if no usable account exists (lockout-safe)."""
    if not has_usable_account():
        raise DjangoValidationError("Set an account password before enabling authentication.")
    Settings.set("security.auth_enabled", True)


def disable_auth() -> None:
    """Turn the auth gate off. Always allowed — this is the recovery direction."""
    Settings.set("security.auth_enabled", False)
