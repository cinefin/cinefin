import pytest

from cinefin.api.models import APIKey
from cinefin.api.services import auth_service

pytestmark = pytest.mark.django_db


def _enable_auth(password="secret123"):
    auth_service.set_password(password)
    auth_service.enable_auth()
    assert auth_service.auth_is_active() is True


class TestAPIKeyModel:
    def test_create_returns_raw_key_once_and_stores_only_the_hash(self):
        key, raw = APIKey.create("Home Assistant")
        assert raw.startswith("cplx_")
        assert key.prefix == raw[:13]
        assert key.key_hash != raw
        assert len(key.key_hash) == 64
        assert raw not in (key.prefix, key.key_hash)

    def test_resolve_matches_and_records_last_used(self):
        key, raw = APIKey.create("k")
        assert key.last_used_at is None
        resolved = APIKey.resolve(raw)
        assert resolved is not None and resolved.id == key.id
        resolved.refresh_from_db()
        assert resolved.last_used_at is not None


class TestAPIKeyEndpoints:
    def test_create_list_revoke_roundtrip(self, client):
        r = client.post("/api/v2/security/api-keys", data={"name": "CI"}, content_type="application/json")
        assert r.status_code == 200
        created = r.json()["data"]
        assert created["key"].startswith("cplx_")
        assert created["name"] == "CI"
        key_id = created["id"]

        listed = client.get("/api/v2/security/api-keys").json()["data"]
        assert [k["id"] for k in listed] == [key_id]
        assert "key" not in listed[0]

        r = client.delete(f"/api/v2/security/api-keys/{key_id}")
        assert r.status_code == 200
        assert client.get("/api/v2/security/api-keys").json()["data"] == []


class TestBearerAuthAgainstGate:
    def test_key_authorises_when_gate_is_on(self, client):
        _key, raw = APIKey.create("k")
        _enable_auth()
        r = client.get("/api/v2/programmes/list", HTTP_AUTHORIZATION=f"Bearer {raw}")
        assert r.status_code == 200

    def test_bad_key_is_rejected_when_gate_is_on(self, client):
        _enable_auth()
        r = client.get("/api/v2/programmes/list", HTTP_AUTHORIZATION="Bearer cplx_wrong")
        assert r.status_code == 401

    def test_no_credentials_rejected_when_gate_is_on(self, client):
        _enable_auth()
        assert client.get("/api/v2/programmes/list").status_code == 401

    def test_key_authorises_unsafe_method_without_csrf(self, client):
        _key, raw = APIKey.create("k")
        _enable_auth()
        r = client.post(
            "/api/v2/security/api-keys",
            data={"name": "made-by-key"},
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {raw}",
        )
        assert r.status_code == 200
