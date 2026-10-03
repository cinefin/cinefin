"""
Settings for running Cinefin in Docker (DJANGO_SETTINGS_MODULE=cinefin.settings_docker).

The one knob most installs set is CINEFIN_SERVER_URL (your box's address);
CSRF_TRUSTED_ORIGINS derives from it and SECRET_KEY is auto-generated. All runtime
data lives under CINEFIN_USERDATA_DIR (default /app/userdata): mount that one dir.

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
from urllib.parse import urlparse

from cinefin.settings import *  # noqa: F401,F403


def _bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


# The container's own DEBUG var takes precedence over the base CINEFIN_DEBUG.
DEBUG = _bool("DEBUG", False)

_server_url = os.environ.get("CINEFIN_SERVER_URL", "").strip()
_server = urlparse(_server_url) if _server_url else None

if os.environ.get("ALLOWED_HOSTS"):
    ALLOWED_HOSTS = [h.strip() for h in os.environ["ALLOWED_HOSTS"].split(",") if h.strip()]

# Explicit env wins; else trust the server URL's origin so unsafe requests from the browsed address pass.
if os.environ.get("CSRF_TRUSTED_ORIGINS"):
    CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.environ["CSRF_TRUSTED_ORIGINS"].split(",") if o.strip()]
elif _server and _server.scheme and _server.netloc:
    CSRF_TRUSTED_ORIGINS = [f"{_server.scheme}://{_server.netloc}"]
