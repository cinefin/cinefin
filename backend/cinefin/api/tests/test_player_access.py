"""A browsing player's access to Cinefin: its address, an API key of its own and its host id."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from cinefin.api.models import APIKey, PlayoutHost, Settings
from cinefin.api.services import player_access

pytestmark = pytest.mark.django_db

HOSTS = "/api/v2/playout/hosts"
AGENT_REQUEST = "cinefin.api.services.playout_agent_service.requests.request"
UNLOAD = "cinefin.api.ninja_views.playout_ninja.mpv_service.unload_for_host_switch"


def _resp(status=200, payload=None):
    payload = {} if payload is None else payload
    resp = MagicMock(status_code=status, ok=200 <= status < 300, text=str(payload))
    resp.json.return_value = payload
    return resp


def _host(**kw):
    kw.setdefault("name", "Lounge")
    kw.setdefault("base_url", "http://tv:8089")
    kw.setdefault("features", ["browse"])
    return PlayoutHost.objects.create(token="t", **kw)


@pytest.fixture(autouse=True)
def server_url():
    Settings.set("playout.server_url", "http://cinema.local:8000")


def _send(host, status=200, side_effect=None):
    """push_now for one host with the agent answering ``status``; returns the request mock."""
    kw = {"side_effect": side_effect} if side_effect else {"return_value": _resp(status)}
    with patch(AGENT_REQUEST, **kw) as req:
        player_access.push_now([host.id])
    host.refresh_from_db()
    return req


class TestSend:
    def test_sends_address_key_and_host_id(self):
        host = _host()
        req = _send(host)
        assert req.call_args.args[:2] == ("PUT", "http://tv:8089/cinefin")
        body = req.call_args.kwargs["json"]
        assert body["base_url"] == "http://cinema.local:8000" and body["host_id"] == host.id
        assert APIKey.resolve(body["api_key"]) == host.api_key
        assert host.api_key.name == "Player: Lounge" and host.access_url == "http://cinema.local:8000"

    def test_sent_once(self):
        host = _host()
        _send(host)
        assert not _send(host).called

    @pytest.mark.parametrize("features", [[], ["other"], None])
    def test_players_that_do_not_browse_get_nothing(self, features):
        host = _host(features=features or [])
        assert not _send(host).called
        assert not APIKey.objects.exists()

    def test_an_undelivered_key_is_dropped_and_sent_again_later(self):
        host = _host()
        _send(host, side_effect=requests.ConnectionError("off"))
        assert host.api_key is None and host.access_url == "" and not APIKey.objects.exists()
        assert _send(host).called and host.api_key is not None

    def test_a_new_address_brings_a_new_key(self):
        host = _host()
        _send(host)
        old = host.api_key_id
        Settings.set("playout.server_url", "http://cinema.lan:8000/")
        body = _send(host).call_args.kwargs["json"]
        assert body["base_url"] == "http://cinema.lan:8000"
        assert host.api_key_id != old and not APIKey.objects.filter(pk=old).exists()

    def test_a_failed_resend_keeps_the_old_key(self):
        host = _host()
        _send(host)
        old = host.api_key_id
        Settings.set("playout.server_url", "http://cinema.lan:8000")
        _send(host, status=500)
        assert host.api_key_id == old and APIKey.objects.count() == 1

    def test_a_revoked_key_stays_revoked(self):
        host = _host()
        _send(host)
        host.api_key.delete()  # revoked on the Security page
        assert not _send(host).called
        Settings.set("playout.server_url", "http://cinema.lan:8000")
        assert not _send(host).called


class TestTriggers:
    def _pair(self, client, answer):
        reply = _resp(200, {"protocol": 2, "token": "new", "id": "tv1", **answer})
        with patch("cinefin.api.services.playout_agent_service.requests.post", return_value=reply):
            return client.post(f"{HOSTS}/pair", {"base_url": "tv", "code": "123456"}, content_type="application/json")

    def test_pairing_records_features_and_starts_afresh(self, client, access_pushes):
        PlayoutHost.objects.all().delete()
        old_key, _ = APIKey.create("Player: Lounge")
        _host(agent_id="tv1", api_key=old_key, access_url="http://cinema.local:8000")
        r = self._pair(client, {"features": ["browse", 7]})
        host = PlayoutHost.objects.get(pk=r.json()["data"]["id"])
        assert host.features == ["browse"]
        assert host.api_key is None and host.access_url == "" and not APIKey.objects.exists()
        assert access_pushes == [[host.id]]

    def test_refresh_records_features_and_sends_to_an_updated_player(self, client, access_pushes):
        host = _host(features=[])
        reply = _resp(200, {"protocol": 2, "features": ["browse"]})
        with patch("cinefin.api.services.playout_host_service.requests.get", return_value=reply):
            client.post(f"{HOSTS}/{host.id}/refresh")
        host.refresh_from_db()
        assert host.features == ["browse"] and access_pushes == [[host.id]]

    def test_removing_a_host_deletes_its_key(self, client):
        key, _ = APIKey.create("Player: Lounge")
        host = _host(api_key=key, access_url="http://cinema.local:8000")
        with patch(AGENT_REQUEST, return_value=_resp()), patch(UNLOAD):
            assert client.delete(f"{HOSTS}/{host.id}").status_code == 200
        assert not APIKey.objects.exists()

    def test_a_new_streaming_url_pushes(self, client, access_pushes):
        client.post("/api/v2/settings/", {"playout_server_url": "http://c:8000"}, content_type="application/json")
        assert access_pushes == [None]
