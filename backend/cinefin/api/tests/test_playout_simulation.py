"""End-to-end playout simulations: real MPVService driving a FakeMPVAgent.

transaction=True because the WSMPV dispatcher thread opens its own DB
connection; test data must be committed to be visible to it.
"""

import time

import pytest

from cinefin.api import mpv_service as mpv_module
from cinefin.api.models import PlaylistCue, PlayoutHost, PlayoutSession
from cinefin.api.mpv_service import COVER_OVERLAY_ID, COVER_Z, MPVService, ProgrammeState
from cinefin.api.services import command_runner

from .factories import CommandFactory, PlaylistFactory, PlaylistItemFactory, ProgrammeFactory
from .fake_mpv_agent import FakeMPVAgent, agent_http

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
def service(fake, monkeypatch):
    PlayoutHost.objects.all().delete()
    PlayoutHost.objects.create(name="Fake", base_url=f"http://127.0.0.1:{fake.port}", token="tkn", is_active=True)
    agent_http(monkeypatch, fake)

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


def set_props(fake):
    return [tuple(c[1:]) for c in fake.commands_named("set_property")]


def capture_cues(monkeypatch):
    fired = []
    monkeypatch.setattr(
        command_runner,
        "execute_many_sequential",
        lambda commands, trigger: fired.append(([c.name for c in commands], trigger)),
    )
    return fired


def assert_aligned(service, fake, playlist):
    """Entry by entry: every item sits at mpv_index = playlist_offset + order."""
    for item in playlist.items.order_by("order"):
        assert fake.playlist[service.playlist_offset + item.order] == item.file
    assert len(fake.playlist) == service.playlist_offset + playlist.items.count()


class TestLoadAndStart:
    def test_load_keeps_standby_first_and_appends_the_whole_playlist(self, service, fake):
        programme, playlist = build_programme(
            [("bumper", "http://d/stream/bumper/1/"), ("movie", "http://d/stream/movie/1/"), ("system", BLACK_URL)]
        )

        assert service.load_programme(programme) is True

        # The player was sent its spec and put on standby, which stays as entry 0.
        assert fake.standby_spec["ident"]["options"] == "ab-loop-a=4,ab-loop-b=34"
        assert fake.playlist[0] == fake.standby_loaded
        assert service.playlist_offset == 1
        assert_aligned(service, fake, playlist)
        assert fake.pos == 0  # no title card: standby holds until start
        assert service.programme_state == ProgrammeState.LOADED
        assert fake.commands_named("playlist-clear")

        session = PlayoutSession.load()
        assert session.programme_id == programme.id
        assert session.playlist_offset == 1

        empty = ProgrammeFactory()
        PlaylistFactory(programme=empty)
        assert service.load_programme(empty) is False


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

        assert wait_until(lambda: executed)
        assert executed == [("Projector on", "block")]
        assert wait_until(lambda: ("loop-file", "inf") in set_props(fake))
        assert wait_until(lambda: service.executing_command)

        assert wait_until(lambda: fake.commands_named("playlist-next"), timeout=10)
        assert wait_until(lambda: ("loop-file", "no") in set_props(fake))
        # The end sentinel put the player straight on standby.
        assert wait_until(lambda: service.programme_state == ProgrammeState.NOT_LOADED, timeout=10)
        assert wait_until(lambda: fake.playlist == [fake.standby_loaded])
        assert fake.paused is False
        assert service.current_programme is None
        assert not service.executing_command


class TestSessionRestore:
    def test_new_process_reattaches_to_a_running_screening(self, service, fake):
        programme, _ = build_programme(
            [("bumper", "http://d/stream/bumper/1/"), ("movie", "http://d/stream/movie/1/"), ("system", BLACK_URL)]
        )
        service.load_programme(programme)
        service.start_programme()
        assert wait_until(lambda: service._programme_cursor == 0)

        service.controller.terminate()

        revived = MPVService()
        assert revived._ensure_connected()
        try:
            assert revived.current_programme.id == programme.id
            assert revived.programme_state == ProgrammeState.RUNNING
            assert revived.playlist_offset == 1
            assert revived._programme_cursor == 0
            assert ("loop-file", "no") in set_props(fake)
        finally:
            revived.controller.terminate()


