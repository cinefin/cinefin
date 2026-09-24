from importlib import import_module
from unittest.mock import patch

import pytest
from django.apps import apps as live_apps

from cinefin.api.models import PlayoutHost, Settings

pytestmark = pytest.mark.django_db

_seed_migration = import_module("cinefin.api.migrations.0019_seed_playout_host")


class TestSingleActiveInvariant:
    def test_setting_active_clears_others(self):
        a = PlayoutHost.objects.create(name="A", base_url="http://a:8089", is_active=True)
        b = PlayoutHost.objects.create(name="B", base_url="http://b:8089", is_active=True)
        a.refresh_from_db()
        b.refresh_from_db()
        assert b.is_active is True
        assert a.is_active is False
        assert PlayoutHost.objects.filter(is_active=True).count() == 1

    def test_get_active_returns_active(self):
        PlayoutHost.objects.create(name="A", base_url="http://a:8089", is_active=False)
        active = PlayoutHost.objects.create(name="B", base_url="http://b:8089", is_active=True)
        assert PlayoutHost.get_active() == active


class TestActiveHostResolution:
    def test_agent_host_resolves_to_ws(self):
        PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", token="host-token", is_active=True)
        from cinefin.api.mpv_controller import _transport_config

        assert _transport_config() == ("ws", "ws://booth:8089/ws/control", "host-token")

    def test_local_socket_host_resolves_to_socket(self):
        PlayoutHost.objects.create(
            name="Local", kind=PlayoutHost.KIND_LOCAL_SOCKET, socket_path="/tmp/mpvsocket", is_active=True
        )
        from cinefin.api.mpv_controller import _transport_config

        assert _transport_config() == ("socket", "/tmp/mpvsocket", None)


class _FakeResponse:
    def __init__(self, payload, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._payload


class TestPlayoutHostRefresh:
    def test_refresh_records_liveness_and_version(self):
        from cinefin.api.services.playout_host_service import PlayoutHostService

        host = PlayoutHost.objects.create(name="Booth", base_url="http://booth:8089", token="t")

        def fake_get(url, headers=None, timeout=None):
            assert headers == {"Authorization": "Bearer t"}
            return _FakeResponse({"version": "2.0", "os": "linux", "arch": "amd64"})

        with patch("cinefin.api.services.playout_host_service.requests.get", side_effect=fake_get):
            assert PlayoutHostService.refresh(host) is True

        host.refresh_from_db()
        assert host.agent_version == "2.0"
        assert host.os == "linux"
        assert host.arch == "amd64"
        assert host.last_seen_at is not None


class TestSeedingFunction:
    def test_seeds_active_host_from_configured_agent(self):
        Settings.set("playout.agent.url", "http://configured:8089")
        Settings.set("playout.agent.token", "cfg-token")
        Settings.set("playout.agent.enabled", True)
        PlayoutHost.objects.all().delete()

        _seed_migration.seed_playout_host(live_apps, None)

        host = PlayoutHost.objects.get()
        assert host.base_url == "http://configured:8089"
        assert host.token == "cfg-token"
        assert host.enabled is True
        assert host.is_active is True


class TestSwitchUnloadsProgramme:
    """Activating a different host stops whatever is on air and drops the control link."""

    ACTIVATE = "/api/v2/playout/hosts/{}/activate"

    def _patches(self):
        return (
            patch("cinefin.api.ninja_views.playout_ninja.mpv_service.unload_for_host_switch"),
            patch("cinefin.api.ninja_views.playout_ninja.playout_agent_service.resync_idle_media"),
            patch("cinefin.api.ninja_views.playout_ninja.mpv_service.show_idle"),
        )

    def test_switching_hosts_unloads(self, client):
        PlayoutHost.objects.all().delete()
        PlayoutHost.objects.create(name="A", base_url="http://a:8089", is_active=True)
        b = PlayoutHost.objects.create(name="B", base_url="http://b:8089", is_active=False)
        unload_p, resync_p, idle_p = self._patches()
        with unload_p as unload, resync_p, idle_p:
            r = client.post(self.ACTIVATE.format(b.id))
        assert r.status_code == 200
        unload.assert_called_once()
        assert PlayoutHost.objects.get(pk=b.id).is_active is True

    def test_activate_shows_idle_immediately(self, client):
        """Connecting a player loads the idle ident straight away."""
        PlayoutHost.objects.all().delete()
        PlayoutHost.objects.create(name="A", base_url="http://a:8089", is_active=True)
        b = PlayoutHost.objects.create(name="B", base_url="http://b:8089", is_active=False)
        unload_p, resync_p, idle_p = self._patches()
        with unload_p, resync_p, idle_p as show_idle:
            r = client.post(self.ACTIVATE.format(b.id))
        assert r.status_code == 200
        show_idle.assert_called_once()


class TestResetEndpoint:
    """POST /playout/reset returns the player to the idle ident."""

    RESET = "/api/v2/playout/reset"

    def test_reset_calls_mpv_reset(self, client):
        with patch("cinefin.api.ninja_views.playout_ninja.mpv_service.reset", return_value=True) as reset:
            r = client.post(self.RESET)
        assert r.status_code == 200
        reset.assert_called_once()

    def test_reset_reports_an_unreachable_player(self, client):
        with patch("cinefin.api.ninja_views.playout_ninja.mpv_service.reset", return_value=False):
            r = client.post(self.RESET)
        assert r.status_code == 422


class TestStreamingBaseUrl:
    def test_defaults_to_env_when_unset(self):
        from cinefin.api.utils.urls import cinefin_base_url

        Settings.set("playout.server_url", "")
        assert cinefin_base_url()

    def test_setting_overrides_and_trims_trailing_slash(self):
        from cinefin.api.utils.urls import cinefin_base_url

        Settings.set("playout.server_url", "http://booth.local:8000/")
        assert cinefin_base_url() == "http://booth.local:8000"

    def test_media_stream_urls_use_it(self):
        from cinefin.api.models import Bumper

        Settings.set("playout.server_url", "http://booth.local:9000")
        bumper = Bumper.objects.create(title="Ident", file_path="/x.mp4")
        assert bumper.get_stream_url()["stream_url"].startswith("http://booth.local:9000/stream/bumper/")
