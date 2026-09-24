import json
import mimetypes
import os
import re
import time

from django.conf import settings as django_settings
from django.contrib.auth import authenticate
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.http import FileResponse, Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from cinefin.api.models import (
    Bumper,
    Certification,
    Movie,
    Programme,
    Settings,
    Trailer,
)
from cinefin.api.utils.paths import contained_in

# NOTE: the legacy server-rendered UI is gone — the SvelteKit SPA under
# frontend/ (served by spa_view at /app/) is THE UI. What remains here is
# infrastructure only: streaming, auth, the first-run installer (the one
# surviving server-rendered page — its SPA port is a documented follow-up),
# the SPA serving view and the update-check JSON endpoints.

# =============================================================================
# Streaming Views - Serve local media files via HTTP
# =============================================================================


def _stream_authorized(request, kind, obj_id):
    """A stream request is authorised by a logged-in session OR the signed
    token get_stream_url() puts on the URL — MPV has no session, so playlists
    carry tokens (see api.utils.stream_token). No-op while auth is off."""
    from cinefin.api.services.auth_service import auth_is_active
    from cinefin.api.utils.stream_token import check_stream_token

    if not auth_is_active(request):
        return True
    if getattr(request, "user", None) is not None and request.user.is_authenticated:
        return True
    return check_stream_token(kind, obj_id, request.GET.get("t"))


def stream_trailer(request, trailer_id):
    """Stream a trailer file."""
    if not _stream_authorized(request, "trailer", trailer_id):
        return HttpResponse(status=401)
    trailer = get_object_or_404(Trailer, id=trailer_id)
    return _stream_file(request, trailer.file_path)


def stream_bumper(request, bumper_id):
    """Stream a bumper file."""
    if not _stream_authorized(request, "bumper", bumper_id):
        return HttpResponse(status=401)
    bumper = get_object_or_404(Bumper, id=bumper_id)
    return _stream_file(request, bumper.file_path)


def stream_certification(request, certification_id):
    """Stream a certification file."""
    if not _stream_authorized(request, "certification", certification_id):
        return HttpResponse(status=401)
    cert = get_object_or_404(Certification, id=certification_id)
    return _stream_file(request, cert.file_path)


def stream_movie(request, movie_id):
    """Stream a movie's local file (the streaming-only fallback for movies with
    no Plex/Jellyfin origin — provider-backed movies stream from their own
    server, not here)."""
    if not _stream_authorized(request, "movie", movie_id):
        return HttpResponse(status=401)
    movie = get_object_or_404(Movie, id=movie_id)
    if not movie.file_path:
        raise Http404("Movie has no local file")
    return _stream_file(request, movie.file_path)


def stream_system_black(request):
    """Stream the bundled black clip (end-of-programme sentinel + hold-black
    command items). A fixed system asset, so the token has a constant id."""
    if not _stream_authorized(request, "system", 0):
        return HttpResponse(status=401)
    from cinefin.api.utils.assets import system_black_path

    return _stream_file(request, system_black_path())


def stream_system_ident(request):
    """Stream the bundled System Ident — the idle splash used when no user media
    item is set as the default ident. A fixed system asset, so the token has a
    constant id (1, next to the black clip's 0)."""
    if not _stream_authorized(request, "system", 1):
        return HttpResponse(status=401)
    from cinefin.api.utils.assets import system_ident_path

    return _stream_file(request, system_ident_path())


def stream_title(request, programme_id):
    """Stream a programme's generated title card (the opening item when a
    programme has a title template). Served so the remote playout host can
    fetch it — no local file needed there."""
    if not _stream_authorized(request, "title", programme_id):
        return HttpResponse(status=401)
    programme = get_object_or_404(Programme, id=programme_id)
    path = programme.get_title_file_path()
    if not path:
        raise Http404("No title generated for this programme")
    return _stream_file(request, path)


def _allowed_media_roots():
    """Directories media may legitimately be streamed from.

    Uploaded/generated media (and downloaded trailers, which live in the fixed
    MEDIA_ROOT/trailers subdir) sit under MEDIA_ROOT; bundled system files sit
    under the assets dir. Both cover everything streamable, so there's no
    per-request path lookup any more.
    """
    roots = [django_settings.MEDIA_ROOT, django_settings.CINEFIN_ASSETS_DIR]
    return [os.path.realpath(r) for r in roots if r]


class _FileSlice:
    """Iterator over one byte range of a file — the body of a 206 response."""

    CHUNK = 8192

    def __init__(self, path, start, length):
        self.fh = open(path, "rb")
        self.fh.seek(start)
        self.remaining = length

    def __iter__(self):
        return self

    def __next__(self):
        if self.remaining <= 0:
            self.fh.close()
            raise StopIteration
        chunk = self.fh.read(min(self.CHUNK, self.remaining))
        if not chunk:
            self.fh.close()
            raise StopIteration
        self.remaining -= len(chunk)
        return chunk

    def close(self):
        self.fh.close()


_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)$")


