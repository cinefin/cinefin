"""Django settings for Cinefin."""

import logging
import os
from pathlib import Path

from django.urls import reverse_lazy

from cinefin.cli import resolve_data_dir

# BASE_DIR is backend/ (code assets under cinefin/); REPO_ROOT is the repo root.
BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent

# One directory holds all runtime data (db, media, secret key, logfile); cli.resolve_data_dir
# decides where, so manage.py and `cinefin` agree. SQLITE_PATH etc. still override per item.
CINEFIN_USERDATA_DIR = str(resolve_data_dir()[0])

LOGIN_URL = reverse_lazy("login")
LOGIN_REDIRECT_URL = "/app/"
LOGOUT_REDIRECT_URL = "/app/"


def _load_or_create_secret_key() -> str:
    """$SECRET_KEY, else a key persisted with the userdata (so a backup/restore keeps
    sessions valid), else an ephemeral one when that path is unwritable."""
    from_env = os.environ.get("SECRET_KEY")
    if from_env:
        return from_env
    from django.core.management.utils import get_random_secret_key

    key_file = Path(os.environ.get("CINEFIN_SECRET_KEY_FILE") or os.path.join(CINEFIN_USERDATA_DIR, ".secret_key"))
    try:
        if key_file.exists():
            stored = key_file.read_text().strip()
            if stored:
                return stored
        key_file.parent.mkdir(parents=True, exist_ok=True)
        generated = get_random_secret_key()
        key_file.write_text(generated)
        os.chmod(key_file, 0o600)
        return generated
    except OSError as exc:
        logging.getLogger("cinefin").warning(
            "Could not persist SECRET_KEY at %s (%s) — using an ephemeral key; sessions "
            "will reset every restart. Set the SECRET_KEY env var to a fixed value.",
            key_file,
            exc,
        )
        return get_random_secret_key()


SECRET_KEY = _load_or_create_secret_key()

DEBUG = os.environ.get("CINEFIN_DEBUG", "0") == "1"

# Any Host by default (a home box on a trusted LAN); CINEFIN_ALLOWED_HOSTS=a,b restricts it.
_allowed_hosts = [h.strip() for h in os.environ.get("CINEFIN_ALLOWED_HOSTS", "").split(",") if h.strip()]
ALLOWED_HOSTS = _allowed_hosts or ["*"]

# Key the login lockout on X-Forwarded-For: only behind a trusted proxy, as the header is spoofable.
CINEFIN_TRUST_PROXY = os.environ.get("CINEFIN_TRUST_PROXY", "0") == "1"

# Base of the absolute stream URLs in playlists (Settings' playout.server_url overrides it).
CINEFIN_SERVER_URL = os.environ.get("CINEFIN_SERVER_URL", "http://localhost:8000")

# Skip the background workers and the boot-time media tree (tests, build-time django.setup()).
CINEFIN_DISABLE_BACKGROUND_WORKERS = os.environ.get("CINEFIN_DISABLE_BACKGROUND_WORKERS") == "1"

from cinefin.version import get_version as _get_version  # noqa: E402

CINEFIN_VERSION = _get_version()

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "cinefin.api",
]

CINEFIN_LOG_LEVEL = os.environ.get("CINEFIN_LOG_LEVEL", "INFO").upper()

# uvicorn's per-request access log is noise (the SPA polls); CINEFIN_ACCESS_LOG=1 restores it.
CINEFIN_ACCESS_LOG = os.environ.get("CINEFIN_ACCESS_LOG") == "1"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "cinefin": {
            "handlers": ["console"],
            "level": CINEFIN_LOG_LEVEL,
            "propagate": False,
        },
        "plexapi": {"level": "WARNING"},
        "urllib3": {"level": "WARNING"},
        "yt_dlp": {"level": "WARNING"},
        "uvicorn.access": {
            "handlers": ["console"] if CINEFIN_ACCESS_LOG else [],
            "level": "INFO" if CINEFIN_ACCESS_LOG else "WARNING",
            "propagate": False,
        },
    },
}

