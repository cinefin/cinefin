"""Ninja auth for the optional auth gate: the enforcement point for ``/api/v2/``.

Auth off (or fail-open): everything is allowed and no CSRF applies. Auth on: like Ninja's
``SessionAuth`` (a logged-in session, else 401, plus CSRF on unsafe methods, inherited from
``APIKeyCookie``), with read-only kiosk polls and API-key bearers let through without CSRF.
The same ``auth_is_active`` rule governs this and the middleware.
"""

from typing import Any

from ninja.security import APIKeyCookie

from cinefin.api.services.auth_service import api_key_user, auth_is_active, is_kiosk_public_request

# Any non-None value tells Ninja the request is authorised.
PUBLIC = "public"


class SessionAuthWhenEnabled(APIKeyCookie):
    """Session auth that only bites when ``security.auth_enabled`` is active."""

    openapi_name = "SessionAuth"

    def authenticate(self, request, key) -> Any | None:
        # A wall display can't log in, so its read-only kiosk poll is allowed.
        if not auth_is_active(request) or is_kiosk_public_request(request):
            return PUBLIC
        # An API key authorises as the single account (a bearer token isn't cookie-driven: no CSRF).
        key_user = api_key_user(request)
        if key_user is not None:
            return key_user
        # CSRF was already enforced in _get_key() for unsafe methods.
        return request.user if request.user.is_authenticated else None

    def _get_key(self, request):
        # Skip the inherited CSRF check where authenticate() lets the request through anyway.
        if not auth_is_active(request) or is_kiosk_public_request(request) or api_key_user(request) is not None:
            return None
        return super()._get_key(request)


session_auth = SessionAuthWhenEnabled()
