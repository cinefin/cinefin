"""
Settings for running Cinefin in Docker.

Imports the project settings and applies environment-variable overrides, so the
image is configurable without editing settings.py. Selected via
DJANGO_SETTINGS_MODULE=cinefin.settings_docker (set in the Dockerfile).

The one knob most installs set is CINEFIN_SERVER_URL (your box's address);
ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS derive from it, and SECRET_KEY is
auto-generated. Everything else is optional.

All runtime data lives under one dir, CINEFIN_USERDATA_DIR (default /app/userdata):
the SQLite db, user media (userdata/media), the persisted SECRET_KEY and, when
enabled, the logfile. Mount that one dir as a volume.

Env vars:
    CINEFIN_SERVER_URL     your box's base URL  (e.g. http://cinema.local — the address
                                                 you browse to; drives CSRF + the playout
                                                 stream URLs)
    DEBUG                  true/false           (default: false)
    ALLOWED_HOSTS          comma list or '*'    (default: '*' — accept any Host)
    CSRF_TRUSTED_ORIGINS   comma list of URLs   (default: CINEFIN_SERVER_URL's origin)
    SECRET_KEY             string               (default: auto-generated + persisted — optional)
    CINEFIN_USERDATA_DIR   runtime data dir     (default: /app/userdata — mount this)
    SQLITE_PATH            db file override     (default: userdata/db.sqlite3)
    CINEFIN_USERMEDIA_DIR  media dir override   (default: userdata/media)
    CINEFIN_SECRET_KEY_FILE key file override   (default: userdata/.secret_key)
    CINEFIN_LOG_FILE       logfile path         (default: unset — set e.g. /app/userdata/logs/cinefin.log)
    CINEFIN_LOG_LEVEL     log level name       (default: INFO — read by settings.py)
"""

import os

from cinefin.settings import *  # noqa: F401,F403


def _bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# Production-off by default, same as the base settings (which read
# CINEFIN_DEBUG; this container-specific DEBUG var takes precedence).
DEBUG = _bool("DEBUG", False)

# The single knob most installs set is CINEFIN_SERVER_URL — the address you
# browse to and that the playout agent/kiosk fetch streams from. CSRF_TRUSTED_ORIGINS
# derives from it; it still accepts an explicit env override.
from urllib.parse import urlparse  # noqa: E402

_server_url = os.environ.get("CINEFIN_SERVER_URL", "").strip()
_server = urlparse(_server_url) if _server_url else None

# ALLOWED_HOSTS: explicit env wins; otherwise inherit the base default ("*", accept
# any Host — a home box on a trusted LAN). Restrict with ALLOWED_HOSTS=host1,host2.
if os.environ.get("ALLOWED_HOSTS"):
    ALLOWED_HOSTS = [h.strip() for h in os.environ["ALLOWED_HOSTS"].split(",") if h.strip()]

# SECRET_KEY is auto-generated and persisted under the userdata dir (see
# settings.py). Setting it explicitly is optional — only needed to share a key
# across instances — and overrides the generated one when present.
if os.environ.get("SECRET_KEY"):
    SECRET_KEY = os.environ["SECRET_KEY"]

# CSRF_TRUSTED_ORIGINS: explicit env wins; otherwise trust the server URL's
# origin (scheme://host[:port]) so unsafe requests from the browsed address pass.
if os.environ.get("CSRF_TRUSTED_ORIGINS"):
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ["CSRF_TRUSTED_ORIGINS"].split(",") if o.strip()]
elif _server and _server.scheme and _server.netloc:
    CSRF_TRUSTED_ORIGINS = [f"{_server.scheme}://{_server.netloc}"]

# The db, media and secret key all resolve under CINEFIN_USERDATA_DIR (default
# /app/userdata) via the base settings — nothing to override here.

# Static serving: the base settings already use WhiteNoise's non-manifest
# CompressedStaticFilesStorage (via STORAGES) plus WHITENOISE_USE_FINDERS, so
# nothing to override here — the image's collectstatic output is used when
# present and a stray missing reference can't 500 a whole page.