def _stream_file(request, file_path):
    """Stream a file with proper content type and real HTTP Range support.

    Players need ranged reads: MPV must fetch the trailing moov atom of a
    non-faststart .mov/.mp4 before it can start playing, and seeking always
    goes through Range. We previously advertised Accept-Ranges while ignoring
    the header — large .mov files simply failed to stream.

    Paths come from DB rows the app wrote itself, but belt-and-braces: the
    resolved path (symlinks included) must live under one of the expected
    media roots, so a poisoned row can't serve arbitrary filesystem paths.

    Stored user-media paths are relative to MEDIA_ROOT (and legacy/stale
    absolute paths self-heal onto it), so resolve to an absolute path first.
    """
    from cinefin.api.utils.media_paths import usermedia_abs_path

    file_path = usermedia_abs_path(file_path)
    if not file_path or not os.path.isabs(file_path):
        raise Http404("Invalid media path")
    real_path = os.path.realpath(file_path)
    if not any(contained_in(real_path, root) for root in _allowed_media_roots()):
        raise Http404("Invalid media path")
    if not os.path.exists(real_path):
        raise Http404(f"File not found: {file_path}")

    content_type, _ = mimetypes.guess_type(real_path)
    if not content_type:
        content_type = "video/mp4"
    size = os.path.getsize(real_path)

    match = _RANGE_RE.match(request.headers.get("Range", "").strip())
    if match and size > 0:
        start_s, end_s = match.groups()
        if start_s:
            start = int(start_s)
            end = min(int(end_s), size - 1) if end_s else size - 1
        elif end_s:  # suffix range: last N bytes
            start = max(0, size - int(end_s))
            end = size - 1
        else:
            start, end = 0, size - 1
        if start >= size or start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            return response
        length = end - start + 1
        response = StreamingHttpResponse(_FileSlice(real_path, start, length), status=206, content_type=content_type)
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
        response["Content-Length"] = str(length)
        response["Accept-Ranges"] = "bytes"
        return response

    response = FileResponse(open(real_path, "rb"), content_type=content_type)
    response["Accept-Ranges"] = "bytes"
    response["Content-Length"] = size
    return response


# =============================================================================
# Authentication (optional auth gate — issue #124)
# =============================================================================


def _safe_next(request, fallback="/"):
    """Return the validated ?next= target, or a safe fallback.

    Guards against open-redirects: only same-host, non-scheme URLs are allowed.
    """
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    if nxt and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return fallback


# Brute-force guard for the login form: after _LOGIN_MAX_FAILURES failed
# attempts from one address, further attempts are refused for
# _LOGIN_LOCKOUT_SECONDS. In-memory per process — right-sized for a
# single-box home app (a restart clears it, which is fine).
_login_failures: dict[str, list] = {}  # ip -> [count, locked_until (monotonic)]
_LOGIN_MAX_FAILURES = 5
_LOGIN_LOCKOUT_SECONDS = 60


def _client_ip(request) -> str:
    """The requester's IP for the lockout key.

    Behind a reverse proxy REMOTE_ADDR is the proxy, so every client would
    share one lockout bucket (one attacker locks everyone out). When
    CINEFIN_TRUST_PROXY is set — i.e. a trusted proxy populates it — use the
    first X-Forwarded-For hop instead. Off by default: the header is
    client-spoofable, so trusting it without a proxy would let an attacker
    rotate it to dodge the lockout.
    """
    from django.conf import settings as django_settings

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
    """Styled login form for the optional auth gate.

    GET renders the form; POST authenticates and, on success, redirects to the
    validated ?next= target (or the dashboard). Always reachable — the auth
    gate exempts /login — so it is the one way back in when auth is on.

    If auth is off, or the user is already logged in, there's nothing to do:
    bounce to next/dashboard so /login/ is never a dead end.
    """
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

    # Branding (cinema_name / cinema_web_logo_url / accent_color) comes from the
    # cinema_config context processor, so it's available here too.
    return render(
        request,
        "login.html",
        {"error": error, "next": request.GET.get("next", "") or request.POST.get("next", "")},
        status=401 if error else 200,
    )


def logout_view(request):
    """Log out and return to the login page."""
    auth_logout(request)
    return redirect("/login/")


# =============================================================================
# SPA (SvelteKit build under /app/ — see settings.FRONTEND_BUILD_DIR)
# =============================================================================

# Kit's immutable assets are content-hashed, so they can be cached forever.
_SPA_IMMUTABLE_PREFIX = "_app/immutable/"


def spa_view(request, path=""):
    """Serve the built SPA: a real build file when `path` names one, otherwise
    the index.html fallback so the client router handles /app/<anything>.

    Plain Django file serving, like the /media/ routes: WhiteNoise can't mount
    an extra tree outside STATIC_URL and the Kit build addresses its assets at
    /app/_app/…, so this view is the single serving point. Auth: /app is not
    in AuthGateMiddleware's exempt list, so when the auth gate is on the SPA
    sits behind the same login redirect as every legacy page.
    """
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

    # SPA fallback: any other /app/* path gets the shell; never cache it so a
    # new deploy's hashed asset URLs take effect immediately.
    response = FileResponse(open(index, "rb"), content_type="text/html")
    response["Cache-Control"] = "no-cache"
    return response


# ============================================================================
# Update check (plain JSON — see urls.py for why these outlive the legacy UI)
# ============================================================================


def update_check_view(request):
    """Plain JSON view for the update-available check.

    Returns ``{update_available, latest, url, checked_at}``. Never errors on a
    network failure — the service degrades to update_available=False. Consumed
    by the SPA's System/About page (routes/system/+page.svelte). (The toggle
    sibling endpoint still has no consumer.)
    """
    from cinefin.api.services.version_check_service import check_for_update

    return JsonResponse(check_for_update())


@require_POST
def update_check_toggle_view(request):
    """Enable/disable the update check (``display.update_check``).

    Accepts a JSON body ``{"enabled": bool}``; returns the new state. When
    disabled, the cached result is cleared so any consumer stops hinting at
    once.
    """
    from cinefin.api.services.version_check_service import _clear_cache

    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        payload = {}
    enabled = bool(payload.get("enabled", True))
    Settings.set("display.update_check", enabled)
    _clear_cache()
    return JsonResponse({"enabled": enabled})
