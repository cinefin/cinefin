from unittest.mock import patch

import pytest
import requests

from cinefin.api.models import PlayoutHost, Settings
from cinefin.api.services.playout_agent_service import PlayoutAgentService

pytestmark = pytest.mark.django_db


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload if payload is not None else {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


class TestResolve:
    def test_resolves_the_active_host(self):
        PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089/", token="ht", is_active=True)
        base, token = PlayoutAgentService.resolve()
        assert base == "http://booth:8089"
        assert token == "ht"
        assert PlayoutAgentService.is_configured() is True


class TestProxyMethods:
    def _active(self):
        return PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", token="t", is_active=True)

    def test_get_hostconfig_proxies(self):
        self._active()
        with patch("cinefin.api.services.playout_agent_service.requests.request") as rq:
            rq.return_value = _Resp(200, {"graphics": {"mode": "drm"}, "audio": {"device": "alsa"}})
            out = PlayoutAgentService.get_hostconfig()
        assert out["graphics"]["mode"] == "drm"
        method, url = rq.call_args[0][0], rq.call_args[0][1]
        assert method == "GET" and url == "http://booth:8089/hostconfig"
        assert rq.call_args.kwargs["headers"]["Authorization"] == "Bearer t"

    def test_standby_calls_address_the_host(self):
        host = self._active()
        with patch("cinefin.api.services.playout_agent_service.requests.request") as rq:
            rq.return_value = _Resp(200, {"on_standby": True})
            assert PlayoutAgentService.put_standby(host, {"ident": {}})["on_standby"] is True
            assert rq.call_args.args[:2] == ("PUT", "http://booth:8089/standby")
            assert rq.call_args.kwargs["json"] == {"ident": {}}
            PlayoutAgentService.enter_standby(host)
            assert rq.call_args.args[:2] == ("POST", "http://booth:8089/standby")
        assert rq.call_args.kwargs["headers"]["Authorization"] == "Bearer t"

    def test_unconfigured_raises(self):
        from cinefin.api.exceptions import UnprocessableEntityError

        PlayoutHost.objects.all().delete()
        with pytest.raises(UnprocessableEntityError):
            PlayoutAgentService.get_hostconfig()


class TestHostEndpoints:
    PAIR = "/api/v2/playout/hosts/pair"

    def _pair(self, client, answer, **body):
        body = {"base_url": "booth", "code": "482 913", **body}
        answer = {"protocol": 2, **answer}
        with patch("cinefin.api.services.playout_agent_service.requests.post", return_value=_Resp(200, answer)) as post:
            r = client.post(self.PAIR, data=body, content_type="application/json")
        return r, post

    def test_pair_adds_and_activates_the_first_player(self, client, standby_pushes):
        PlayoutHost.objects.all().delete()
        r, post = self._pair(client, {"token": "sekret", "id": "abc", "name": "Booth", "agent_version": "1.0"})
        assert r.status_code == 200
        # Scheme and default port are filled in; the code is sent without spaces.
        post.assert_called_once()
        assert post.call_args.args[0] == "http://booth:8089/pair"
        assert post.call_args.kwargs["json"] == {"code": "482913"}
        host = r.json()["data"]
        assert host["is_active"] is True and host["has_token"] is True and host["agent_id"] == "abc"
        assert host["name"] == "Booth" and "token" not in host
        assert host["needs_update"] is False and host["needs_pairing_again"] is False
        saved = PlayoutHost.objects.get(pk=host["id"])
        assert saved.token == "sekret" and saved.protocol == 2
        assert standby_pushes == [[host["id"]]]  # the new player gets its standby spec

    @pytest.mark.parametrize("answer", [{}, {"protocol": 1}, {"protocol": "2"}])
    def test_pair_refuses_a_player_without_standby(self, client, answer):
        PlayoutHost.objects.all().delete()
        reply = _Resp(200, {"token": "t", "id": "old", **answer})
        with patch("cinefin.api.services.playout_agent_service.requests.post", return_value=reply):
            r = client.post(self.PAIR, data={"base_url": "booth", "code": "111111"}, content_type="application/json")
        assert r.status_code == 422
        assert r.json()["error_code"] == "AGENT_OUTDATED"
        assert "needs updating to the latest cinefin-playout release" in r.json()["error"]
        assert not PlayoutHost.objects.exists()

    def test_hosts_list_flags_players_to_pair_again_or_update(self, client):
        PlayoutHost.objects.all().delete()
        PlayoutHost.objects.create(name="Legacy", token="t", protocol=2)
        PlayoutHost.objects.create(name="Old", token="t", agent_id="a", protocol=1)
        PlayoutHost.objects.create(name="Current", token="t", agent_id="b", protocol=2)
        PlayoutHost.objects.create(name="Local", kind=PlayoutHost.KIND_LOCAL_SOCKET, socket_path="/s", token="")
        hosts = {h["name"]: h for h in client.get("/api/v2/playout/hosts").json()["data"]}
        flags = {n: (h["needs_pairing_again"], h["needs_update"]) for n, h in hosts.items()}
        assert flags == {
            "Legacy": (True, False),
            "Old": (False, True),
            "Current": (False, False),
            "Local": (False, False),
        }

    def test_refresh_records_the_protocol(self, client):
        host = PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", token="t", protocol=2)
        with patch(
            "cinefin.api.services.playout_host_service.requests.get", return_value=_Resp(200, {"version": "0.9"})
        ):
            r = client.post(f"/api/v2/playout/hosts/{host.id}/refresh")
        assert r.json()["data"]["needs_update"] is True
        host.refresh_from_db()
        assert host.protocol == 0

    def test_repairing_a_known_player_updates_it(self, client):
        PlayoutHost.objects.all().delete()
        known = PlayoutHost.objects.create(name="Booth", base_url="http://old:8089", agent_id="abc", token="old")
        r, _ = self._pair(client, {"token": "new", "id": "abc", "name": "renamed"}, base_url="http://new:8089")
        assert r.status_code == 200
        known.refresh_from_db()
        assert (known.token, known.base_url, known.name) == ("new", "http://new:8089", "Booth")
        assert PlayoutHost.objects.count() == 1

    @pytest.mark.parametrize(
        ("status", "code"),
        [(403, "PAIR_WRONG_CODE"), (429, "PAIR_RATE_LIMITED"), (409, "PAIR_ALREADY_PAIRED")],
    )
    def test_pair_errors_reach_the_user(self, client, status, code):
        with patch("cinefin.api.services.playout_agent_service.requests.post", return_value=_Resp(status, {})):
            r = client.post(self.PAIR, data={"base_url": "booth", "code": "111111"}, content_type="application/json")
        assert r.json()["error_code"] == code
        assert r.status_code == (409 if status == 409 else 400)

    def test_code_must_be_six_digits(self, client):
        r = client.post(self.PAIR, data={"base_url": "booth", "code": "12"}, content_type="application/json")
        assert r.status_code == 400

    def test_agent_hosts_cannot_be_created_without_pairing(self, client):
        r = client.post(
            "/api/v2/playout/hosts",
            data={"name": "Booth", "base_url": "http://booth:8089"},
            content_type="application/json",
        )
        assert r.status_code == 400
        assert r.json()["error_code"] == "PAIR_REQUIRED"

    def test_delete_unpairs_the_player(self, client):
        PlayoutHost.objects.all().delete()
        a = PlayoutHost.objects.create(name="A", base_url="http://a:8089", token="ta", is_active=True)
        b = PlayoutHost.objects.create(name="B", base_url="http://b:8089", token="tb")
        with (
            patch("cinefin.api.services.playout_agent_service.requests.request", return_value=_Resp(200)) as req,
            patch("cinefin.api.ninja_views.playout_ninja.mpv_service.unload_for_host_switch") as unload,
        ):
            assert client.delete(f"/api/v2/playout/hosts/{a.id}").status_code == 200
        req.assert_called_once()
        assert req.call_args.args[:2] == ("POST", "http://a:8089/unpair")
        assert req.call_args.kwargs["headers"] == {"Authorization": "Bearer ta"}
        unload.assert_called_once()
        assert PlayoutHost.objects.get(pk=b.id).is_active is True

    def test_delete_works_when_the_player_is_off(self, client):
        host = PlayoutHost.objects.create(name="Off", base_url="http://off:8089", token="t")
        with patch(
            "cinefin.api.services.playout_agent_service.requests.request",
            side_effect=requests.ConnectionError("refused"),
        ):
            assert client.delete(f"/api/v2/playout/hosts/{host.id}").status_code == 200
        assert not PlayoutHost.objects.filter(pk=host.id).exists()

    def test_update_keeps_token(self, client):
        host = PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", token="keep", is_active=True)
        client.patch(f"/api/v2/playout/hosts/{host.id}", data={"name": "Renamed"}, content_type="application/json")
        host.refresh_from_db()
        assert host.name == "Renamed" and host.token == "keep"

    def test_rename_and_show_status_push_the_spec(self, client, standby_pushes):
        host = PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", token="t")
        url = f"/api/v2/playout/hosts/{host.id}"
        client.patch(url, data={"enabled": True}, content_type="application/json")
        assert standby_pushes == []  # nothing in the spec changed
        client.patch(url, data={"name": "Screen 1"}, content_type="application/json")
        r = client.patch(url, data={"show_status": False}, content_type="application/json")
        assert r.json()["data"]["show_status"] is False
        assert standby_pushes == [[host.id], [host.id]]


class TestSubtitleSettings:
    def test_roundtrip_and_live_apply(self, client):
        with patch("cinefin.api.mpv_service.mpv_service.apply_subtitle_style") as apply_:
            r = client.post(
                "/api/v2/settings/",
                data={
                    "subtitle_font_size": 60,
                    "subtitle_color": "#ffee00",
                    "subtitle_border_style": "opaque-box",
                    "subtitle_position": 90,
                    "subtitle_bold": True,
                },
                content_type="application/json",
            )
        assert r.status_code == 200
        assert Settings.get("playout.subtitles.font_size") == 60
        assert Settings.get("playout.subtitles.border_style") == "opaque-box"
        apply_.assert_called_once()

        s = client.get("/api/v2/settings/").json()["data"]["settings"]
        assert s["subtitle_font_size"] == 60
        assert s["subtitle_color"] == "#ffee00"


class TestEnsureMpvRunning:
    def test_starts_when_not_running(self):
        PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", is_active=True)
        calls = []

        def fake(method, url, **kw):
            calls.append((method, url))
            if url.endswith("/status"):
                return _Resp(200, {"mpv": {"running": False, "socket_responding": False}})
            return _Resp(200, {"ok": True})

        with patch("cinefin.api.services.playout_agent_service.requests.request", side_effect=fake):
            assert PlayoutAgentService.ensure_mpv_running() is True
        assert ("POST", "http://booth:8089/mpv/start") in calls
