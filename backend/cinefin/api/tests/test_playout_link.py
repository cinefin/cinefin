"""The always-on control link: WSMPV keepalive and redial backoff, and the playout link keeper."""

import time

import pytest

from cinefin.api import mpv_ws
from cinefin.api.models import PlayoutHost
from cinefin.api.mpv_service import MPVService
from cinefin.api.mpv_socket import SocketMPV
from cinefin.api.mpv_ws import WSMPV

from .ws_stub_agent import StubAgent


def _wait(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not cond():
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
    def test_pings_keep_a_live_link_and_a_silent_agent_is_redialled(self, stub, fast_keepalive):
        player = WSMPV(stub.url)
        try:
            assert _wait(lambda: stub.pings >= 5)
            assert stub.connection_count == 1 and player._ws is not None
            stub.answer_pings = False  # no pongs and nothing else for 0.5 s: closed and redialled
            assert _wait(lambda: stub.connection_count >= 2)
        finally:
            player.terminate()
        assert WSMPV.keepalive is True and SocketMPV.keepalive is False

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
            agent.close()
            assert _wait(lambda: player._reconnect_delay == 0.04)
        finally:
            player.terminate()


@pytest.mark.django_db
class TestEnsureLink:
    @pytest.fixture
    def service(self, monkeypatch):
        PlayoutHost.objects.all().delete()
        service = MPVService()
        for name in ("_restore_session", "apply_subtitle_style", "_persist_session"):
            monkeypatch.setattr(service, name, lambda: None)
        yield service
        if service.controller is not None:
            service.controller.terminate()

    def _host(self, port, name="Stub", **kw):
        return PlayoutHost.objects.create(
            name=name, base_url=f"http://127.0.0.1:{port}", token="tok", is_active=True, **kw
        )

    def test_connects_to_the_active_agent_and_follows_a_switch(self, service):
        with StubAgent() as first, StubAgent() as second:
            self._host(first.port)
            assert service.ensure_link() is True and first.wait_for_client()
            controller = service.controller
            assert service.ensure_link() is True and service.controller is controller
            self._host(second.port, name="Other")  # save() deactivates the first
            assert service.ensure_link() is True and second.wait_for_client()
            assert service.controller is not controller and service.controller.transport[1] == second.url
