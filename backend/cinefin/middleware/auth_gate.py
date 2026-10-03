"""The optional authentication gate.

When ``auth_service.auth_is_active`` (``security.auth_enabled`` on and a usable account), every
request needs a logged-in session or an API key: a page is redirected to ``/login/?next=<path>``,
an API call gets a JSON 401 in the standard error envelope. Off (the default and the fail-open
state) it passes everything through. It sits after InstallerRedirectMiddleware, so an
unconfigured box reaches setup first.

Always exempt, so you can never lock yourself out: login/logout, static assets, the installer
flow, the web logo (shown on the login screen) and
``/stream/`` (mpv fetches with no session; the stream views check their own signed ``?t=``
token). For ``/api/`` the Ninja auth is the real enforcement point; this is a backstop.

With ``security.kiosk_public`` on, the kiosk pages and the read-only polls they make
(``auth_service.is_kiosk_public_request``) are exempt too. Nothing state-changing is.
"""

from django.conf import settings as django_settings
from django.http import JsonResponse
from django.shortcuts import redirect

from cinefin.api.services.auth_service import api_key_user, auth_is_active, is_kiosk_public_request


class AuthGateMiddleware:
    # STATIC_URL and the web-logo media subdir are added at init.
    EXEMPT_PREFIXES = (
        "/login",
        "/logout",
        "/static/",
        "/installer",  # the old wizard path (redirects to /app/setup)
        "/api/v2/installer/",
        "/favicon.ico",
        "/stream/",
    )

    # Exempt only when security.kiosk_public is set: the SPA kiosk, the SPA's built assets it
    # boots from (the rest of /app/ stays gated), and the old /kiosk/ redirect hop.
    KIOSK_PREFIXES = ("/kiosk", "/app/kiosk", "/app/_app/")

    def __init__(self, get_response):
        from cinefin.api.utils.branding import WEB_LOGO_SUBDIR

        self.get_response = get_response
        static_url = getattr(django_settings, "STATIC_URL", "/static/") or "/static/"
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
        return not self._is_exempt(request) and api_key_user(request) is None

    def _is_exempt(self, request) -> bool:
        path = request.path
        if path.startswith(self._exempt):
            return True
        if self._kiosk_public() and path.startswith(self.KIOSK_PREFIXES):
            return True
        return is_kiosk_public_request(request)

    @staticmethod
    def _kiosk_public() -> bool:
        from cinefin.api.models import Settings

        return bool(Settings.get("security.kiosk_public"))

    @staticmethod
    def _blocked_response(request):
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
        return redirect(f"/login/?next={request.get_full_path()}")
