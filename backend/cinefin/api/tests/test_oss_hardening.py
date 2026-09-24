import pytest
from django.conf import settings as django_settings
from django.contrib.auth.models import User

from cinefin.api.models import Settings

pytestmark = pytest.mark.django_db


class TestSettingsDefaults:
    def test_no_hardcoded_secret_key_fallback(self):
        assert "django-insecure" not in django_settings.SECRET_KEY
        assert len(django_settings.SECRET_KEY) >= 32

    def test_cors_locked_down_by_default(self):
        assert django_settings.CORS_ALLOW_ALL_ORIGINS is False
        assert django_settings.CORS_ALLOWED_ORIGINS == []

    def test_allowed_hosts_defaults_to_wildcard(self):
        # A home box on a trusted LAN accepts any Host by default; restrict it
        # with CINEFIN_ALLOWED_HOSTS=host1,host2. (pytest-django also appends
        # "testserver", so assert the wildcard is present rather than exact.)
        assert "*" in django_settings.ALLOWED_HOSTS

    def test_logfile_is_off_by_default(self):
        assert "file" not in django_settings.LOGGING["handlers"]

    def test_update_host_urls(self):
        from cinefin.api.services.version_check_service import _latest_release_url

        assert _latest_release_url() == (
            "https://api.github.com/repos/" + django_settings.CINEFIN_UPDATE_REPO + "/releases/latest"
        )

    def test_gitea_hosts_still_supported(self, settings):
        from cinefin.api.services.version_check_service import _latest_release_url

        settings.CINEFIN_UPDATE_HOST = "https://gitea.example.com"
        settings.CINEFIN_UPDATE_REPO = "me/cinema"
        assert _latest_release_url() == "https://gitea.example.com/api/v1/repos/me/cinema/releases/latest"


class TestLogfileOptIn:
    def test_setting_the_env_wires_a_rotating_file_handler(self, tmp_path):
        # Settings-only import in a subprocess (no django.setup / DB) with the
        # env set — proves the opt-in logfile wires up and its dir is created.
        import json
        import os
        import subprocess
        import sys
        from pathlib import Path

        logfile = tmp_path / "logs" / "cinefin.log"
        backend_dir = Path(__file__).resolve().parents[3]
        env = {
            **os.environ,
            "CINEFIN_USERDATA_DIR": str(tmp_path / "ud"),
            "CINEFIN_LOG_FILE": str(logfile),
        }
        code = (
            "import json, cinefin.settings as s;"
            "h = s.LOGGING['handlers'].get('file');"
            "print(json.dumps({'class': h and h['class'], 'filename': h and h['filename'],"
            " 'backups': h and h['backupCount'],"
            " 'wired': 'file' in s.LOGGING['loggers']['cinefin']['handlers']}))"
        )
        result = subprocess.run([sys.executable, "-c", code], env=env, cwd=backend_dir, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout.strip().splitlines()[-1])
        assert data["class"] == "logging.handlers.RotatingFileHandler"
        assert data["filename"] == str(logfile)
        assert data["backups"] == 5
        assert data["wired"] is True
        assert logfile.parent.is_dir()


class TestLoginThrottle:
    @pytest.fixture
    def auth_on(self):
        User.objects.create_user("owner", password="right-horse-battery")
        Settings.set("security.auth_enabled", True)

    def test_lockout_after_repeated_failures(self, client, auth_on):
        for _ in range(5):
            resp = client.post("/login/", {"username": "owner", "password": "wrong"})
            assert resp.status_code == 401
        resp = client.post("/login/", {"username": "owner", "password": "wrong"})
        assert "Too many failed attempts" in resp.content.decode()
        resp = client.post("/login/", {"username": "owner", "password": "right-horse-battery"})
        assert "Too many failed attempts" in resp.content.decode()

    def test_success_clears_the_counter(self, client, auth_on):
        for _ in range(3):
            client.post("/login/", {"username": "owner", "password": "wrong"})
        resp = client.post("/login/", {"username": "owner", "password": "right-horse-battery"})
        assert resp.status_code == 302
        from cinefin import views

        assert "127.0.0.1" not in views._login_failures


class TestInstallerGuard:
    def test_complete_refused_after_setup_finished(self, client):
        Settings.set("setup.wizard_step", 0)
        resp = client.post(
            "/api/v2/installer/complete",
            {"cinema_name": "Takeover Cinema", "ratings_system": "BBFC"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "already complete" in resp.content.decode()

    def test_complete_refused_even_mid_wizard(self, client):
        """Regression: /complete is auth-exempt and can set the admin password, so it must stay refused mid-wizard."""
        Settings.set("setup.wizard_step", 3)
        resp = client.post(
            "/api/v2/installer/complete",
            {"cinema_name": "Takeover Cinema", "ratings_system": "BBFC"},
            content_type="application/json",
        )
        assert resp.status_code == 400
        assert "already complete" in resp.content.decode()