# Manual mode: one-off items on the player outside any programme.

A, B, C = "http://d/a.mp4", "http://d/b.mp4", "http://d/c.mp4"


def titles(svc):
    return [i["title"] for i in svc.manual_items]


class TestManualQueue:
    def test_queue_appends_before_the_sentinel_and_play_now_goes_next(self, service, fake):
        assert service.manual_add("A", "url", A) is True
        assert wait_until(lambda: len(fake.playlist) == 2)
        assert fake.playlist[0] == A and "/stream/system/black" in fake.playlist[1]
        service.manual_add("B", "url", B)
        assert wait_until(lambda: len(fake.playlist) == 3)
        assert fake.playlist[:2] == [A, B]
        service.manual_add("C", "url", C, now=True)
        assert wait_until(lambda: fake.current_file == C)
        assert fake.playlist[:3] == [A, C, B] and titles(service) == ["A", "C", "B"]

    def test_move_and_remove_keep_titles_in_step_with_the_player(self, service, fake):
        for t, u in (("A", A), ("B", B), ("C", C)):
            service.manual_add(t, "url", u)
        assert wait_until(lambda: len(fake.playlist) == 4)
        assert service.manual_move(2, 1) is True
        assert wait_until(lambda: fake.playlist[:3] == [A, C, B])
        assert service.manual_move(0, 2) is True
        assert wait_until(lambda: fake.playlist[:3] == [C, B, A])
        assert titles(service) == ["C", "B", "A"]
        assert service.manual_remove(1) is True
        assert wait_until(lambda: fake.playlist[:2] == [C, A])
        assert titles(service) == ["C", "A"]

    def test_the_sentinel_puts_the_player_on_standby(self, service, fake):
        service.manual_add("A", "url", A)
        assert wait_until(lambda: len(fake.playlist) == 2)
        fake.finish_current()
        assert wait_until(lambda: not service.manual_items)
        assert wait_until(lambda: fake.playlist == [fake.standby_loaded])

    def test_loading_a_programme_replaces_manual_play(self, service, fake):
        service.manual_add("A", "url", A)
        programme, playlist = build_programme([("bumper", "http://d/stream/bumper/1/"), ("system", BLACK_URL)])
        assert service.load_programme(programme) is True
        assert service.manual_items == []
        assert fake.playlist[0] == fake.standby_loaded
        assert_aligned(service, fake, playlist)


def _cover_alpha(overlay):
    """The cover's ASS alpha (0 opaque, 255 clear), or None for a removal."""
    if overlay["format"] == "none":
        return None
    return int(overlay["data"].split(r"\1a&H", 1)[1][:2], 16)


def _cover_sequence(fake):
    """The cover overlays and playlist moves, in the order the player received them."""
    seq = []
    for c in list(fake.received_commands):
        if isinstance(c, dict) and c.get("name") == "osd-overlay":
            seq.append(("cover", _cover_alpha(c)))
        elif isinstance(c, list) and c[:2] == ["set_property", "playlist-pos"]:
            seq.append(("move", c[2]))
    return seq


def _cover_removed(fake):
    return bool(fake.overlays()) and fake.overlays()[-1]["format"] == "none"


