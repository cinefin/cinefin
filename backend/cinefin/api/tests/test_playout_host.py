"""Playout hosts: pairing (API and command), the host list, per-host agent proxies and the active host."""

from importlib import import_module
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.apps import apps as live_apps
from django.core.management import call_command

from cinefin.api.models import Bumper, PlayoutHost, Settings
from cinefin.api.services.playout_agent_service import PlayoutAgentService

pytestmark = pytest.mark.django_db

HOSTS = "/api/v2/playout/hosts"
PAIR = f"{HOSTS}/pair"
AGENT_REQUEST = "cinefin.api.services.playout_agent_service.requests.request"
UNLOAD = "cinefin.api.ninja_views.playout_ninja.mpv_service.unload_for_host_switch"


def _resp(status=200, payload=None):
    payload = {} if payload is None else payload
    resp = MagicMock(status_code=status, ok=200 <= status < 300, text=str(payload))
    resp.json.return_value = payload
    return resp


def _answer(status, payload):
    return patch(AGENT_REQUEST, return_value=_resp(status, payload))


def _host(**kw):
    kw.setdefault("name", "Booth")
    kw.setdefault("base_url", "http://booth:8089")
    return PlayoutHost.objects.create(token="t", **kw)


def _post(client, url, data=None):
    return client.post(url, data=data or {}, content_type="application/json")


class TestPairing:
    def _pair(self, client, answer, status=200, **body):
        body = {"base_url": "booth", "code": "482 913", **body}
        reply = _resp(status, {"protocol": 2, **answer})
        with patch("cinefin.api.services.playout_agent_service.requests.post", return_value=reply) as post:
            return _post(client, PAIR, body), post

    def test_pair_adds_and_activates_the_first_player(self, client, standby_pushes):
        PlayoutHost.objects.all().delete()
        r, post = self._pair(client, {"token": "sekret", "id": "abc", "name": "Booth", "agent_version": "1.0"})
        assert r.status_code == 200
        # Scheme and default port are filled in; the code is sent without spaces.
        assert post.call_args.args[0] == "http://booth:8089/pair"
        assert post.call_args.kwargs["json"] == {"code": "482913"}
        host = r.json()["data"]
        assert host["is_active"] and host["has_token"] and host["agent_id"] == "abc" and "token" not in host
        assert host["needs_update"] is False and host["needs_pairing_again"] is False
        saved = PlayoutHost.objects.get(pk=host["id"])
        assert saved.token == "sekret" and saved.protocol == 2
        assert standby_pushes == [[host["id"]]]

    @pytest.mark.parametrize("answer", [{"protocol": None}, {"protocol": 1}, {"protocol": "2"}])
    def test_pair_refuses_a_player_without_standby(self, client, answer):
        PlayoutHost.objects.all().delete()
        r, _ = self._pair(client, {"token": "t", "id": "old", **answer})
        assert r.status_code == 422 and r.json()["error_code"] == "AGENT_OUTDATED"
        assert "needs updating to the latest cinefin-playout release" in r.json()["error"]
        assert not PlayoutHost.objects.exists()

    def test_repairing_a_known_player_updates_it(self, client):
        PlayoutHost.objects.all().delete()
        known = PlayoutHost.objects.create(name="Booth", base_url="http://old:8089", agent_id="abc", token="old")
        r, _ = self._pair(client, {"token": "new", "id": "abc", "name": "renamed"}, base_url="http://new:8089")
        assert r.status_code == 200
        known.refresh_from_db()
        assert (known.token, known.base_url, known.name) == ("new", "http://new:8089", "Booth")
        assert PlayoutHost.objects.count() == 1

    @pytest.mark.parametrize(
        ("status", "code", "http"),
        [(403, "PAIR_WRONG_CODE", 400), (429, "PAIR_RATE_LIMITED", 400), (409, "PAIR_ALREADY_PAIRED", 409)],
    )
    def test_pair_errors_reach_the_user(self, client, status, code, http):
        r, _ = self._pair(client, {}, status=status)
        assert (r.status_code, r.json()["error_code"]) == (http, code)

    def test_a_code_and_pairing_are_required(self, client):
        assert _post(client, PAIR, {"base_url": "booth", "code": "12"}).status_code == 400
        r = _post(client, HOSTS, {"name": "Booth", "base_url": "http://booth:8089"})
        assert (r.status_code, r.json()["error_code"]) == (400, "PAIR_REQUIRED")


