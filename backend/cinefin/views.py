"""Non-API views: media streaming, the login form and the SPA shell."""

import mimetypes
import os
import re
import time

from django.conf import settings as django_settings
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from cinefin.api.models import Bumper, Certification, Movie, Programme, Trailer
from cinefin.api.utils.paths import contained_in

# =============================================================================
# Streaming
# =============================================================================


def _stream_authorized(request, kind, obj_id):
    """A logged-in session OR the signed token get_stream_url() puts on the URL
    (MPV has no session). No-op while auth is off."""
    from cinefin.api.services.auth_service import auth_is_active
    from cinefin.api.utils.stream_token import check_stream_token

    if not auth_is_active(request):
        return True
    if getattr(request, "user", None) is not None and request.user.is_authenticated:
        return True
    return check_stream_token(kind, obj_id, request.GET.get("t"))


def _movie_path(movie_id):
    movie = get_object_or_404(Movie, id=movie_id)
    if not movie.file_path:
        raise Http404("Movie has no local file")
    return movie.file_path


def _title_path(programme_id):
    path = get_object_or_404(Programme, id=programme_id).get_title_file_path()
    if not path:
        raise Http404("No title generated for this programme")
    return path


def _system_path(obj_id):
    from cinefin.api.utils.assets import system_black_path, system_ident_path

    # Fixed system assets carry constant token ids: 0 = black clip, 1 = System Ident.
    return system_ident_path() if obj_id else system_black_path()


_STREAM_PATHS = {
    "trailer": lambda pk: get_object_or_404(Trailer, id=pk).file_path,
    "bumper": lambda pk: get_object_or_404(Bumper, id=pk).file_path,
    "certification": lambda pk: get_object_or_404(Certification, id=pk).file_path,
    "movie": _movie_path,
    "title": _title_path,
    "system": _system_path,
}


def stream_media(request, kind, pk):
    if not _stream_authorized(request, kind, pk):
        return HttpResponse(status=401)
    return _stream_file(request, _STREAM_PATHS[kind](pk))


def _allowed_media_roots():
    roots = [django_settings.MEDIA_ROOT, django_settings.CINEFIN_ASSETS_DIR]
    return [os.path.realpath(r) for r in roots if r]