class TestStandbyFade:
    """Leaving standby for a programme fades to black, moves on, then reveals the
    next entry, under a black osd-overlay cover (id 2, above the agent's card)."""

    @pytest.fixture(autouse=True)
    def short_fade(self, monkeypatch):
        # A few steps each way, quickly (conftest makes it instant elsewhere).
        monkeypatch.setattr(mpv_module, "COVER_FADE_SECONDS", 0.12)
        monkeypatch.setattr(mpv_module, "COVER_REVEAL_SECONDS", 0.12)
        monkeypatch.setattr(mpv_module, "COVER_FIRST_FRAME_WAIT", 1.0)

    def test_start_fades_out_then_moves_then_reveals(self, service, fake):
        programme, playlist = build_programme(
            [("bumper", "http://d/stream/bumper/1/"), ("movie", "http://d/stream/movie/1/"), ("system", BLACK_URL)]
        )
        assert service.load_programme(programme) is True
        assert fake.overlays() == []  # no title card: standby holds, untouched

        assert service.start_programme() is True
        assert wait_until(lambda: _cover_removed(fake))

        seq = _cover_sequence(fake)
        move = seq.index(("move", 1))
        fade, reveal = [a for _, a in seq[:move]], [a for _, a in seq[move + 1 :]]
        assert len(fade) >= 2 and fade == sorted(fade, reverse=True) and fade[-1] == 0  # clear to opaque
        assert len(reveal) >= 2 and reveal[-1] is None  # back towards clear, then removed
        assert reveal[0] > 0 and reveal[:-1] == sorted(reveal[:-1])
        for overlay in fake.overlays():
            assert overlay["id"] == COVER_OVERLAY_ID
            if overlay["format"] == "ass-events":
                assert overlay["z"] == COVER_Z and (overlay["res_x"], overlay["res_y"]) == (1280, 720)

        assert fake.current_file == "http://d/stream/bumper/1/"
        assert_aligned(service, fake, playlist)
        assert wait_until(lambda: service._programme_cursor == 0)

    def test_a_lead_in_cues_a_title_card_that_fades_in_and_holds(self, service, fake, tmp_path, monkeypatch):
        from cinefin.api.services import preshow

        monkeypatch.setattr("cinefin.api.mpv_service.mpv_service", service)
        programme, playlist = build_programme([("bumper", "http://d/stream/bumper/1/"), ("system", BLACK_URL)])
        (tmp_path / "title.mp4").write_bytes(b"x")
        programme.title_file, programme.title_hold, programme.title_fade_in = str(tmp_path / "title.mp4"), True, 2.0
        programme.save()

        preshow.run(programme, [])  # just the cue
        assert service.programme_state == ProgrammeState.LOADED
        assert fake.playlist[0] == fake.standby_loaded and f"/stream/title/{programme.id}/" in fake.playlist[1]
        assert wait_until(lambda: _cover_removed(fake))

        seq = _cover_sequence(fake)
        move = seq.index(("move", 1))
        assert seq[move - 1] == ("cover", 0)  # fully black before the move
        assert seq[move + 1 :] == [("cover", None)]  # then removed in one go
        assert service.playlist_offset == 2
        assert_aligned(service, fake, playlist)

        # The title card still plays its fade-in and holds there.
        assert wait_until(lambda: fake.pos == 1 and service._title_armed)
        fake.set_time(1.0)
        assert fake.paused is False
        fake.set_time(2.1)
        assert wait_until(lambda: fake.paused is True)

        # Start plays on from the title card: standby is gone, so no second fade.
        before = len(fake.overlays())
        assert service.start_programme() is True
        assert wait_until(lambda: fake.paused is False)
        assert len(fake.overlays()) == before and fake.pos == 1
        fake.finish_current()
        assert wait_until(lambda: service._programme_cursor == 0)

    def test_the_cover_is_removed_when_the_fade_fails(self, service, fake):
        programme, playlist = build_programme([("bumper", "http://d/stream/bumper/1/"), ("system", BLACK_URL)])
        service.load_programme(programme)
        real = service.controller._mpv_command
        drawn = []

        def flaky(command, *args):
            if isinstance(command, dict) and command.get("format") == "ass-events":
                drawn.append(command)
                if len(drawn) == 2:
                    raise RuntimeError("link dropped mid-fade")
            return real(command, *args)

        service.controller._mpv_command = flaky
        assert service.start_programme() is True

        assert wait_until(lambda: _cover_removed(fake))  # lifted, never left on screen
        assert ("move", 1) in _cover_sequence(fake)  # and the programme still moved on
        assert wait_until(lambda: fake.current_file == "http://d/stream/bumper/1/")
        assert_aligned(service, fake, playlist)
