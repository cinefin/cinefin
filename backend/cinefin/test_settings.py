"""
Settings for the test suite (pytest-django points here via pyproject.toml).

Same as production settings except: no background worker threads, an
in-memory database, and a throwaway MPV socket path so nothing ever
touches the real player.
"""

from cinefin.settings import *  # noqa: F403

CINEFIN_DISABLE_BACKGROUND_WORKERS = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Keep password hashing fast if any test creates users
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
