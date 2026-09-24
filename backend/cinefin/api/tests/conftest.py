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
