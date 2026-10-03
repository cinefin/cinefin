import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib.auth.models import User

from cinefin.api.models import Settings

pytestmark = pytest.mark.django_db


def test_logfile_env_wires_a_rotating_file_handler(tmp_path):
    # Settings-only import in a subprocess, with the env set.
    logfile = tmp_path / "logs" / "cinefin.log"
    env = {**os.environ, "CINEFIN_USERDATA_DIR": str(tmp_path / "ud"), "CINEFIN_LOG_FILE": str(logfile)}
    code = (
        "import json, cinefin.settings as s; h = s.LOGGING['handlers']['file'];"
        "print(json.dumps([h['class'], h['filename'], 'file' in s.LOGGING['loggers']['cinefin']['handlers']]))"
    )
    cwd = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, "-c", code], env=env, cwd=cwd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [
        "logging.handlers.RotatingFileHandler",
        str(logfile),
        True,
    ]
    assert logfile.parent.is_dir()


class TestLoginThrottle:
    @pytest.fixture(autouse=True)
    def auth_on(self):
        User.objects.create_user("owner", password="right-horse-battery")
        Settings.set("security.auth_enabled", True)

    def _login(self, client, password="wrong"):
        return client.post("/login/", {"username": "owner", "password": password})

    def test_lockout_after_repeated_failures(self, client):
        for _ in range(5):
            assert self._login(client).status_code == 401
        assert "Too many failed attempts" in self._login(client).content.decode()
        assert "Too many failed attempts" in self._login(client, "right-horse-battery").content.decode()


@pytest.mark.parametrize("step", [0, 3])
def test_installer_complete_refused_once_setup_is_done_even_mid_wizard(client, step):
    # /complete is auth-exempt and can set the admin password.
    Settings.set("setup.wizard_step", step)
    resp = client.post(
        "/api/v2/installer/complete",
        {"cinema_name": "Takeover Cinema", "ratings_system": "BBFC"},
        content_type="application/json",
    )
    assert resp.status_code == 400 and "already complete" in resp.content.decode()