class TestPairCommand:
    def _pair(self, answer, **kwargs):
        out = StringIO()
        with patch.object(PlayoutAgentService, "pair", return_value=answer) as agent_pair:
            call_command("pair_playout_host", stdout=out, **kwargs)
        agent_pair.assert_called_once_with(kwargs["url"].strip().rstrip("/"), kwargs["code"])
        return out.getvalue()

    def test_fresh_install_has_no_placeholder_host(self):
        # 0019 seeds one; 0048 drops it again while it is still untouched.
        assert PlayoutHost.objects.count() == 0

    def test_adopts_a_host_at_the_same_url_keeping_its_name(self):
        PlayoutHost.objects.create(name="Playout host", base_url="http://127.0.0.1:8089")
        out = self._pair({"token": "tok-1", "id": "a1", "name": "Box"}, url="http://127.0.0.1:8089/", code="123456")
        host = PlayoutHost.objects.get()
        assert (host.token, host.agent_id, host.name) == ("tok-1", "a1", "Playout host")
        assert host.enabled and host.is_active and "Re-paired" in out


class TestHostList:
    def test_flags_players_to_pair_again_or_update(self, client):
        PlayoutHost.objects.all().delete()
        PlayoutHost.objects.create(name="Legacy", token="t", protocol=2)
        PlayoutHost.objects.create(name="Old", token="t", agent_id="a", protocol=1)
        PlayoutHost.objects.create(name="Current", token="t", agent_id="b", protocol=2)
        PlayoutHost.objects.create(name="Local", kind=PlayoutHost.KIND_LOCAL_SOCKET, socket_path="/s", token="")
        flags = {h["name"]: (h["needs_pairing_again"], h["needs_update"]) for h in client.get(HOSTS).json()["data"]}
        assert flags == {
            "Legacy": (True, False),
            "Old": (False, True),
            "Current": (False, False),
            "Local": (False, False),
        }

    def test_refresh_records_liveness_version_and_protocol(self, client):
        host = _host(protocol=2)
        reply = _resp(200, {"version": "0.9", "os": "linux", "arch": "amd64"})
        with patch("cinefin.api.services.playout_host_service.requests.get", return_value=reply) as get:
            r = client.post(f"{HOSTS}/{host.id}/refresh")
        assert get.call_args.kwargs["headers"] == {"Cinefin-Protocol": "2", "Authorization": "Bearer t"}
        assert r.json()["data"]["needs_update"] is True
        host.refresh_from_db()
        assert (host.protocol, host.agent_version, host.os, host.arch) == (0, "0.9", "linux", "amd64")
        assert host.last_seen_at is not None

    def test_delete_unpairs_the_player_even_when_it_is_off(self, client):
        PlayoutHost.objects.all().delete()
        a = _host(name="A", base_url="http://a:8089", is_active=True)
        b = _host(name="B", base_url="http://b:8089")
        with patch(AGENT_REQUEST, return_value=_resp()) as req, patch(UNLOAD) as unload:
            assert client.delete(f"{HOSTS}/{a.id}").status_code == 200
        assert req.call_args.args[:2] == ("POST", "http://a:8089/unpair")
        assert req.call_args.kwargs["headers"] == {"Cinefin-Protocol": "2", "Authorization": "Bearer t"}
        unload.assert_called_once()
        assert PlayoutHost.objects.get(pk=b.id).is_active is True
        with patch(AGENT_REQUEST, side_effect=requests.ConnectionError("refused")):
            assert client.delete(f"{HOSTS}/{b.id}").status_code == 200
        assert not PlayoutHost.objects.exists()

    def test_rename_and_show_status_push_the_spec_and_keep_the_token(self, client, standby_pushes):
        host = _host()
        url = f"{HOSTS}/{host.id}"
        client.patch(url, data={"enabled": True}, content_type="application/json")
        assert standby_pushes == []  # nothing in the spec changed
        client.patch(url, data={"name": "Screen 1"}, content_type="application/json")
        r = client.patch(url, data={"show_status": False}, content_type="application/json")
        assert r.json()["data"]["show_status"] is False
        assert standby_pushes == [[host.id], [host.id]]
        host.refresh_from_db()
        assert (host.name, host.token) == ("Screen 1", "t")

    def test_activating_another_host_unloads_and_pushes_its_spec(self, client, standby_pushes):
        PlayoutHost.objects.all().delete()
        _host(name="A", base_url="http://a:8089", is_active=True)
        b = _host(name="B", base_url="http://b:8089")
        with patch(UNLOAD) as unload:
            assert client.post(f"{HOSTS}/{b.id}/activate").status_code == 200
        unload.assert_called_once()
        assert PlayoutHost.get_active() == b
        assert PlayoutHost.objects.filter(is_active=True).count() == 1
        assert standby_pushes == [[b.id]]


