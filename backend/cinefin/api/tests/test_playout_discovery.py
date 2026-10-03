from unittest.mock import MagicMock, patch

import pytest
import requests

from cinefin.api.services import playout_discovery
from cinefin.api.services.playout_discovery import Announcement

pytestmark = pytest.mark.django_db

BOOTH = "http://10.0.0.5:8089"


def _resolve(announcements, health):
    """resolve() with /health answered from ``health`` (base URL -> payload); other addresses refuse."""

    def get(url, timeout):
        base = url.removesuffix("/health")
        if base not in health:
            raise requests.ConnectionError("refused")
        return MagicMock(json=lambda: health[base])

    with patch.object(playout_discovery.requests, "get", side_effect=get):
        return playout_discovery.resolve(announcements)


def test_confirms_each_player_on_the_address_that_answers():
    ann = Announcement({"id": "a1", "name": "booth"}, ["172.17.0.1", "10.0.0.5"], 8089)
    [player] = _resolve([ann], {BOOTH: {"id": "a1", "name": "booth", "version": "1.0", "paired": False}})
    assert (player.base_url, player.id, player.name, player.version, player.paired, player.host_id) == (
        BOOTH,
        "a1",
        "booth",
        "1.0",
        False,
        None,
    )


def test_discover_endpoint_never_fails_without_multicast(client):
    with patch.object(playout_discovery, "browse", side_effect=OSError("no multicast")):
        r = client.get("/api/v2/playout/discover")
    assert r.status_code == 200 and r.json()["data"] == []
