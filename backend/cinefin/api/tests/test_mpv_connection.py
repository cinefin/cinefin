"""MPV connection lifecycle — the single-controller guarantee (regression cover for the duplicate-controller bug)."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from cinefin.api.mpv_service import MPVService

pytestmark = pytest.mark.django_db


def _fresh_service(monkeypatch):
    service = MPVService()
    monkeypatch.setattr(service, "_restore_session", lambda: None)
    monkeypatch.setattr(service, "_load_ident_paused", lambda: None)
    monkeypatch.setattr(service, "apply_subtitle_style", lambda: None)
    return service


def _connected_mock():
    c = MagicMock()
    c._connected = True
    return c


class TestConnectionLifecycle:
    def test_connect_terminates_the_previous_controller(self, monkeypatch):
        built = []

        def make_controller():
            c = _connected_mock()
            built.append(c)
            return c

        with patch("cinefin.api.mpv_service.MPVController", side_effect=make_controller):
            service = _fresh_service(monkeypatch)
            assert service._connect() is True
            first = service.controller
            assert service._connect() is True
            second = service.controller

        assert first is not second
        first.terminate.assert_called_once()
        assert service.controller is second

    def test_concurrent_ensure_connected_builds_one_controller(self, monkeypatch):
        built = []

        def make_controller():
            time.sleep(0.05)
            c = _connected_mock()
            built.append(c)
            return c

        with patch("cinefin.api.mpv_service.MPVController", side_effect=make_controller):
            service = _fresh_service(monkeypatch)
            threads = [threading.Thread(target=service._ensure_connected) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        assert len(built) == 1
        assert service.controller is built[0]
