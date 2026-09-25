"""Version channel derivation and the /version endpoint."""

import pytest

from cinefin import version

pytestmark = pytest.mark.django_db


def test_channel_env_override_wins(monkeypatch):
    monkeypatch.setenv("CINEFIN_CHANNEL", "edge")
    monkeypatch.setenv("CINEFIN_VERSION", "v1.2.3")  # would derive "release"
    assert version.get_channel() == "edge"


def test_channel_derives_release_from_exact_tag(monkeypatch):
    monkeypatch.delenv("CINEFIN_CHANNEL", raising=False)
    monkeypatch.setenv("CINEFIN_VERSION", "v1.2.3")
    assert version.get_channel() == "release"


def test_channel_derives_edge_from_describe(monkeypatch):
    monkeypatch.delenv("CINEFIN_CHANNEL", raising=False)
    monkeypatch.setenv("CINEFIN_VERSION", "v1.2.3-5-gabc1234")
    assert version.get_channel() == "edge"


def test_channel_derives_dev(monkeypatch):
    monkeypatch.delenv("CINEFIN_CHANNEL", raising=False)
    monkeypatch.setenv("CINEFIN_VERSION", "dev")
    assert version.get_channel() == "dev"


def test_version_info_includes_channel(monkeypatch):
    monkeypatch.setenv("CINEFIN_CHANNEL", "edge")
    assert version.get_version_info()["channel"] == "edge"


def test_version_endpoint_returns_channel(client, monkeypatch):
    monkeypatch.setenv("CINEFIN_CHANNEL", "dev")
    resp = client.get("/api/v2/version")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) >= {"version", "channel", "commit"}
    assert body["channel"] == "dev"
