"""
The optional authentication gate (issue #124).

When ``security.auth_enabled`` is on AND a usable account exists
(``auth_service.auth_is_active``), every request must come from a logged-in
session — otherwise:

* a **page** request is redirected to ``/login/?next=<path>``;
* an **API** request (``/api/``) gets a JSON 401 in the standard error
  envelope (never a redirect — an XHR can't follow one usefully).

When auth is off (the default, and the fail-open state) this middleware is a
pass-through and the app behaves exactly as it did before this feature.

Modelled on ``InstallerRedirectMiddleware`` — same "exempt a handful of path
prefixes, otherwise gate" shape. It sits AFTER that middleware in the chain so
an unconfigured box is sent to the installer before auth is ever considered
(and the installer flow is exempt here too, belt and braces).

Always-exempt (so you can never brick yourself), even when the gate is on:

* ``/login`` / ``/logout`` — otherwise you couldn't log in.
* static assets (``/static/``, ``STATIC_URL``).
* the installer flow (``/installer``, ``/api/v2/installer/``) — a fresh box
  must reach setup before it can create an account.
* the navbar update-check reads (``/system/``) — harmless, public, polled on
  every page including the login screen.
* the cinema web logo (``/media/branding_web/``) — the login screen shows it,
  so it must load before you're authenticated. Only this one branding subdir
  is exempt; the rest of ``/media/`` (thumbnails, uploads) stays gated.
* the ``/stream/`` media endpoints — MPV fetches playlist items over plain
  HTTP with no session, so the stream views enforce their own signed ``?t=``
  token (put on the URL by ``get_stream_url()``) instead of the session gate.
* the Ninja API's own auth (a ``SessionAuth``) is the real enforcement point
  for ``/api/`` — this middleware's API branch is a defensive backstop that
  guarantees a 401 even for the plain SSE views and anything Ninja might let
  through.

Kiosk exemption (``security.kiosk_public``, default on): a wall display can't
log in, so the SPA kiosk (``/app/kiosk`` plus the built ``/app/_app/`` assets
it boots from, plus the old ``/kiosk/`` path that redirects there) and the
small read-only allow-list it reads (the ``GET /api/v2/schedules/list`` /
``/api/v2/playout/status`` / ``/api/v2/kiosk/display`` polls and the
poster-thumbnail media subdir — see ``auth_service.is_kiosk_public_request``)
are exempt when that toggle is set. Nothing state-changing is exempted.
"""

import logging

from django.conf import settings as django_settings
from django.http import JsonResponse
from django.shortcuts import redirect

from cinefin.api.services.auth_service import api_key_user, auth_is_active, is_kiosk_public_request

logger = logging.getLogger(__name__)


class AuthGateMiddleware:
    """Enforce ``security.auth_enabled`` on pages and the API."""

    # Prefixes exempt regardless of auth state. STATIC_URL is added at init.
    EXEMPT_PREFIXES = (
        "/login",
        "/logout",
        "/static/",
        "/installer",  # the old wizard path (redirects to /app/setup)
        "/api/v2/installer/",  # installer API used by the setup wizard
        "/system/",  # navbar update-check (public, harmless)
        "/favicon.ico",
        # Media streams: MPV fetches these with no session, so the views
        # enforce their own signed ?t= token instead (views._stream_authorized
        # / api.utils.stream_token). Exempt here so the request reaches them.
        "/stream/",
    )

    # The kiosk PAGE prefixes (their read-only API polls are shared with the
    # Ninja auth via auth_service.is_kiosk_public_request). Exempt ONLY when
    # security.kiosk_public is set. /app/kiosk is the SPA kiosk (served by
    # spa_view's index.html fallback); /app/_app/ is the SPA's built,
    # content-hashed JS/CSS — the SPA equivalent of the always-exempt
    # /static/ tree, opened here only for the kiosk toggle so an
    # unauthenticated wall display can actually boot the page it was allowed
    # to load. The rest of /app/ stays gated. The bare /kiosk prefix keeps
    # the old-URL redirect hop (and any wall unit bookmarked on it) exempt.
    KIOSK_PREFIXES = ("/kiosk", "/app/kiosk", "/app/_app/")

    def __init__(self, get_response):
        self.get_response = get_response
        static_url = getattr(django_settings, "STATIC_URL", "/static/") or "/static/"
        # The cinema web logo is shown on the (unauthenticated) login screen, so
        # its media subdir must load without a session. Nothing else under
        # /media/ is exempted.
        from cinefin.api.utils.branding import WEB_LOGO_SUBDIR

        media_url = getattr(django_settings, "MEDIA_URL", "/media/") or "/media/"
        logo_prefix = f"{media_url.rstrip('/')}/{WEB_LOGO_SUBDIR}/"
        self._exempt = tuple(dict.fromkeys((*self.EXEMPT_PREFIXES, static_url, logo_prefix)))

    def __call__(self, request):
        if self._should_block(request):
            return self._blocked_response(request)
        return self.get_response(request)

    def _should_block(self, request) -> bool:
        if not auth_is_active(request):
            return False
        if getattr(request, "user", None) is not None and request.user.is_authenticated:
            return False
        if self._is_exempt(request):
            return False
        # A valid API key (Authorization: Bearer) authorises the request the
        # same way a session would — resolved once and shared with the Ninja
        # auth. Only API paths carry keys, but the check is cheap (no header →
        # no query) so it's safe to run for any request.
        if api_key_user(request) is not None:
            return False
        return True

    def _is_exempt(self, request) -> bool:
        path = request.path
        # The /system/ read is public, but the update-check *toggle* changes
        # state (display.update_check) — keep it gated even though it shares
        # the public prefix.
        if path.startswith("/system/update-check/toggle"):
            return False
        if path.startswith(self._exempt):
            return True
        # Kiosk page + its read-only API polls, when kiosk_public is on.
        if self._kiosk_public() and path.startswith(self.KIOSK_PREFIXES):
            return True
        if is_kiosk_public_request(request):
            return True
        return False

    @staticmethod
    def _kiosk_public() -> bool:
        from cinefin.api.models import Settings

        return bool(Settings.get("security.kiosk_public"))

    @staticmethod
    def _blocked_response(request):
        # API → JSON 401 (envelope-consistent with ninja_api's handlers).
        if request.path.startswith("/api/"):
            return JsonResponse(
                {
                    "success": False,
                    "error": "Authentication required",
                    "error_code": "AUTHENTICATION_REQUIRED",
                    "details": None,
                },
                status=401,
            )
        # Pages → redirect to the login form, preserving where they were going.
        return redirect(f"/login/?next={request.get_full_path()}")