# Opt-in rotating logfile (5 MB × 5); Docker and systemd capture stdout anyway.
CINEFIN_LOG_FILE = os.environ.get("CINEFIN_LOG_FILE")
if CINEFIN_LOG_FILE:
    Path(CINEFIN_LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    LOGGING["handlers"]["file"] = {
        "level": "DEBUG",
        "class": "logging.handlers.RotatingFileHandler",
        "filename": CINEFIN_LOG_FILE,
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 5,
        "formatter": "verbose",
    }
    for _target in (LOGGING["root"], LOGGING["loggers"]["django"], LOGGING["loggers"]["cinefin"]):
        _target["handlers"] = [*_target["handlers"], "file"]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "cinefin.middleware.InstallerRedirectMiddleware",
    # After AuthenticationMiddleware (it reads request.user) and the installer redirect.
    "cinefin.middleware.AuthGateMiddleware",
]

ROOT_URLCONF = "cinefin.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": ["cinefin/templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cinefin.context_processors.cinema_config",
            ],
        },
    },
]

WSGI_APPLICATION = "cinefin.wsgi.application"

# Django creates the SQLite file but not its directory.
_sqlite_path = os.environ.get("SQLITE_PATH") or os.path.join(CINEFIN_USERDATA_DIR, "db.sqlite3")
os.makedirs(os.path.dirname(_sqlite_path), exist_ok=True)

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": _sqlite_path,
        # WAL avoids per-insert journal churn (SQLITE_CANTOPEN under fd pressure in bulk
        # syncs); IMMEDIATE takes the write lock up front so atomic blocks can't fail a
        # lock upgrade; the busy timeout lets readers and the writer wait for each other.
        "OPTIONS": {
            "timeout": 30,
            "transaction_mode": "IMMEDIATE",
            "init_command": ("PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL;PRAGMA busy_timeout=30000;"),
        },
    }
}

DATA_UPLOAD_MAX_NUMBER_FIELDS = 200000

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Europe/London"
USE_I18N = True
USE_TZ = True

STATIC_ROOT = os.path.join(BASE_DIR, "cinefin", "staticfiles")
STATIC_URL = "/static/"

# WhiteNoise everywhere, safe where collectstatic never ran: non-manifest storage (the
# manifest variant 500s on any missing entry) and USE_FINDERS (STATIC_ROOT is optional).
# AUTOREFRESH always: without it WhiteNoise caches sizes at startup and serves a file
# changed by a pull truncated to its old Content-Length.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = True

STATICFILES_DIRS = (os.path.join(BASE_DIR, "cinefin", "static"),)

MEDIA_URL = "/media/"
# User media (uploads, generated cards, the trailer tree); stored paths are relative to it.
MEDIA_ROOT = os.environ.get("CINEFIN_USERMEDIA_DIR") or os.path.join(CINEFIN_USERDATA_DIR, "media")

# Bundled app assets (rating cards, system clips); a packaged build may point elsewhere.
CINEFIN_ASSETS_DIR = os.environ.get("CINEFIN_ASSETS_DIR") or os.path.join(BASE_DIR, "cinefin", "assets")

# The SvelteKit build, served at /app/ by cinefin.views.spa_view.
FRONTEND_BUILD_DIR = os.environ.get("CINEFIN_FRONTEND_BUILD_DIR") or os.path.join(REPO_ROOT, "frontend", "build")

# Unset: plugins.plugins_dir() uses REPO_ROOT/contrib/plugins.
CINEFIN_PLUGINS_DIR = os.environ.get("CINEFIN_PLUGINS_DIR") or None

# The UI is same-origin; CORS opens only for your own external client.
CORS_ALLOW_ALL_ORIGINS = os.environ.get("CINEFIN_CORS_ALL", "0") == "1"
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.environ.get("CINEFIN_CORS_ORIGINS", "").split(",") if o.strip()]
CORS_ALLOW_CREDENTIALS = False

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MAX_MEDIA_UPLOAD_SIZE_MB = 5120
