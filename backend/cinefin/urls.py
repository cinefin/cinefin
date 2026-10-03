"""Cinefin URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import RedirectView
from django.views.static import serve as static_serve

from cinefin import views

urlpatterns = [
    # Custom styled views, not django.contrib.auth.urls (which needs registration/*
    # templates we don't ship and would 500 on password-reset routes).
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("api/v2/", include("cinefin.api.urls_v2")),
    # The SPA: every /app/<path> that isn't a build asset falls back to index.html.
    re_path(r"^app(?:/(?P<path>.*))?$", views.spa_view, name="spa"),
    path("", RedirectView.as_view(url="/app/"), name="home"),
    *[
        path(f"stream/{kind}/<int:pk>/", views.stream_media, {"kind": kind}, name=f"stream_{kind}")
        for kind in ("trailer", "bumper", "certification", "title", "movie")
    ],
    path("stream/system/black/", views.stream_media, {"kind": "system", "pk": 0}, name="stream_system_black"),
    path("stream/system/ident/", views.stream_media, {"kind": "system", "pk": 1}, name="stream_system_ident"),
]

# The deleted legacy UI's page paths bounce to their SPA equivalents, so bookmarks,
# wall-mounted kiosk URLs and printed QR links keep working. 302, not 301: nothing
# should cache them permanently.
_SPA_REDIRECTS = {
    "library/": "/app/library",
    "remote/": "/app/remote",
    "trailers/": "/app/trailers",
    "settings/": "/app/settings",
    "kiosk/": "/app/kiosk",  # stays auth-exempt via AuthGateMiddleware.KIOSK_PREFIXES
    "media/": "/app/media",
    "programmes/": "/app/programmes",
    "create-programme/": "/app/programmes/create",
    "programme-editor/": "/app/programmes",
    "template-editor/": "/app/templates",
    "title-template-editor/": "/app/titles",
    "schedules/": "/app/schedules",
    "commands/": "/app/commands",
    "about/": "/app/",
    "health/": "/app/",
    "sync/": "/app/settings?tab=library",
    "installer/": "/app/setup",
}
urlpatterns += [path(p, RedirectView.as_view(url=target, query_string=True)) for p, target in _SPA_REDIRECTS.items()]
urlpatterns += [
    path(
        "programme/<int:programme_id>/",
        RedirectView.as_view(url="/app/programmes/%(programme_id)s", query_string=True),
    ),
    # Django serves MEDIA_ROOT in every mode: a single-box LAN app has no separate
    # file server. `.+` so the bare /media/ path still hits its redirect above.
    re_path(r"^media/(?P<path>.+)$", static_serve, {"document_root": settings.MEDIA_ROOT}),
]

# Django admin is a development tool, mounted only with DEBUG on.
if settings.DEBUG:
    urlpatterns += [path("admin/", admin.site.urls)]

# Django's handlers render templates/404.html and 500.html (500 with an empty
# context, so it must stay self-contained).
handler404 = "django.views.defaults.page_not_found"
handler500 = "django.views.defaults.server_error"
