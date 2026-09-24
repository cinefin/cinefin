"""
Middleware to redirect unconfigured systems to the setup wizard.

Until the first-run setup is finished (the `setup.completed` application
setting is True) every request is redirected to the SPA's setup wizard at
/app/setup, except static files, the SPA's built assets (which the wizard
itself boots from), API endpoints, the admin, and the wizard page itself.
"""

from django.shortcuts import redirect

from cinefin.api.models import Settings

SETUP_PATH = "/app/setup"


class InstallerRedirectMiddleware:
    """
    Middleware that redirects to the setup wizard if the system is not configured.
    """

    # Paths that should not trigger a redirect
    EXCLUDED_PATHS = [
        SETUP_PATH,  # the setup wizard itself (served by spa_view's fallback)
        "/app/_app/",  # the SPA's built JS/CSS — the wizard boots from these
        "/api/",
        "/static/",
        "/media/",
        "/admin/",
        # Navbar chrome (update-check JSON) is fetched on every page, including
        # the wizard itself — never bounce it back to setup.
        "/system/",
    ]

    def __init__(self, get_response):
        self.get_response = get_response
        self._is_configured = False

    def __call__(self, request):
        # Check if we need to redirect to the setup wizard
        if self._should_redirect_to_installer(request):
            return redirect(SETUP_PATH)

        response = self.get_response(request)
        return response

    def _should_redirect_to_installer(self, request):
        """
        Determine if the request should be redirected to the setup wizard.
        """
        # Don't redirect if already on the wizard or excluded paths
        if self._is_excluded_path(request.path):
            return False

        # Check if system is configured (cache the result for performance)
        if not self._is_system_configured():
            return True

        return False

    def _is_excluded_path(self, path):
        """
        Check if the path should be excluded from redirection.
        """
        for excluded in self.EXCLUDED_PATHS:
            if path.startswith(excluded):
                return True
        return False

    def _is_system_configured(self):
        """
        Whether first-run setup has been completed.

        Only the True result is cached (setup never un-completes), so a freshly
        finished install is recognised on the very next request — no redirect
        loop — while an unconfigured system just does one cheap singleton read
        per request.
        """
        if self._is_configured:
            return True
        self._is_configured = bool(Settings.get("setup.completed"))
        return self._is_configured
