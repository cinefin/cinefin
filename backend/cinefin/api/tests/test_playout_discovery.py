from unittest.mock import patch

import pytest
import requests

from cinefin.api.models import PlayoutHost
from cinefin.api.services import playout_discovery
from cinefin.api.services.playout_discovery import Announcement

pytestmark = pytest.mark.django_db


class _Health:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _fake_health(answers):
    """requests.get stub: answers maps base URL -> /health payload; others refuse."""

    def get(url, timeout):
        base = url.removesuffix("/health")
        if base not in answers:
            raise requests.ConnectionError("refused")
        return _Health(answers[base])

    return get


class TestResolve:
    def test_confirms_each_player_on_the_address_that_answers(self):
        ann = Announcement({"id": "a1", "name": "booth"}, ["172.17.0.1", "10.0.0.5"], 8089)
        answers = {"http://10.0.0.5:8089": {"id": "a1", "name": "booth", "version": "1.0", "paired": False}}
        with patch.object(playout_discovery.requests, "get", side_effect=_fake_health(answers)):
            [player] = playout_discovery.resolve([ann])
        assert player.base_url == "http://10.0.0.5:8089"
        assert (player.id, player.name, player.version, player.paired, player.host_id) == (
            "a1",
            "booth",
            "1.0",
            False,
            None,
        )

    def test_drops_stale_entries_and_duplicates(self):
        stale = Announcement({"id": "gone"}, ["10.0.0.5"], 8089)  # the address now answers with another id
        live = Announcement({"id": "a1"}, ["10.0.0.5"], 8089)
        again = Announcement({"id": "a1"}, ["10.0.0.5"], 8089)
        answers = {"http://10.0.0.5:8089": {"id": "a1", "name": "booth", "paired": True}}
        with patch.object(playout_discovery.requests, "get", side_effect=_fake_health(answers)):
            players = playout_discovery.resolve([stale, live, again])
        assert [p.id for p in players] == ["a1"]

    def test_matches_known_hosts_by_agent_id(self):
        host = PlayoutHost.objects.create(name="Booth", base_url="http://old:8089", agent_id="a1", token="t")
        ann = Announcement({"id": "a1"}, ["10.0.0.5"], 8089)
        answers = {"http://10.0.0.5:8089": {"id": "a1", "name": "booth", "paired": True}}
        with patch.object(playout_discovery.requests, "get", side_effect=_fake_health(answers)):
            [player] = playout_discovery.resolve([ann])
        assert player.host_id == host.id

    def test_ipv6_addresses_are_bracketed(self):
        assert playout_discovery.base_url_for("fe80::1", 8089) == "http://[fe80::1]:8089"


def test_discover_endpoint_never_fails_without_multicast(client):
    with patch.object(playout_discovery, "browse", side_effect=OSError("no multicast")):
        r = client.get("/api/v2/playout/discover")
    assert r.status_code == 200
    assert r.json()["data"] == []