class TestAgentService:
    def test_standby_calls_address_the_host(self):
        host = _host(is_active=True)
        with patch(AGENT_REQUEST, return_value=_resp(200, {"on_standby": True})) as rq:
            assert PlayoutAgentService.put_standby(host, {"ident": {}})["on_standby"] is True
            assert rq.call_args.args[:2] == ("PUT", "http://booth:8089/standby")
            assert rq.call_args.kwargs["json"] == {"ident": {}}
            PlayoutAgentService.enter_standby(host)
            assert rq.call_args.args[:2] == ("POST", "http://booth:8089/standby")
        assert rq.call_args.kwargs["headers"]["Authorization"] == "Bearer t"

    @pytest.mark.parametrize(
        ("kind", "expected"),
        [
            (PlayoutHost.KIND_AGENT, ("ws", "ws://booth:8089/ws/control", "t")),
            (PlayoutHost.KIND_LOCAL_SOCKET, ("socket", "/tmp/mpvsocket", None)),
        ],
    )
    def test_the_active_host_picks_the_transport(self, kind, expected):
        from cinefin.api.mpv_controller import _transport_config

        _host(kind=kind, socket_path="/tmp/mpvsocket", is_active=True)
        assert _transport_config() == expected


CONFIG = {
    "autostart": True,
    "graphics": {"mode": "drm", "vo": "gpu-next", "drm_connector": "HDMI-A-1", "fullscreen": True},
    "audio": {"device": "alsa/hdmi:CARD=NVidia,DEV=0", "channels": "5.1", "spdif_passthrough": ["ac3", "dts"]},
}


