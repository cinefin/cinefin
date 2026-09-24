import json

import pytest
from django.test import Client

from cinefin.api.models import Command, Settings
from cinefin.api.services import auth_service, command_runner

pytestmark = pytest.mark.django_db

API = "/api/v2"
PASSWORD = "correct-horse-42"


def post_json(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def make_command():
    return Command.objects.create(name="Echo", provider="rest", config={"url": "http://echo.invalid/"})


def enable_auth(username="admin", password=PASSWORD):
    auth_service.set_password(password, username=username)
    auth_service.enable_auth()


@pytest.fixture
def spa_build(settings, tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>SPA</title>")
    settings.FRONTEND_BUILD_DIR = str(tmp_path)


def test_disabled_api_open(client):
    assert client.get(f"{API}/health").status_code == 200


def test_enabled_unauth_page_redirects_to_login(client):
    enable_auth()
    resp = client.get("/app/settings")
    assert resp.status_code == 302
    assert resp["Location"].startswith("/login/?next=")


def test_enabled_unauth_api_get_401(client):
    enable_auth()
    resp = client.get(f"{API}/movies/list")
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "AUTHENTICATION_REQUIRED"


def test_update_check_toggle_is_gated(client):
    """The state-changing update-check toggle must be gated when auth is on, though it shares the public /system/ prefix."""
    enable_auth()
    resp = client.post(
        "/system/update-check/toggle",
        {"enabled": False},
        content_type="application/json",
    )
    assert resp.status_code == 302
    assert resp["Location"].startswith("/login/")


def test_enabled_unauth_command_execute_401(client, monkeypatch):
    cmd = make_command()
    enable_auth()
    fired = []
    monkeypatch.setattr(command_runner, "execute", lambda *a, **k: fired.append(a))
    resp = client.post(f"{API}/commands/{cmd.id}/execute")
    assert resp.status_code == 401
    assert fired == []


def test_login_page_always_reachable(client):
    enable_auth()
    assert client.get("/login/").status_code == 200


def test_other_media_still_gated_unauth(client):
    enable_auth()
    resp = client.get("/media/uploads/secret.bin")
    assert resp.status_code == 302
    assert "/login" in resp["Location"]


def test_enabled_auth_api_ok(client):
    enable_auth()
    client.force_login(auth_service.get_single_user())
    assert client.get(f"{API}/movies/list").status_code == 200


def test_kiosk_public_status_endpoint_reachable_unauth(client):
    enable_auth()
    Settings.set("security.kiosk_public", True)
    assert client.get(f"{API}/schedules/list").status_code == 200


def test_kiosk_public_does_not_open_other_endpoints(client):
    enable_auth()
    Settings.set("security.kiosk_public", True)
    assert client.get(f"{API}/movies/list").status_code == 401


def test_fail_open_flag_without_account(client, spa_build):
    """Flag set True but no account exists must be treated as disabled."""
    Settings.set("security.auth_enabled", True)
    assert auth_service.auth_is_active() is False
    assert client.get("/app/settings").status_code == 200
    assert client.get(f"{API}/health").status_code == 200


def test_set_password_then_enable(client):
    resp = post_json(client, f"{API}/security/set-password", {"password": PASSWORD, "enable_auth": True})
    assert resp.status_code == 200
    assert auth_service.auth_is_active() is True


def test_login_open_redirect_blocked(client):
    enable_auth()
    resp = client.post(
        "/login/",
        {"username": "admin", "password": PASSWORD, "next": "https://evil.example/"},
    )
    assert resp.status_code == 302
    assert resp["Location"] == "/"


def test_installer_complete_is_refused_after_setup_completes(client, setup_incomplete):
    """Regression: the auth-exempt /complete must not be re-runnable once setup is done (it can set the admin password)."""
    first = post_json(
        client,
        f"{API}/installer/complete",
        {"cinema_name": "The Roxy", "admin_password": PASSWORD},
    )
    assert first.status_code == 200

    second = post_json(
        client,
        f"{API}/installer/complete",
        {"cinema_name": "Hijacked", "admin_password": "attacker-set-this"},
    )
    assert second.status_code == 400
    user = auth_service.get_single_user()
    assert user.check_password(PASSWORD)
    assert not user.check_password("attacker-set-this")


def test_csrf_enforced_for_authenticated_session():
    Settings.set("setup.completed", True)
    enable_auth()
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(auth_service.get_single_user())
    cmd = make_command()
    resp = csrf_client.post(f"{API}/commands/{cmd.id}/execute")
    assert resp.status_code == 403


class TestStreamTokens:
    """When auth is on, /stream/ accepts a session OR the signed ?t= token, since MPV can't log in."""

    @pytest.fixture(autouse=True)
    def _media_root(self, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)

    @staticmethod
    def _trailer(tmp_path):
        from cinefin.api.tests.factories import TrailerFactory

        media = tmp_path / "trailer.mp4"
        media.write_bytes(b"not really video")
        return TrailerFactory(file_path=str(media))

    def test_auth_on_stream_needs_token(self, client, tmp_path):
        trailer = self._trailer(tmp_path)
        enable_auth()
        assert client.get(f"/stream/trailer/{trailer.id}/").status_code == 401
        assert client.get(f"/stream/trailer/{trailer.id}/?t=wrong").status_code == 401

    def test_auth_on_valid_token_streams(self, client, tmp_path):
        from cinefin.api.utils.stream_token import make_stream_token

        trailer = self._trailer(tmp_path)
        enable_auth()
        token = make_stream_token("trailer", trailer.id)
        resp = client.get(f"/stream/trailer/{trailer.id}/?t={token}")
        assert resp.status_code == 200
        resp.close()

    def test_auth_on_session_streams_without_token(self, tmp_path):
        trailer = self._trailer(tmp_path)
        enable_auth()
        client = Client()
        assert client.login(username="admin", password=PASSWORD)
        resp = client.get(f"/stream/trailer/{trailer.id}/")
        assert resp.status_code == 200
        resp.close()

    def test_token_is_per_object(self, client, tmp_path):
        from cinefin.api.utils.stream_token import make_stream_token

        trailer = self._trailer(tmp_path)
        enable_auth()
        other = make_stream_token("trailer", trailer.id + 1)
        assert client.get(f"/stream/trailer/{trailer.id}/?t={other}").status_code == 401

    @staticmethod
    def _titled_programme(tmp_path):
        from cinefin.api.models import Programme

        title = tmp_path / "title.mp4"
        title.write_bytes(b"not really video")
        return Programme.objects.create(name="Titled", title_file=str(title))
