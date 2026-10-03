"""Shared fixtures for the Cinefin test suite."""

import pytest

from cinefin.api.models import Settings


@pytest.fixture(autouse=True)
def setup_completed(db):
    Settings.set("setup.completed", True)


@pytest.fixture
def setup_incomplete(db):
    Settings.set("setup.completed", False)


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    # Per-process brute-force state shared across test clients (all 127.0.0.1)
    # would otherwise leak a lockout into unrelated later tests.
    from cinefin import views

    views._login_failures.clear()


@pytest.fixture(autouse=True)
def standby_pushes(monkeypatch):
    """Record standby spec pushes instead of running them on a background thread
    (which would reach past the test's transaction). Returns the list of calls."""
    from cinefin.api.services import standby

    standby._pushed.clear()
    standby._shown_local.clear()
    calls = []
    monkeypatch.setattr(standby, "push", lambda host_ids=None: calls.append(host_ids))
    return calls


@pytest.fixture(autouse=True)
def instant_standby_fade(monkeypatch):
    """Leaving standby fades through black over about a second; tests run it in
    one step with no waits (test_standby_fade.py sets its own timings)."""
    from cinefin.api import mpv_service

    monkeypatch.setattr(mpv_service, "COVER_FADE_SECONDS", 0.0)
    monkeypatch.setattr(mpv_service, "COVER_REVEAL_SECONDS", 0.0)
    monkeypatch.setattr(mpv_service, "COVER_FIRST_FRAME_WAIT", 0.5)
