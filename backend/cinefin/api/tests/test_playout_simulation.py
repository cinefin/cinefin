"""End-to-end playout simulations: real MPVService driving a FakeMPVAgent.

transaction=True because the WSMPV dispatcher thread opens its own DB
connection; test data must be committed to be visible to it.
"""

import time

import pytest

from cinefin.api.models import Bumper, PlaylistCue, PlayoutHost, PlayoutSession, Settings
from cinefin.api.mpv_service import MPVService, ProgrammeState
from cinefin.api.services import command_runner

from .factories import CommandFactory, PlaylistFactory, PlaylistItemFactory, ProgrammeFactory
from .fake_mpv_agent import FakeMPVAgent

pytestmark = pytest.mark.django_db(transaction=True)

BLACK_URL = "http://127.0.0.1:8000/stream/system/black/?t=tok"


def wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    return predicate()


@pytest.fixture
def fake():
    with FakeMPVAgent() as agent:
        yield agent


@pytest.fixture
def service(fake):
    PlayoutHost.objects.all().delete()
    PlayoutHost.objects.create(name="Fake", base_url=f"http://127.0.0.1:{fake.port}", token="tkn", is_active=True)
    ident = Bumper.objects.create(title="Ident", file_path="/media/ident.mp4")
    Settings.set("cinema.default_ident_id", ident.id)

    svc = MPVService()
    assert svc._ensure_connected(), "service must connect to the fake agent"
    yield svc
    if svc.controller:
        svc.controller.terminate()


def build_programme(item_specs):
    programme = ProgrammeFactory()
    playlist = PlaylistFactory(programme=programme)
    for order, spec in enumerate(item_specs):
        content_type, file, extra = spec[0], spec[1], (spec[2] if len(spec) > 2 else {})
        PlaylistItemFactory(playlist=playlist, order=order, content_type=content_type, file=file, **extra)
    return programme, playlist


def capture_cues(monkeypatch):
    fired = []
    monkeypatch.setattr(
        command_runner,
        "execute_many_sequential",
        lambda commands, trigger: fired.append(([c.name for c in commands], trigger)),
    )
    return fired


class TestLoadAndStart:
    def test_load_streams_ident_then_appends_the_whole_playlist(self, service, fake):
        programme, _ = build_programme(
            [("bumper", "http://d/stream/bumper/1/"), ("movie", "http://d/stream/movie/1/"), ("system", BLACK_URL)]
        )

        assert service.load_programme(programme) is True

        assert wait_until(lambda: len(fake.playlist) == 4)
        assert "/stream/bumper/" in fake.playlist[0]
        assert fake.playlist[1:] == [
            "http://d/stream/bumper/1/",
            "http://d/stream/movie/1/",
            BLACK_URL,
        ]
        assert service.playlist_offset == 1
        assert service.programme_state == ProgrammeState.LOADED
        assert fake.paused is True

        session = PlayoutSession.load()
        assert session.programme_id == programme.id
        assert session.playlist_offset == 1

    def test_start_unpauses_and_runs(self, service, fake):
        programme, _ = build_programme([("bumper", "http://d/stream/bumper/1/"), ("system", BLACK_URL)])
        service.load_programme(programme)

        assert service.start_programme() is True
        assert service.programme_state == ProgrammeState.RUNNING
        assert wait_until(lambda: fake.paused is False)

    def test_empty_playlist_refused(self, service, fake):
        programme = ProgrammeFactory()
        PlaylistFactory(programme=programme)
        assert service.load_programme(programme) is False
        assert service.programme_state == ProgrammeState.NOT_LOADED


class TestCueFiring:
    def test_eof_advance_fires_the_next_items_cues(self, service, fake, monkeypatch):
        fired = capture_cues(monkeypatch)
        programme, playlist = build_programme(
            [("bumper", "http://d/stream/bumper/1/"), ("bumper", "http://d/stream/bumper/2/"), ("system", BLACK_URL)]
        )
        lights = CommandFactory(name="Lights down")
        PlaylistCue.objects.create(playlist=playlist, command=lights, command_name=lights.name, fires_before_order=1)
        service.load_programme(programme)
        service.start_programme()

        fake.finish_current()
        assert wait_until(lambda: service._programme_cursor == 0)
        assert fired == []

        fake.finish_current()
        assert wait_until(lambda: fired)
        assert fired == [(["Lights down"], "block")]

    def test_forward_jump_fires_every_skipped_cue_in_order(self, service, fake, monkeypatch):
        fired = capture_cues(monkeypatch)
        programme, playlist = build_programme(
            [
                ("bumper", "http://d/stream/bumper/1/"),
                ("bumper", "http://d/stream/bumper/2/"),
                ("bumper", "http://d/stream/bumper/3/"),
                ("system", BLACK_URL),
            ]
        )
        for order, name in [(1, "Curtains"), (2, "Lights")]:
            cmd = CommandFactory(name=name)
            PlaylistCue.objects.create(playlist=playlist, command=cmd, command_name=name, fires_before_order=order)
        service.load_programme(programme)
        service.start_programme()

        service.playlist_jump(service.playlist_offset + 2)

        assert wait_until(lambda: fired)
        assert fired == [(["Curtains", "Lights"], "block")]

    def test_backward_jump_fires_nothing(self, service, fake, monkeypatch):
        fired = capture_cues(monkeypatch)
        programme, playlist = build_programme(
            [
                ("bumper", "http://d/stream/bumper/1/"),
                ("bumper", "http://d/stream/bumper/2/"),
                ("system", BLACK_URL),
            ]
        )
        cmd = CommandFactory(name="Curtains")
        PlaylistCue.objects.create(playlist=playlist, command=cmd, command_name=cmd.name, fires_before_order=1)
        service.load_programme(programme)
        service.start_programme()

        service.playlist_jump(service.playlist_offset + 1)
        assert wait_until(lambda: len(fired) == 1)

        service.playlist_jump(service.playlist_offset + 0)
        assert wait_until(lambda: service._programme_cursor == 0)
        assert len(fired) == 1


