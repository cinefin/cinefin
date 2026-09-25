"""
Django Ninja API Configuration for Cinefin V2 APIs
"""

from ninja import NinjaAPI

from cinefin.version import get_channel, get_commit, get_version

from .ninja_auth import session_auth
from .ninja_views.backup_ninja import backup_api
from .ninja_views.command_ninja import command_api
from .ninja_views.docs_ninja import docs_api
from .ninja_views.installer_ninja import installer_api
from .ninja_views.kiosk_ninja import kiosk_api
from .ninja_views.logs_ninja import logs_api
from .ninja_views.media import media_api
from .ninja_views.movies_ninja import movies_api
from .ninja_views.mpv_ninja import mpv_api
from .ninja_views.playout_ninja import playout_api
from .ninja_views.programmes import programme_api
from .ninja_views.rating_cards_ninja import rating_cards_api
from .ninja_views.schedules_ninja import schedules_api
from .ninja_views.security_ninja import security_api
from .ninja_views.settings_ninja import settings_api
from .ninja_views.sync_ninja import sync_api
from .ninja_views.system_ninja import system_api
from .ninja_views.template_ninja import template_api
from .ninja_views.ticket_ninja import ticket_api
from .ninja_views.titlegen_ninja import titlegen_api
from .ninja_views.trailer_ninja import trailer_api

# Create the main API instance.
#
# `auth=session_auth` is the API's enforcement point for the optional auth gate
# (issue #124): when `security.auth_enabled` is off it lets everything through
# (and applies no CSRF), so the API is unchanged; when on it requires a
# logged-in session (else 401) and enforces CSRF on unsafe methods. See
# cinefin/api/ninja_auth.py.
api = NinjaAPI(
    title="Cinefin V2 API",
    version="2.0.0",
    description="Modern cinema automation API built with Django Ninja",
    docs_url="/ninja-docs/",
    openapi_url="/ninja-openapi.json",
    urls_namespace="api-2.0.0",
    auth=session_auth,
)

# Mount sub-APIs
api.add_router("/installer", installer_api, tags=["Installer"])
api.add_router("/settings", settings_api, tags=["Settings"])
api.add_router("/rating-cards", rating_cards_api, tags=["Rating cards"])
api.add_router("/security", security_api, tags=["Security"])
api.add_router("/movies", movies_api, tags=["Movies"])
api.add_router("/commands", command_api, tags=["Commands"])
api.add_router("/templates", template_api, tags=["Templates"])
api.add_router("/programmes", programme_api, tags=["Programmes"])
api.add_router("/media", media_api, tags=["Media"])
api.add_router("/kiosk", kiosk_api, tags=["Kiosk"])
api.add_router("/playout", playout_api, tags=["Playout"])
api.add_router("/schedules", schedules_api, tags=["Schedules"])
api.add_router("/sync", sync_api, tags=["Sync"])
api.add_router("/mpv", mpv_api, tags=["MPV Control"])
api.add_router("/trailers", trailer_api, tags=["Trailers"])
api.add_router("/tickets", ticket_api, tags=["Tickets"])
api.add_router("/titlegen", titlegen_api, tags=["Title Generation"])
api.add_router("/docs", docs_api, tags=["Documentation"])
api.add_router("/logs", logs_api, tags=["Logs"])
api.add_router("/backup", backup_api, tags=["Backup"])
api.add_router("/system", system_api, tags=["System"])


# Health check endpoint
@api.get("/health")
def health_check(request):
    """
    Health check endpoint to verify API is running.
    """
    return {
        "status": "healthy",
        "api": "cinefin-v2",
        "framework": "django-ninja",
        "version": get_version(),
    }


# Version endpoint
@api.get("/version")
def version(request):
    """Return the running application version, channel and commit."""
    return {"version": get_version(), "channel": get_channel(), "commit": get_commit()}


# Global exception handling. Endpoints simply raise NotFoundError /
# ValidationError / etc. (or let unexpected exceptions propagate) and get a
# consistent error envelope with the right HTTP status. Ninja dispatches the
# most-specific registered handler by walking the exception's MRO, so the
# APIException handler always wins over the generic Exception one, and Ninja's
# own default handlers for Http404 / ninja.errors.ValidationError / HttpError
# remain in place (they are more specific than Exception).
import logging  # noqa: E402

from ninja.errors import AuthenticationError  # noqa: E402

from .exceptions import APIException  # noqa: E402 — must import after `api` is created to avoid a circular import

logger = logging.getLogger(__name__)


@api.exception_handler(AuthenticationError)
def handle_authentication_error(request, exc: AuthenticationError):
    """Auth gate: an unauthenticated API call gets our 401 envelope, not Ninja's
    default ``{"detail": "Unauthorized"}`` (issue #124)."""
    return api.create_response(
        request,
        {
            "success": False,
            "error": "Authentication required",
            "error_code": "AUTHENTICATION_REQUIRED",
            "details": None,
        },
        status=401,
    )


@api.exception_handler(APIException)
def handle_api_exception(request, exc: APIException):
    if exc.status_code >= 500:
        logger.error(f"API error: {exc.error_code} - {exc.message}", exc_info=True)
    else:
        logger.warning(f"API error: {exc.error_code} - {exc.message}")

    return api.create_response(
        request,
        {
            "success": False,
            "error": exc.message,
            "error_code": exc.error_code,
            "details": exc.details,
        },
        status=exc.status_code,
    )


@api.exception_handler(Exception)
def handle_unexpected_exception(request, exc: Exception):
    logger.exception("Unhandled exception in API endpoint")

    return api.create_response(
        request,
        {
            "success": False,
            "error": "An unexpected error occurred",
            "error_code": "INTERNAL_ERROR",
            "details": {"exception": str(exc)} if logger.isEnabledFor(logging.DEBUG) else None,
        },
        status=500,
    )
