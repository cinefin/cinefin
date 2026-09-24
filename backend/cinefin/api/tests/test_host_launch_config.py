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
        "idle_media": "http://cinefin/stream/system/ident/?t=abc",
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