class TestHoldBlackJourney:
    def test_full_journey_with_a_hold_item(self, service, fake, monkeypatch):
        executed = []

        def fake_execute(command, trigger, wait=True):
            executed.append((command.name, trigger))
            return True

        monkeypatch.setattr(command_runner, "execute", fake_execute)

        projector = CommandFactory(name="Projector on", duration=1)
        programme, _ = build_programme(
            [
                ("bumper", "http://d/stream/bumper/1/"),
                ("command", BLACK_URL, {"command": projector}),
                ("system", BLACK_URL),
            ]
        )
        service.load_programme(programme)
        service.start_programme()

        fake.finish_current()
        fake.finish_current()

        assert wait_until(lambda: executed)
        assert executed == [("Projector on", "block")]
        assert wait_until(lambda: ("loop-file", "inf") in [tuple(c[1:]) for c in fake.commands_named("set_property")])
        assert wait_until(lambda: service.executing_command)

        assert wait_until(lambda: fake.commands_named("playlist-next"), timeout=10)
        assert wait_until(lambda: ("loop-file", "no") in [tuple(c[1:]) for c in fake.commands_named("set_property")])
        assert wait_until(lambda: service.programme_state == ProgrammeState.COMPLETED, timeout=10)
        assert wait_until(lambda: len(fake.playlist) == 1 and "/stream/bumper/" in fake.playlist[0])
        # Ident is loaded and THEN paused (two commands); the playlist arriving
        # does not mean the pause has — must wait for it separately.
        assert wait_until(lambda: fake.paused is True)
        assert service.current_programme is None
        assert not service.executing_command


class TestSessionRestore:
    def test_new_process_reattaches_to_a_running_screening(self, service, fake):
        programme, _ = build_programme(
            [("bumper", "http://d/stream/bumper/1/"), ("movie", "http://d/stream/movie/1/"), ("system", BLACK_URL)]
        )
        service.load_programme(programme)
        service.start_programme()
        fake.finish_current()
        assert wait_until(lambda: service._programme_cursor == 0)

        service.controller.terminate()

        revived = MPVService()
        assert revived._ensure_connected()
        try:
            assert revived.current_programme.id == programme.id
            assert revived.programme_state == ProgrammeState.RUNNING
            assert revived.playlist_offset == 1
            assert revived._programme_cursor == 0
            assert ("loop-file", "no") in [tuple(c[1:]) for c in fake.commands_named("set_property")]
        finally:
            revived.controller.terminate()

    def test_stale_session_cleared_when_mpv_lost_the_playlist(self, service, fake):
        programme, _ = build_programme([("bumper", "http://d/stream/bumper/1/"), ("system", BLACK_URL)])
        service.load_programme(programme)
        service.start_programme()

        # mpv restarted empty: the persisted session must not zombie-restore.
        with fake._state_lock:
            fake.playlist = []
            fake.pos = None
        service.controller.terminate()

        revived = MPVService()
        assert revived._ensure_connected()
        try:
            assert revived.current_programme is None
            assert revived.programme_state == ProgrammeState.NOT_LOADED
            assert PlayoutSession.load().state == ProgrammeState.NOT_LOADED
        finally:
            revived.controller.terminate()


class TestErrorAdvance:
    def test_stream_error_logs_and_keeps_the_show_moving(self, service, fake, caplog):
        programme, _ = build_programme(
            [("bumper", "http://d/stream/bumper/1/"), ("bumper", "http://d/stream/bumper/2/"), ("system", BLACK_URL)]
        )
        service.load_programme(programme)
        service.start_programme()
        fake.finish_current()
        assert wait_until(lambda: service._programme_cursor == 0)

        with caplog.at_level("WARNING", logger="cinefin.api.mpv_service"):
            fake.finish_current(reason="error")
            assert wait_until(lambda: service._programme_cursor == 1)
            assert wait_until(lambda: any("playback error" in r.message.lower() for r in caplog.records), timeout=5)
        assert service.programme_state == ProgrammeState.RUNNING
