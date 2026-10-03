from unittest.mock import patch

import pytest

from cinefin.api.models import PlayoutHost

pytestmark = pytest.mark.django_db

CONFIG = {
    "autostart": True,
    "graphics": {
        "mode": "drm",
        "vo": "gpu-next",
        "gpu_api": "vulkan",
        "gpu_context": "displayvk",
        "hwdec": "auto",
        "screen": 0,
        "drm_connector": "HDMI-A-1",
        "drm_mode": "3840x2160@60",
        "fullscreen": True,
        "hdr_passthrough": True,
        "osc": False,
        "display": "",
    },
    "audio": {
        "device": "alsa/hdmi:CARD=NVidia,DEV=0",
        "channels": "5.1",
        "spdif_passthrough": ["ac3", "dts"],
        "max_volume": 130,
    },
}


def _host(**kwargs):
    return PlayoutHost.objects.create(
        name=kwargs.pop("name", "Booth"),
        base_url=kwargs.pop("base_url", "http://booth:8089"),
        token="t",
        **kwargs,
    )


def _agent(method_name, value):
    return patch(f"cinefin.api.services.playout_agent_service.PlayoutAgentService.{method_name}", return_value=value)


class TestReadConfig:
    def test_returns_the_agents_config_typed(self, client):
        host = _host()
        with _agent("_request", CONFIG):
            body = client.get(f"/api/v2/playout/hosts/{host.id}/config").json()
        data = body["data"]
        assert data["graphics"]["drm_connector"] == "HDMI-A-1"
        assert data["audio"]["spdif_passthrough"] == ["ac3", "dts"]
        assert data["autostart"] is True

    def test_a_sparse_config_fills_in_defaults(self, client):
        host = _host()
        with _agent("_request", {"graphics": {"mode": "desktop"}}):
            data = client.get(f"/api/v2/playout/hosts/{host.id}/config").json()["data"]
        assert data["graphics"]["vo"] == "gpu-next"
        assert data["audio"]["channels"] == "auto"
        assert data["audio"]["max_volume"] == 130

    def test_unknown_host_is_404(self, client):
        assert client.get("/api/v2/playout/hosts/999999/config").status_code == 404

    def test_a_socket_host_has_no_agent_to_configure(self, client):
        host = _host(kind=PlayoutHost.KIND_LOCAL_SOCKET, base_url="", socket_path="/tmp/mpv")
        resp = client.get(f"/api/v2/playout/hosts/{host.id}/config")
        assert resp.status_code == 422
        assert "no agent" in resp.json()["error"]


class TestWriteConfig:
    def test_put_forwards_to_that_host_and_reports_restart(self, client):
        host = _host(base_url="http://lounge:8089")
        with patch("cinefin.api.services.playout_agent_service.requests.request") as rq:
            rq.return_value.ok = True
            rq.return_value.status_code = 200
            rq.return_value.json.return_value = {"restart_required": True}
            body = client.put(
                f"/api/v2/playout/hosts/{host.id}/config",
                data=CONFIG,
                content_type="application/json",
            ).json()

        assert body["data"]["restart_required"] is True
        method, url = rq.call_args[0][0], rq.call_args[0][1]
        assert method == "PUT" and url == "http://lounge:8089/hostconfig"
        sent = rq.call_args.kwargs["json"]
        assert sent["graphics"]["drm_connector"] == "HDMI-A-1"

    def test_the_agents_refusal_is_passed_through_verbatim(self, client):
        host = _host()
        with patch("cinefin.api.services.playout_agent_service.requests.request") as rq:
            rq.return_value.ok = False
            rq.return_value.status_code = 400
            rq.return_value.json.return_value = {"error": "graphics.drm_connector is required in drm mode"}
            resp = client.put(
                f"/api/v2/playout/hosts/{host.id}/config",
                data=CONFIG,
                content_type="application/json",
            )
        assert resp.status_code == 422
        assert resp.json()["error"] == "graphics.drm_connector is required in drm mode"


class TestHardware:
    def test_enumerates_that_host(self, client):
        host = _host()
        report = {
            "audio_devices": [{"name": "alsa/hdmi:CARD=NVidia,DEV=0", "description": "HDMI / NVidia"}],
            "drm_connectors": ["HDMI-A-1", "DP-1"],
            "screens": [{"index": 0, "name": "DP-1", "w": 3840, "h": 2160, "hz": 60.0}],
            "mpv": {"version": "mpv 0.38.0", "vo": ["gpu-next", "gpu"], "gpu_apis": ["vulkan", "opengl"]},
        }
        with _agent("_request", report):
            data = client.get(f"/api/v2/playout/hosts/{host.id}/hardware").json()["data"]
        assert data["drm_connectors"] == ["HDMI-A-1", "DP-1"]
        assert data["screens"][0]["w"] == 3840
        assert data["mpv"]["gpu_apis"] == ["vulkan", "opengl"]
        assert data["note"] == ""

    def test_a_host_with_no_mpv_answers_empty_with_a_note(self, client):
        host = _host()
        with _agent("_request", {"note": "mpv binary not found"}):
            data = client.get(f"/api/v2/playout/hosts/{host.id}/hardware").json()["data"]
        assert data["audio_devices"] == [] and data["note"] == "mpv binary not found"


