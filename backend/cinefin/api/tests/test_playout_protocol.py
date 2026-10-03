"""The two-way protocol check with the playout agent: the header Cinefin sends, the range the
agent serves, and which side the user is told to update."""

from unittest.mock import MagicMock, patch

import pytest

from cinefin.api.exceptions import UnprocessableEntityError
from cinefin.api.models import PlayoutHost
from cinefin.api.services.playout_agent_service import (
    COMPATIBLE,
    PROTOCOL,
    UPDATE_CINEFIN,
    UPDATE_PLAYER,
    PlayoutAgentService,
    compatibility,
    headers,
)

pytestmark = pytest.mark.django_db

HOSTS = "/api/v2/playout/hosts"
AGENT_REQUEST = "cinefin.api.services.playout_agent_service.requests.request"
AGENT_POST = "cinefin.api.services.playout_agent_service.requests.post"


def _resp(status=200, payload=None):
    payload = {} if payload is None else payload
    resp = MagicMock(status_code=status, ok=200 <= status < 300, text=str(payload))
    resp.json.return_value = payload
    return resp


def _host(**kw):
    kw.setdefault("name", "Booth")
    kw.setdefault("base_url", "http://booth:8089")
    kw.setdefault("agent_id", "abc")
    kw.setdefault("is_active", True)
    return PlayoutHost.objects.create(token="t", **kw)


@pytest.mark.parametrize(
    ("answer", "verdict"),
    [
        ({"protocol": 2, "min_protocol": 2}, COMPATIBLE),
        ({"protocol": 3, "min_protocol": 2}, COMPATIBLE),
        ({"protocol": 2}, COMPATIBLE),  # a player from before the range: no lower bound
        ({"protocol": 1}, UPDATE_PLAYER),
        ({}, UPDATE_PLAYER),
        ({"protocol": True}, UPDATE_PLAYER),
        ({"protocol": 3, "min_protocol": 3}, UPDATE_CINEFIN),
    ],
)
def test_compatibility(answer, verdict):
    assert compatibility(answer) == verdict


def test_every_request_names_the_protocol():
    assert headers() == {"Cinefin-Protocol": str(PROTOCOL)}
    assert headers("t") == {"Cinefin-Protocol": str(PROTOCOL), "Authorization": "Bearer t"}
    host = _host()
    with patch(AGENT_REQUEST, return_value=_resp(200, {})) as req:
        PlayoutAgentService.host_status(host)
    assert req.call_args.kwargs["headers"]["Cinefin-Protocol"] == str(PROTOCOL)


def test_a_player_that_needs_a_newer_cinefin_says_so():
    host = _host()
    body = {"error": "This player needs Cinefin v0.4.0 or later.", "protocol": 3, "min_protocol": 3}
    with patch(AGENT_REQUEST, return_value=_resp(426, body)):
        with pytest.raises(UnprocessableEntityError) as e:
            PlayoutAgentService.host_status(host)
    assert e.value.error_code == "AGENT_NEEDS_NEWER_CINEFIN"
    assert "Cinefin v0.4.0" in e.value.message


def test_a_player_that_refuses_this_cinefin_as_too_new_asks_for_an_update():
    host = _host()
    body = {"error": "This Cinefin needs a newer player.", "protocol": 1, "min_protocol": 1}
    with patch(AGENT_REQUEST, return_value=_resp(426, body)):
        with pytest.raises(UnprocessableEntityError) as e:
            PlayoutAgentService.host_status(host)
    assert e.value.error_code == "AGENT_OUTDATED"


def test_pairing_a_player_newer_than_cinefin_is_refused(client):
    PlayoutHost.objects.all().delete()
    answer = {"token": "t", "id": "new", "protocol": 3, "min_protocol": 3}
    with patch(AGENT_POST, return_value=_resp(200, answer)):
        r = client.post(f"{HOSTS}/pair", data={"base_url": "booth", "code": "482913"}, content_type="application/json")
    assert r.status_code == 422 and r.json()["error_code"] == "AGENT_NEEDS_NEWER_CINEFIN"
    assert not PlayoutHost.objects.exists()


def test_pairing_records_the_range(client):
    PlayoutHost.objects.all().delete()
    answer = {"token": "t", "id": "abc", "protocol": 2, "min_protocol": 2}
    with patch(AGENT_POST, return_value=_resp(200, answer)) as post:
        r = client.post(f"{HOSTS}/pair", data={"base_url": "booth", "code": "482913"}, content_type="application/json")
    assert r.status_code == 200
    assert post.call_args.kwargs["headers"] == {"Cinefin-Protocol": str(PROTOCOL)}
    host = PlayoutHost.objects.get()
    assert (host.protocol, host.min_protocol) == (2, 2)


def test_host_list_flags_a_player_newer_than_cinefin(client):
    PlayoutHost.objects.all().delete()
    _host(name="Newer", protocol=3, min_protocol=3)
    _host(name="Current", agent_id="def", protocol=2, min_protocol=2, is_active=False)
    flags = {h["name"]: (h["needs_update"], h["needs_cinefin_update"]) for h in client.get(HOSTS).json()["data"]}
    assert flags == {"Newer": (False, True), "Current": (False, False)}


def test_a_failed_action_shows_the_agents_message(client):
    _host()
    body = {"ok": False, "message": "mpv started but IPC socket did not appear within 15s", "status": {}}
    with patch(AGENT_REQUEST, return_value=_resp(500, body)):
        r = client.post("/api/v2/playout/agent/start")
    assert r.status_code == 422
    assert "IPC socket did not appear" in r.json()["error"]
    assert "{" not in r.json()["error"]


def test_an_updated_player_is_refreshed_from_the_status_poll(client):
    host = _host(protocol=1, agent_version="v0.1.1")
    status = {"agent_version": "v0.2.0", "mpv": {"running": True}}
    health = _resp(200, {"version": "v0.2.0", "protocol": 2, "min_protocol": 2})
    with (
        patch(AGENT_REQUEST, return_value=_resp(200, status)),
        patch("cinefin.api.services.playout_host_service.requests.get", return_value=health),
    ):
        client.get("/api/v2/playout/agent/status")
    host.refresh_from_db()
    assert (host.agent_version, host.protocol, host.min_protocol) == ("v0.2.0", 2, 2)
