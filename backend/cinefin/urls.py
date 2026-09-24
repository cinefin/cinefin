"""
URL configuration for cinefin project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve as static_serve

from cinefin import views

urlpatterns = [
    # Authentication (optional auth gate — issue #124). Custom styled views,
    # not django.contrib.auth.urls (which needs registration/* templates we
    # don't ship and would 500 on password-reset routes).
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    # API URLs (Django Ninja v2 API plus the SSE views)
    path("api/v2/", include("cinefin.api.urls_v2")),
    # The SvelteKit SPA (frontend/build) — THE UI. /app/ and every /app/<path>
    # that isn't a build asset falls back to index.html (client-side routing).
    # The bare root sends you there.
    re_path(r"^app(?:/(?P<path>.*))?$", views.spa_view, name="spa"),
    path("", RedirectView.as_view(url="/app/"), name="home"),
    # Update check (plain JSON, not Ninja). Consumed by the SPA's System/About
    # page (routes/system/+page.svelte); the /toggle sibling has no consumer.
    path("system/update-check", views.update_check_view, name="update_check"),
    path("system/update-check/toggle", views.update_check_toggle_view, name="update_check_toggle"),
    # Streaming endpoints for local content
    path("stream/trailer/<int:trailer_id>/", views.stream_trailer, name="stream_trailer"),
    path("stream/bumper/<int:bumper_id>/", views.stream_bumper, name="stream_bumper"),
    path("stream/certification/<int:certification_id>/", views.stream_certification, name="stream_certification"),
    path("stream/title/<int:programme_id>/", views.stream_title, name="stream_title"),
    path("stream/movie/<int:movie_id>/", views.stream_movie, name="stream_movie"),
    path("stream/system/black/", views.stream_system_black, name="stream_system_black"),
    path("stream/system/ident/", views.stream_system_ident, name="stream_system_ident"),
]

# Compatibility redirects: the deleted legacy UI's top-level page paths bounce
# to their SPA equivalents, so bookmarks, wall-mounted kiosk URLs and printed
# QR links keep working. Query strings ride along (the kiosk's ?layout=… etc.;
# fragments survive client-side). Deliberately 302, not 301: nothing should
# cache them permanently. The old about/health pages both land on the SPA's
# System page (version + health checks).
_SPA_REDIRECTS = {
    "library/": "/app/library",
    "remote/": "/app/remote",
    "trailers/": "/app/trailers",
    "settings/": "/app/settings",
    "kiosk/": "/app/kiosk",  # stays auth-exempt via AuthGateMiddleware.KIOSK_PREFIXES
    "media/": "/app/media",
    "programmes/": "/app/programmes",
    "create-programme/": "/app/programmes/create",
    "programme-editor/": "/app/programmes",  # the SPA editor is per-programme (/app/programmes/edit/<id>)
    "template-editor/": "/app/templates",
    "title-template-editor/": "/app/titles",
    "schedules/": "/app/schedules",
    "commands/": "/app/commands",
    "about/": "/app/system",
    "health/": "/app/system",
    # The library source is Settings now — a library takes ONE server, which is
    # configuration rather than something managed from the film grid.
    "sync/": "/app/settings?tab=library",
    # The setup wizard moved into the SPA; the old server-rendered page's path
    # keeps working for bookmarks and the resume-after-close flow.
    "installer/": "/app/setup",
}
urlpatterns += [path(p, RedirectView.as_view(url=target, query_string=True)) for p, target in _SPA_REDIRECTS.items()]
urlpatterns += [
    path(
        "programme/<int:programme_id>/",
        RedirectView.as_view(url="/app/programmes/%(programme_id)s", query_string=True),
    ),
]

# Serve media (screenshots, generated title/cert videos, uploads) in ALL
# modes, not just DEBUG: this is a single-user LAN app with no reverse proxy or
# separate file server in front, so Django itself must serve MEDIA_ROOT. The
# Django docs call django.views.static.serve inefficient/unhardened for
# production; that trade-off is acceptable here. `.+` (not `.*`) so the bare
# /media/ path still hits its compatibility redirect above.
urlpatterns += [
    re_path(r"^media/(?P<path>.+)$", static_serve, {"document_root": settings.MEDIA_ROOT}),
]

# Django admin: a development spelunking tool, not part of the product — the
# app UI and API cover everything users need. Only mounted with DEBUG on, so
# production never exposes a second login surface.
if settings.DEBUG:
    urlpatterns += [path("admin/", admin.site.urls)]

# Custom error pages. These point at Django's built-in handlers, which render
# templates/404.html and templates/500.html — 500.html is rendered with an
# empty context (no context processors, no DB), so it must stay self-contained.
# Only used when DEBUG is off; with DEBUG on Django serves its own debug pages.
handler404 = "django.views.defaults.page_not_found"
handler500 = "django.views.defaults.server_error"
