"""Settings for the Playwright smoke pack: the dev settings on a throwaway db
(CINEFIN_E2E_DB, created by scripts/e2e-server.sh). Background workers stay on —
the dashboard shows the schedule runner heartbeat."""

import os

from cinefin.settings import *  # noqa: F403
from cinefin.settings import DATABASES

DATABASES = {"default": {**DATABASES["default"], "NAME": os.environ.get("CINEFIN_E2E_DB", "/tmp/cinefin-e2e.sqlite3")}}
