import pytest
from django.test import Client

from cinefin.api.models import APIKey, Command, Settings
from cinefin.api.services import auth_service, command_runner
from cinefin.api.utils.stream_token import make_stream_token

from .factories import TrailerFactory

pytestmark = pytest.mark.django_db

API = "/api/v2"
PASSWORD = "correct-horse-42"


def make_command():
    return Command.objects.create(name="Echo", provider="rest", config={"url": "http://echo.invalid/"})


def enable_auth():
    auth_service.set_password(PASSWORD, username="admin")
    auth_service.enable_auth()


class TestGate:
    def test_off_is_open_and_flag_without_account_fails_open(self, client, settings, tmp_path):
        (tmp_path / "index.html").write_text("<!doctype html><title>SPA</title>")
        settings.FRONTEND_BUILD_DIR = str(tmp_path)
        assert client.get(f"{API}/movies/list").status_code == 200
        Settings.set("security.auth_enabled", True)
        assert auth_service.auth_is_active() is False
        assert client.get("/app/settings").status_code == 200

    def test_on_gates_pages_api_and_media_but_not_login(self, client):
        enable_auth()
        resp = client.get("/app/settings")
        assert resp.status_code == 302 and resp["Location"].startswith("/login/?next=")
        resp = client.get(f"{API}/movies/list")
        assert resp.status_code == 401 and resp.json()["error_code"] == "AUTHENTICATION_REQUIRED"
        assert "/login" in client.get("/media/uploads/secret.bin")["Location"]
        assert client.get("/login/").status_code == 200
        client.force_login(auth_service.get_single_user())
        assert client.get(f"{API}/movies/list").status_code == 200

    def test_unauth_command_execute_never_fires(self, client, monkeypatch):
        cmd = make_command()
        enable_auth()
        fired = []
        monkeypatch.setattr(command_runner, "execute", lambda *a, **k: fired.append(a))
        assert client.post(f"{API}/commands/{cmd.id}/execute").status_code == 401
        assert fired == []

    def test_kiosk_public_opens_only_kiosk_polls(self, client):
        enable_auth()
        Settings.set("security.kiosk_public", True)
        assert client.get(f"{API}/schedules/list").status_code == 200
        assert client.get(f"{API}/movies/list").status_code == 401

    def test_login_open_redirect_blocked(self, client):
        enable_auth()
        resp = client.post("/login/", {"username": "admin", "password": PASSWORD, "next": "https://evil.example/"})
        assert resp.status_code == 302 and resp["Location"] == "/"

    def test_installer_complete_is_refused_after_setup_completes(self, client, setup_incomplete):
        # The auth-exempt /complete can set the admin password, so it must not be re-runnable.
        url = f"{API}/installer/complete"
        body = {"cinema_name": "The Roxy", "admin_password": PASSWORD}
        assert client.post(url, body, content_type="application/json").status_code == 200
        body = {"cinema_name": "Hijacked", "admin_password": "attacker-set-this"}
        assert client.post(url, body, content_type="application/json").status_code == 400
        assert auth_service.get_single_user().check_password(PASSWORD)

    def test_csrf_enforced_for_authenticated_session(self):
        enable_auth()
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(auth_service.get_single_user())
        assert csrf_client.post(f"{API}/commands/{make_command().id}/execute").status_code == 403


class TestStreamTokens:
    """With auth on, /stream/ takes a session OR the signed ?t= token, since mpv can't log in."""

    @pytest.fixture
    def trailer(self, tmp_path, settings):
        settings.MEDIA_ROOT = str(tmp_path)
        media = tmp_path / "trailer.mp4"
        media.write_bytes(b"not really video")
        trailer = TrailerFactory(file_path=str(media))
        enable_auth()
        return trailer

    def test_needs_a_valid_per_object_token(self, client, trailer):
        url = f"/stream/trailer/{trailer.id}/"
        assert client.get(url).status_code == 401
        assert client.get(f"{url}?t=wrong").status_code == 401
        assert client.get(f"{url}?t={make_stream_token('trailer', trailer.id + 1)}").status_code == 401
        resp = client.get(f"{url}?t={make_stream_token('trailer', trailer.id)}")
        assert resp.status_code == 200
        resp.close()

    def test_session_streams_without_token(self, trailer):
        client = Client()
        assert client.login(username="admin", password=PASSWORD)
        resp = client.get(f"/stream/trailer/{trailer.id}/")
        assert resp.status_code == 200
        resp.close()


class TestAPIKeys:
    def test_create_stores_only_the_hash_and_resolve_records_use(self):
        key, raw = APIKey.create("Home Assistant")
        assert raw.startswith("cplx_") and key.prefix == raw[:13]
        assert len(key.key_hash) == 64 and raw not in (key.prefix, key.key_hash)
        resolved = APIKey.resolve(raw)
        assert resolved.id == key.id
        resolved.refresh_from_db()
        assert resolved.last_used_at is not None

    def test_create_list_revoke_roundtrip(self, client):
        created = client.post(f"{API}/security/api-keys", data={"name": "CI"}, content_type="application/json")
        created = created.json()["data"]
        assert created["key"].startswith("cplx_")
        listed = client.get(f"{API}/security/api-keys").json()["data"]
        assert [k["id"] for k in listed] == [created["id"]] and "key" not in listed[0]
        assert client.delete(f"{API}/security/api-keys/{created['id']}").status_code == 200
        assert client.get(f"{API}/security/api-keys").json()["data"] == []

    def test_bearer_key_against_the_gate(self, client):
        _key, raw = APIKey.create("k")
        enable_auth()
        url = f"{API}/programmes/list"
        assert client.get(url, HTTP_AUTHORIZATION=f"Bearer {raw}").status_code == 200
        assert client.get(url, HTTP_AUTHORIZATION="Bearer cplx_wrong").status_code == 401
        # A key authorises an unsafe method without CSRF.
        resp = client.post(
            f"{API}/security/api-keys",
            data={"name": "made-by-key"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {raw}",
        )
        assert resp.status_code == 200