class TestHostProxies:
    def test_config_reads_typed_with_defaults(self, client):
        host = _host()
        with _answer(200, {"graphics": {"mode": "drm", "drm_connector": "HDMI-A-1"}}):
            data = client.get(f"{HOSTS}/{host.id}/config").json()["data"]
        assert data["graphics"]["drm_connector"] == "HDMI-A-1" and data["graphics"]["vo"] == "gpu-next"
        assert data["audio"]["channels"] == "auto" and data["audio"]["max_volume"] == 130

    def test_config_put_goes_to_that_host_and_passes_refusals_through(self, client):
        host = _host(base_url="http://lounge:8089")
        url = f"{HOSTS}/{host.id}/config"
        with _answer(200, {"restart_required": True}) as rq:
            body = client.put(url, data=CONFIG, content_type="application/json").json()
        assert body["data"]["restart_required"] is True
        assert rq.call_args.args[:2] == ("PUT", "http://lounge:8089/hostconfig")
        assert rq.call_args.kwargs["json"]["graphics"]["drm_connector"] == "HDMI-A-1"
        with _answer(400, {"error": "graphics.drm_connector is required in drm mode"}):
            r = client.put(url, data=CONFIG, content_type="application/json")
        assert (r.status_code, r.json()["error"]) == (422, "graphics.drm_connector is required in drm mode")

    def test_an_android_players_settings_and_output_survive_the_round_trip(self, client):
        host = _host()
        android = {"graphics": {"mode": "android", "display_mode": "3840x2160@23.976", "keep_awake": False}}
        with _answer(200, android):
            g = client.get(f"{HOSTS}/{host.id}/config").json()["data"]["graphics"]
        assert (g["mode"], g["display_mode"], g["keep_awake"], g["tunneling"]) == (
            "android",
            "3840x2160@23.976",
            False,
            False,
        )
        with _answer(200, {"restart_required": False}) as rq:
            client.put(f"{HOSTS}/{host.id}/config", data=android, content_type="application/json")
        sent = rq.call_args.kwargs["json"]["graphics"]
        assert (sent["display_mode"], sent["keep_awake"]) == ("3840x2160@23.976", False)
        report = {"android": {"passthrough": ["ac3", "truehd"], "hdr": ["HDR10"], "modes": [{"id": 1, "hz": 23.976}]}}
        with _answer(200, report):
            hw = client.get(f"{HOSTS}/{host.id}/hardware").json()["data"]
        assert hw["android"]["passthrough"] == ["ac3", "truehd"] and hw["android"]["modes"][0]["hz"] == 23.976
        with _answer(200, {}):
            assert client.get(f"{HOSTS}/{host.id}/hardware").json()["data"]["android"] is None

    @pytest.mark.parametrize(
        ("path", "body", "agent_path", "answer"),
        [
            ("testcard", {"on": True}, "/testcard", {"on": True, "off_in_s": 600}),
            ("testsound", None, "/testsound", {"playing": True, "duration_ms": 3000, "sequence": []}),
            ("restart", None, "/mpv/restart", {"ok": True}),
        ],
    )
    def test_proxies_go_to_that_host(self, client, path, body, agent_path, answer):
        _host(is_active=True)
        lounge = _host(name="Lounge", base_url="http://lounge:8089")
        with _answer(200, answer) as rq:
            r = _post(client, f"{HOSTS}/{lounge.id}/{path}", body)
        assert r.status_code == 200
        assert rq.call_args.args[:2] == ("POST", f"http://lounge:8089{agent_path}")
        if body:
            assert rq.call_args.kwargs["json"] == body

    @pytest.mark.parametrize(
        ("status", "http", "code", "error"),
        [
            (409, 409, "AGENT_BUSY", "A test sound is already playing"),
            (401, 422, "AGENT_AUTH_FAILED", None),
            (503, 422, "AGENT_ERROR", None),
        ],
    )
    def test_agent_errors_reach_the_user(self, client, status, http, code, error):
        host = _host()
        with _answer(status, {"error": "a test sound is already playing"}):
            r = client.post(f"{HOSTS}/{host.id}/testsound")
        assert (r.status_code, r.json()["error_code"]) == (http, code)
        if error:
            assert r.json()["error"] == error

    @pytest.mark.parametrize("path", ["testcard", "testsound", "config"])
    def test_unknown_or_socket_hosts(self, client, path):
        socket = _host(kind=PlayoutHost.KIND_LOCAL_SOCKET, base_url="", socket_path="/tmp/mpv")
        call = client.get if path == "config" else (lambda url: _post(client, url, {"on": True}))
        assert call(f"{HOSTS}/999999/{path}").status_code == 404
        r = call(f"{HOSTS}/{socket.id}/{path}")
        assert r.status_code == 422 and "agent" in r.json()["error"].lower()


@pytest.mark.parametrize(("ok", "status"), [(True, 200), (False, 422)])
def test_reset_goes_to_standby(client, ok, status):
    with patch("cinefin.api.ninja_views.playout_ninja.mpv_service.standby", return_value=ok) as standby:
        assert client.post("/api/v2/playout/reset").status_code == status
    standby.assert_called_once()


def test_seed_migration_takes_the_configured_agent():
    Settings.set("playout.agent.url", "http://configured:8089")
    Settings.set("playout.agent.token", "cfg-token")
    Settings.set("playout.agent.enabled", True)
    PlayoutHost.objects.all().delete()
    import_module("cinefin.api.migrations.0019_seed_playout_host").seed_playout_host(live_apps, None)
    host = PlayoutHost.objects.get()
    assert (host.base_url, host.token, host.enabled, host.is_active) == (
        "http://configured:8089",
        "cfg-token",
        True,
        True,
    )


def test_streaming_base_url():
    from cinefin.api.utils.urls import cinefin_base_url

    Settings.set("playout.server_url", "")
    assert cinefin_base_url()
    Settings.set("playout.server_url", "http://booth.local:9000/")
    assert cinefin_base_url() == "http://booth.local:9000"
    bumper = Bumper.objects.create(title="Ident", file_path="/x.mp4")
    assert bumper.get_stream_url()["stream_url"].startswith("http://booth.local:9000/stream/bumper/")
