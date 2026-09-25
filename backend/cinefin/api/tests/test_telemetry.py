"""Opt-in telemetry: payload shape, anonymity, cadence, and opt-in minting."""

import json

import pytest

from cinefin import plugins
from cinefin.api.models import Settings
from cinefin.api.services import telemetry_service

from .factories import SyncSourceFactory

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _configured():
    Settings.set("telemetry.enabled", True)
    Settings.set("telemetry.host", "https://aptabase.invalid")
    Settings.set("telemetry.app_key", "A-SH-0000000000")


def test_disabled_sends_nothing(monkeypatch):
    Settings.set("telemetry.enabled", False)
    calls = []
    monkeypatch.setattr(telemetry_service.requests, "post", lambda *a, **k: calls.append(a))
    assert telemetry_service.send() is False
    assert calls == []


def test_no_host_sends_nothing(monkeypatch):
    Settings.set("telemetry.host", "")
    calls = []
    monkeypatch.setattr(telemetry_service.requests, "post", lambda *a, **k: calls.append(a))
    assert telemetry_service.send() is False
    assert calls == []


def test_install_id_only_minted_on_opt_in():
    Settings.set("telemetry.install_id", "")
    minted = telemetry_service.ensure_install_id()
    assert minted and Settings.get("telemetry.install_id") == minted
    # Idempotent: a second call keeps the same id.
    assert telemetry_service.ensure_install_id() == minted


def test_payload_carries_no_identifying_data(monkeypatch):
    src = SyncSourceFactory(sync_type="plex", url="http://secret-host.lan:32400", token="s3cr3t")
    event = telemetry_service.build_event()
    blob = json.dumps(event)

    # Config *shape* is present…
    assert event["eventName"] == "heartbeat"
    assert "plex" in event["props"]["sync_source_types"]
    assert event["props"]["install_id"]
    assert event["props"]["channel"] in ("release", "edge", "dev")
    assert event["systemProps"]["sdkVersion"] == telemetry_service.SDK_VERSION

    # …but no URL, token, path, or source name leaks anywhere in the payload.
    assert src.url not in blob
    assert src.token not in blob
    assert src.name not in blob


def test_send_posts_to_aptabase_and_stamps_last_sent(monkeypatch):
    captured = {}

    class FakeResp:
        status_code = 200

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(url=url, body=json, headers=headers)
        return FakeResp()

    monkeypatch.setattr(telemetry_service.requests, "post", fake_post)
    Settings.set("telemetry.last_sent", 0)

    telemetry_service._send_if_due()

    assert captured["url"] == "https://aptabase.invalid/api/v0/events"
    assert captured["headers"]["App-Key"] == "A-SH-0000000000"
    assert isinstance(captured["body"], list) and len(captured["body"]) == 1
    assert Settings.get("telemetry.last_sent") > 0


def test_cadence_guard_skips_within_a_day(monkeypatch):
    import time

    calls = []
    monkeypatch.setattr(telemetry_service.requests, "post", lambda *a, **k: calls.append(a))
    Settings.set("telemetry.last_sent", int(time.time()))  # sent just now
    telemetry_service._send_if_due()
    assert calls == []


def test_settings_api_opt_in_mints_id(client):
    Settings.set("telemetry.install_id", "")
    resp = client.post(
        "/api/v2/settings/",
        data=json.dumps({"telemetry_enabled": True}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert Settings.get("telemetry.enabled") is True
    assert Settings.get("telemetry.install_id")


def test_settings_api_rejects_bad_host(client):
    resp = client.post(
        "/api/v2/settings/",
        data=json.dumps({"telemetry_host": "aptabase.invalid"}),
        content_type="application/json",
    )
    assert resp.status_code == 400


def test_plugins_shape_lists_enabled_ids(monkeypatch):
    monkeypatch.setattr(plugins, "list_providers", lambda: [])
    shape = telemetry_service._config_shape()
    assert shape["plugins_enabled"] == ""
    assert shape["playout_kind"] == "none"


def test_installer_opt_in_enables_and_mints_id(client, setup_incomplete):
    Settings.set("telemetry.enabled", False)
    Settings.set("telemetry.install_id", "")
    resp = client.post(
        "/api/v2/installer/complete",
        data=json.dumps({"cinema_name": "The Roxy", "telemetry_enabled": True}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert Settings.get("telemetry.enabled") is True
    assert Settings.get("telemetry.install_id")


def test_installer_defaults_telemetry_off(client, setup_incomplete):
    Settings.set("telemetry.enabled", False)
    resp = client.post(
        "/api/v2/installer/complete",
        data=json.dumps({"cinema_name": "The Roxy"}),
        content_type="application/json",
    )
    assert resp.status_code == 200
    assert Settings.get("telemetry.enabled") is False
    assert not Settings.get("telemetry.install_id")
