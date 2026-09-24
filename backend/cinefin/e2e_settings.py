"""
Settings for the Playwright end-to-end smoke pack (frontend/e2e).

Same as the dev settings except the database lives wherever
``CINEFIN_E2E_DB`` points (a throwaway file created by scripts/e2e-server.sh)
so a smoke run can never touch the real db.sqlite3. Background workers stay
enabled — the schedule runner heartbeat is part of what the dashboard shows.
"""

import os

from cinefin.settings import *  # noqa: F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.environ.get("CINEFIN_E2E_DB", "/tmp/cinefin-e2e.sqlite3"),
        "OPTIONS": {
            "timeout": 30,
            "transaction_mode": "IMMEDIATE",
            "init_command": ("PRAGMA journal_mode=WAL;PRAGMA synchronous=NORMAL;PRAGMA busy_timeout=30000;"),
        },
    }
}
