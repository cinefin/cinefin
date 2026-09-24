"""
Ninja auth for the optional auth gate (issue #124).

This is the real enforcement point for ``/api/v2/``. Attached as the global
``auth=`` on the ``NinjaAPI``, it runs for every operation and decides, per the
``security.auth_enabled`` setting:

* **Auth off** (default / fail-open): return a truthy public sentinel so every
  endpoint stays open and NO CSRF check is applied. The API behaves exactly as
  it did before this feature — which is what keeps the existing test suite green
  and existing installs working after an upgrade.

* **Auth on**: behave like Ninja's ``SessionAuth`` — require a logged-in
  session (else return ``None`` → Ninja answers 401) AND enforce CSRF on unsafe
  methods. We subclass ``APIKeyCookie`` specifically to inherit that CSRF
  machinery (``check_csrf`` runs in ``_get_key`` for cookie auth), so a
  logged-in session cannot be driven cross-site.

Why here and not only in middleware: the middleware already 401s unauthenticated
API calls, but Ninja's own auth is where CSRF protection is wired for the JSON
API, and keeping the decision in one callable means the *same* ``auth_is_active``
rule (incl. fail-open) governs both.
"""

from typing import Any

from ninja.security import APIKeyCookie

from cinefin.api.services.auth_service import api_key_user, auth_is_active, is_kiosk_public_request

# Returned when auth is off, so Ninja treats the request as authorised. Any
# non-None value satisfies Ninja; a stable sentinel is clearer than True.
PUBLIC = "public"


class SessionAuthWhenEnabled(APIKeyCookie):
    """Session auth that only bites when ``security.auth_enabled`` is active.

    Inherits the cookie-auth CSRF check from ``APIKeyCookie`` (enforced on
    unsafe methods when a session is present and auth is on).
    """

    # Marked optional in the OpenAPI schema so the interactive docs don't imply
    # a hard requirement when auth is off.
    openapi_name = "SessionAuth"

    def authenticate(self, request, key) -> Any | None:
        # Auth off / fail-open: everything is allowed, no CSRF.
        if not auth_is_active(request):
            return PUBLIC
        # Read-only kiosk poll (a wall display can't log in): allowed, no CSRF.
        if is_kiosk_public_request(request):
            return PUBLIC
        # Stateless API key (external clients): authorises as the single
        # account. No session, no CSRF — a bearer token isn't cookie-driven.
        key_user = api_key_user(request)
        if key_user is not None:
            return key_user
        # Auth on: a real logged-in session is required. CSRF was already
        # enforced in _get_key() for unsafe methods (inherited behaviour).
        if request.user.is_authenticated:
            return request.user
        return None

    def _get_key(self, request):
        # Skip the inherited CSRF check while auth is off, for the read-only
        # kiosk polls, or for a valid API-key request — otherwise token-less /
        # bearer clients would break the moment this auth is attached even when
        # the feature is effectively off for them.
        if not auth_is_active(request) or is_kiosk_public_request(request):
            return None
        if api_key_user(request) is not None:
            return None
        return super()._get_key(request)


session_auth = SessionAuthWhenEnabled()
