"""Redirect every page to the SPA's setup wizard (/app/setup) until first-run setup completes."""

from django.shortcuts import redirect

from cinefin.api.models import Settings

SETUP_PATH = "/app/setup"


class InstallerRedirectMiddleware:
    EXCLUDED_PATHS = (
        SETUP_PATH,
        "/app/_app/",  # the SPA's built JS/CSS, which the wizard boots from
        "/api/",
        "/static/",
        "/media/",
        "/admin/",
    )

    def __init__(self, get_response):
        self.get_response = get_response
        # Only True is cached (setup never un-completes), so a just-finished install
        # is recognised on the next request.
        self._is_configured = False

    def __call__(self, request):
        if not request.path.startswith(self.EXCLUDED_PATHS) and not self._is_system_configured():
            return redirect(SETUP_PATH)
        return self.get_response(request)

    def _is_system_configured(self):
        if not self._is_configured:
            self._is_configured = bool(Settings.get("setup.completed"))
        return self._is_configured