def _answer(status, payload):
    """A fake agent reply for requests.request."""
    from unittest.mock import MagicMock

    resp = MagicMock(status_code=status, ok=200 <= status < 300, text=str(payload))
    resp.json.return_value = payload
    return patch("cinefin.api.services.playout_agent_service.requests.request", return_value=resp)


SEQUENCE = {
    "playing": True,
    "frequency_hz": 440,
    "duration_ms": 3000,
    "sequence": [
        {"channel": "left", "start_ms": 0, "duration_ms": 1500},
        {"channel": "right", "start_ms": 1500, "duration_ms": 1500},
    ],
}


class TestTestCardAndSound:
    def test_test_card_goes_to_that_host_with_its_token(self, client):
        _host(name="Booth", is_active=True)
        lounge = _host(name="Lounge", base_url="http://lounge:8089")
        with _answer(200, {"on": True, "off_in_s": 600}) as rq:
            r = client.post(
                f"/api/v2/playout/hosts/{lounge.id}/testcard", data={"on": True}, content_type="application/json"
            )
        assert r.status_code == 200
        assert r.json()["data"] == {"on": True, "off_in_s": 600}
        assert rq.call_args.args[:2] == ("POST", "http://lounge:8089/testcard")
        assert rq.call_args.kwargs["json"] == {"on": True}
        assert rq.call_args.kwargs["headers"]["Authorization"] == "Bearer t"

    def test_test_card_needs_on(self, client):
        host = _host()
        r = client.post(f"/api/v2/playout/hosts/{host.id}/testcard", data={}, content_type="application/json")
        assert r.status_code in (400, 422)

    def test_test_sound_returns_the_sequence(self, client):
        host = _host()
        with _answer(200, SEQUENCE) as rq:
            r = client.post(f"/api/v2/playout/hosts/{host.id}/testsound")
        assert r.status_code == 200
        data = r.json()["data"]
        assert [s["channel"] for s in data["sequence"]] == ["left", "right"]
        assert data["sequence"][1]["start_ms"] == 1500 and data["duration_ms"] == 3000
        assert rq.call_args.args[:2] == ("POST", "http://booth:8089/testsound")

    @pytest.mark.parametrize(
        "error", ["a test sound is already playing", "the test sound plays only on standby or with the test card on"]
    )
    def test_the_agents_409_passes_through(self, client, error):
        host = _host()
        with _answer(409, {"error": error}):
            r = client.post(f"/api/v2/playout/hosts/{host.id}/testsound")
        assert r.status_code == 409
        body = r.json()
        assert body["error_code"] == "AGENT_BUSY"
        assert body["error"] == error[0].upper() + error[1:]

    @pytest.mark.parametrize("path", ["testcard", "testsound"])
    def test_unknown_host_is_404(self, client, path):
        r = client.post(f"/api/v2/playout/hosts/999999/{path}", data={"on": True}, content_type="application/json")
        assert r.status_code == 404 and r.json()["error_code"] == "HOST_NOT_FOUND"

    @pytest.mark.parametrize("path", ["testcard", "testsound"])
    def test_a_socket_host_has_no_agent(self, client, path):
        host = _host(kind=PlayoutHost.KIND_LOCAL_SOCKET, base_url="", socket_path="/tmp/mpv")
        r = client.post(f"/api/v2/playout/hosts/{host.id}/{path}", data={"on": True}, content_type="application/json")
        assert r.status_code == 422 and r.json()["error_code"] == "AGENT_NOT_CONFIGURED"

    @pytest.mark.parametrize(
        ("status", "code"), [(401, "AGENT_AUTH_FAILED"), (503, "AGENT_ERROR"), (500, "AGENT_ERROR")]
    )
    def test_agent_errors_reach_the_user(self, client, status, code):
        host = _host()
        with _answer(status, {"error": "mpv not running"}):
            r = client.post(f"/api/v2/playout/hosts/{host.id}/testsound")
        assert r.status_code == 422 and r.json()["error_code"] == code

    def test_an_unreachable_player(self, client):
        import requests

        host = _host()
        with patch(
            "cinefin.api.services.playout_agent_service.requests.request",
            side_effect=requests.ConnectionError("refused"),
        ):
            r = client.post(
                f"/api/v2/playout/hosts/{host.id}/testcard", data={"on": False}, content_type="application/json"
            )
        assert r.status_code == 422 and r.json()["error_code"] == "AGENT_UNREACHABLE"

    @pytest.mark.parametrize("path", ["testcard", "testsound"])
    def test_needs_a_login_when_auth_is_on(self, path):
        from django.test import Client

        from cinefin.api.services import auth_service

        host = _host()
        auth_service.set_password("correct-horse-42", username="admin")
        auth_service.enable_auth()
        with _answer(200, SEQUENCE) as rq:
            r = Client().post(
                f"/api/v2/playout/hosts/{host.id}/{path}", data={"on": True}, content_type="application/json"
            )
        assert r.status_code == 401
        rq.assert_not_called()


class TestRestartHost:
    def test_restarts_that_host_not_the_active_one(self, client):
        _host(name="Booth", is_active=True)
        lounge = _host(name="Lounge", base_url="http://lounge:8089")
        with _answer(200, {"ok": True}) as rq:
            r = client.post(f"/api/v2/playout/hosts/{lounge.id}/restart")
        assert r.status_code == 200
        assert rq.call_args.args[:2] == ("POST", "http://lounge:8089/mpv/restart")
