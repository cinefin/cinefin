import pytest

from cinefin import version

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("channel", "version_str", "expected"),
    [
        ("edge", "v1.2.3", "edge"),  # the env override wins
        (None, "v1.2.3", "release"),
        (None, "v1.2.3-5-gabc1234", "edge"),
        (None, "dev", "dev"),
    ],
)
def test_channel(monkeypatch, channel, version_str, expected):
    if channel:
        monkeypatch.setenv("CINEFIN_CHANNEL", channel)
    else:
        monkeypatch.delenv("CINEFIN_CHANNEL", raising=False)
    monkeypatch.setenv("CINEFIN_VERSION", version_str)
    assert version.get_channel() == expected


def test_version_endpoint_returns_channel(client, monkeypatch):
    monkeypatch.setenv("CINEFIN_CHANNEL", "dev")
    body = client.get("/api/v2/version").json()
    assert set(body) >= {"version", "channel", "commit"} and body["channel"] == "dev"