def _file_slice(path, start, length):
    with open(path, "rb") as fh:
        fh.seek(start)
        while length > 0 and (chunk := fh.read(min(8192, length))):
            length -= len(chunk)
            yield chunk


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def _stream_file(request, file_path):
    """Serve a file with real HTTP Range support: MPV must fetch the trailing
    moov atom of a non-faststart .mov/.mp4 before playing, and seeks use Range.

    The resolved path (symlinks included) must live under a media root, so a
    poisoned DB row can't serve arbitrary filesystem paths."""
    from cinefin.api.utils.media_paths import usermedia_abs_path

    file_path = usermedia_abs_path(file_path)
    if not file_path or not os.path.isabs(file_path):
        raise Http404("Invalid media path")
    real_path = os.path.realpath(file_path)
    if not any(contained_in(real_path, root) for root in _allowed_media_roots()):
        raise Http404("Invalid media path")
    if not os.path.exists(real_path):
        raise Http404(f"File not found: {file_path}")

    content_type = mimetypes.guess_type(real_path)[0] or "video/mp4"
    size = os.path.getsize(real_path)

    match = _RANGE_RE.match(request.headers.get("Range", "").strip())
    if match and size > 0:
        start_s, end_s = match.groups()
        if start_s:
            start = int(start_s)
            end = min(int(end_s), size - 1) if end_s else size - 1
        elif end_s:  # suffix range: last N bytes
            start, end = max(0, size - int(end_s)), size - 1
        else:
            start, end = 0, size - 1
        if start >= size or start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        length = end - start + 1
        response = StreamingHttpResponse(_file_slice(real_path, start, length), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(length)
    else:
        response = FileResponse(open(real_path, "rb"), content_type=content_type)
        response["Content-Length"] = size
    response["Accept-Ranges"] = "bytes"
    return response


# =============================================================================
# Authentication (the optional auth gate)
# =============================================================================


def _safe_next(request, fallback="/"):
    """The ?next= target if it is same-host (no open redirects), else the fallback."""
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return fallback


# Brute-force guard: after _LOGIN_MAX_FAILURES failures from one address, refuse
# for _LOGIN_LOCKOUT_SECONDS. In-memory per process (a restart clears it).
_login_failures: dict[str, list] = {}  # ip -> [count, locked_until (monotonic)]
_LOGIN_MAX_FAILURES = 5
_LOGIN_LOCKOUT_SECONDS = 60


def _client_ip(request) -> str:
    # X-Forwarded-For is client-spoofable, so it is trusted only behind a proxy
    # (CINEFIN_TRUST_PROXY); else every client behind a proxy shares one bucket.
    if getattr(django_settings, "CINEFIN_TRUST_PROXY", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "?")


def _login_locked(ip: str) -> bool:
    entry = _login_failures.get(ip)
    return bool(entry and entry[1] > time.monotonic())


def _login_failed(ip: str) -> None:
    if len(_login_failures) > 1000:  # bound the table against address churn
        _login_failures.clear()
    entry = _login_failures.setdefault(ip, [0, 0.0])
    entry[0] += 1
    if entry[0] >= _LOGIN_MAX_FAILURES:
        entry[1] = time.monotonic() + _LOGIN_LOCKOUT_SECONDS
        entry[0] = 0


def login_view(request):
    """The login form; with auth off or already logged in it bounces to ?next=."""
    from cinefin.api.services.auth_service import auth_is_active

    if request.user.is_authenticated or not auth_is_active(request):
        return redirect(_safe_next(request))

    error = None
    if request.method == "POST":
        ip = _client_ip(request)
        if _login_locked(ip):
            error = "Too many failed attempts — wait a minute and try again."
        else:
            username = (request.POST.get("username") or "").strip()
            password = request.POST.get("password") or ""
            user = authenticate(request, username=username, password=password)
            if user is not None and user.is_active:
                _login_failures.pop(ip, None)
                auth_login(request, user)
                return redirect(_safe_next(request))
            _login_failed(ip)
            error = "Incorrect username or password."

    return render(
        request,
        "login.html",
        {"error": error, "next": request.GET.get("next", "") or request.POST.get("next", "")},
        status=401 if error else 200,
    )


def logout_view(request):
    auth_logout(request)
    return redirect("/login/")


# =============================================================================
# SPA (SvelteKit build under /app/ — see settings.FRONTEND_BUILD_DIR)
# =============================================================================

# Kit's immutable assets are content-hashed, so they can be cached forever.
_SPA_IMMUTABLE_PREFIX = "_app/immutable/"


def spa_view(request, path=""):
    """A real build file when `path` names one, else the index.html fallback for
    client-side routing. WhiteNoise can't mount a tree outside STATIC_URL, so
    this view serves the whole build."""
    build_dir = os.path.realpath(django_settings.FRONTEND_BUILD_DIR)
    index = os.path.join(build_dir, "index.html")
    if not os.path.isfile(index):
        return HttpResponse(
            "The SPA has not been built. Run `npm run build:spa` (or `npm run build` in frontend/).",
            status=404,
            content_type="text/plain",
        )

    if path:
        candidate = os.path.realpath(os.path.join(build_dir, path))
        if contained_in(candidate, build_dir) and os.path.isfile(candidate):
            content_type = mimetypes.guess_type(candidate)[0] or "application/octet-stream"
            response = FileResponse(open(candidate, "rb"), content_type=content_type)
            if path.startswith(_SPA_IMMUTABLE_PREFIX):
                response["Cache-Control"] = "public, max-age=31536000, immutable"
            return response

    # Never cache the shell, so a new deploy's hashed asset URLs take effect at once.
    response = FileResponse(open(index, "rb"), content_type="text/html")
    response["Cache-Control"] = "no-cache"
    return response
