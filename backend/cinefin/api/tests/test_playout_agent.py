from unittest.mock import patch

import pytest

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

    def test_put_idle_media_returns_restart_flag(self):
        self._active()
        with patch("cinefin.api.services.playout_agent_service.requests.request") as rq:
            rq.return_value = _Resp(200, {"restart_required": True})
            out = PlayoutAgentService.put_idle_media("http://cinefin/ident.mp4")
        assert out["restart_required"] is True
        method, url = rq.call_args[0][0], rq.call_args[0][1]
        assert method == "PUT" and url == "http://booth:8089/hostconfig/idle-media"
        assert rq.call_args.kwargs["json"] == {"idle_media": "http://cinefin/ident.mp4"}


class TestIdentIdleMedia:
    def _active(self):
        return PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", token="t", is_active=True)

    def _ident_bumper(self):
        from cinefin.api.models import Bumper

        bumper = Bumper.objects.create(title="Ident", file_path="/media/ident.mp4")
        Settings.set("cinema.default_ident_id", bumper.id)
        return bumper

    def test_resync_pushes_the_system_ident_when_none_is_chosen(self):
        self._active()
        Settings.set("cinema.default_ident_id", None)
        with patch("cinefin.api.services.playout_agent_service.requests.request") as rq:
            rq.return_value = _Resp(200, {})
            PlayoutAgentService.resync_idle_media()
        method, url = rq.call_args[0][0], rq.call_args[0][1]
        assert method == "PUT" and url.endswith("/hostconfig/idle-media")
        assert "/stream/system/ident/?t=" in rq.call_args.kwargs["json"]["idle_media"]
        assert set(rq.call_args.kwargs["json"].keys()) == {"idle_media"}

    def test_unconfigured_raises(self):
        from cinefin.api.exceptions import UnprocessableEntityError

        PlayoutHost.objects.all().delete()
        with pytest.raises(UnprocessableEntityError):
            PlayoutAgentService.get_hostconfig()


class TestHostEndpoints:
    def test_create_list_activate_delete(self, client):
        PlayoutHost.objects.all().delete()
        r = client.post(
            "/api/v2/playout/hosts",
            data={"name": "Booth", "base_url": "http://booth:8089", "token": "sekret"},
            content_type="application/json",
        )
        assert r.status_code == 200
        host = r.json()["data"]
        assert host["is_active"] is True
        assert host["has_token"] is True
        assert "token" not in host
        hid = host["id"]

        listed = client.get("/api/v2/playout/hosts").json()["data"]
        assert [h["id"] for h in listed] == [hid]

        r2 = client.post(
            "/api/v2/playout/hosts",
            data={"name": "Spare", "base_url": "http://spare:8089"},
            content_type="application/json",
        )
        hid2 = r2.json()["data"]["id"]
        client.post(f"/api/v2/playout/hosts/{hid2}/activate")
        assert PlayoutHost.objects.get(pk=hid2).is_active is True
        assert PlayoutHost.objects.get(pk=hid).is_active is False

        assert client.delete(f"/api/v2/playout/hosts/{hid2}").status_code == 200
        assert PlayoutHost.objects.get(pk=hid).is_active is True

    def test_update_keeps_token_unless_provided(self, client):
        host = PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", token="keep", is_active=True)
        client.patch(f"/api/v2/playout/hosts/{host.id}", data={"name": "Renamed"}, content_type="application/json")
        host.refresh_from_db()
        assert host.name == "Renamed" and host.token == "keep"


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
