"""Settings for the test suite: no background workers, an in-memory database."""

from cinefin.settings import *  # noqa: F403

CINEFIN_DISABLE_BACKGROUND_WORKERS = True

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
