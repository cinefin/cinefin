"""The always-on control link: WSMPV keepalive and redial backoff, and the
playout link keeper that connects to the active agent from startup."""

import time

import pytest

from cinefin.api import mpv_ws
from cinefin.api.mpv_service import MPVService
from cinefin.api.mpv_ws import WSMPV
from cinefin.api.services import playout_link

from .ws_stub_agent import StubAgent


def _wait(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


@pytest.fixture
def stub():
    with StubAgent() as agent:
        yield agent


@pytest.fixture
def fast_keepalive(monkeypatch):
    monkeypatch.setattr(mpv_ws, "PING_INTERVAL", 0.1)
    monkeypatch.setattr(mpv_ws, "KEEPALIVE_TIMEOUT", 0.5)
    monkeypatch.setattr(mpv_ws, "RECONNECT_DELAY", 0.05)


class TestKeepalive:
    def test_pings_keep_a_live_link(self, stub, fast_keepalive):
        player = WSMPV(stub.url)
        try:
            assert _wait(lambda: stub.pings >= 5)
            assert stub.connection_count == 1  # answered pings: never dropped
            assert player._ws is not None
        finally:
            player.terminate()

    def test_silent_agent_is_closed_and_redialled(self, stub, fast_keepalive):
        stub.answer_pings = False
        player = WSMPV(stub.url)
        try:
            # No pongs and nothing else for 0.5 s: the link is closed and redialled.
            assert _wait(lambda: stub.connection_count >= 2)
        finally:
            player.terminate()

    def test_socket_transport_has_no_keepalive(self):
        from cinefin.api.mpv_socket import SocketMPV

        assert WSMPV.keepalive is True
        assert SocketMPV.keepalive is False


class TestRedial:
    def test_reconnects_after_a_drop(self, stub, fast_keepalive):
        player = WSMPV(stub.url)
        try:
            stub.drop_client()
            assert _wait(lambda: stub.connection_count >= 2)
            stub.wait_for_client()
            assert player.command("get_property", "pause", timeout=2) is None
        finally:
            player.terminate()

    def test_backoff_doubles_up_to_the_cap(self, monkeypatch):
        monkeypatch.setattr(mpv_ws, "RECONNECT_DELAY", 0.01)
        monkeypatch.setattr(mpv_ws, "RECONNECT_MAX_DELAY", 0.04)
        agent = StubAgent()
        player = WSMPV(agent.url)
        try:
            agent.close()  # the agent goes away for good
            assert _wait(lambda: player._reconnect_delay == 0.04)
        finally:
            player.terminate()


class TestLinkKeeper:
    def test_backoff_and_periodic_check(self):
        assert playout_link.next_wait(True, 16.0) == (playout_link.CHECK_INTERVAL, playout_link.RETRY_DELAY)
        waits, delay = [], playout_link.RETRY_DELAY
        for _ in range(6):
            wait, delay = playout_link.next_wait(False, delay)
            waits.append(wait)
        assert waits == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]

    def test_not_started_under_tests(self):
        from django.apps import apps

        # ApiConfig.ready() ran at django setup; with background workers off
        # (test settings) it must not have started the keeper, and a second
        # call must not either.
        assert playout_link._thread is None
        apps.get_app_config("api")._maybe_start_background_workers()
        assert playout_link._thread is None


def _service(monkeypatch):
    service = MPVService()
    monkeypatch.setattr(service, "_restore_session", lambda: None)
    monkeypatch.setattr(service, "apply_subtitle_style", lambda: None)
    monkeypatch.setattr(service, "_persist_session", lambda: None)
    return service


@pytest.mark.django_db
class TestEnsureLink:
    def _host(self, agent, **kw):
        from cinefin.api.models import PlayoutHost

        return PlayoutHost.objects.create(
            name=kw.pop("name", "Stub"),
            base_url=f"http://127.0.0.1:{agent.port}",
            token="tok",
            is_active=True,
            **kw,
        )

    def test_connects_to_the_active_agent_and_follows_a_switch(self, monkeypatch):
        from cinefin.api.models import PlayoutHost

        PlayoutHost.objects.all().delete()
        with StubAgent() as first, StubAgent() as second:
            service = _service(monkeypatch)
            try:
                self._host(first)
                assert service.ensure_link() is True
                assert first.wait_for_client()
                controller = service.controller
                assert service.ensure_link() is True
                assert service.controller is controller  # connected: nothing to do

                self._host(second, name="Other")  # save() deactivates the first
                assert service.ensure_link() is True
                assert second.wait_for_client()
                assert service.controller is not controller
                assert service.controller.transport[1] == second.url
            finally:
                if service.controller is not None:
                    service.controller.terminate()

    def test_unreachable_agent_reports_failure(self, monkeypatch):
        import socket

        from cinefin.api.models import PlayoutHost

        PlayoutHost.objects.all().delete()
        with socket.socket() as s:  # a port nobody listens on
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        PlayoutHost.objects.create(name="Gone", base_url=f"http://127.0.0.1:{port}", token="tok", is_active=True)
        service = _service(monkeypatch)
        assert service.ensure_link() is False
        assert service.controller is None

    def test_local_socket_hosts_are_left_alone(self, monkeypatch):
        from cinefin.api.models import PlayoutHost

        PlayoutHost.objects.all().delete()
        PlayoutHost.objects.create(
            name="Local", kind=PlayoutHost.KIND_LOCAL_SOCKET, socket_path="/nonexistent.sock", is_active=True
        )
        service = _service(monkeypatch)
        assert service.ensure_link() is True
        assert service.controller is None
