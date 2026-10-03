"""The playout status: one phase, label and set of actions for every surface."""

from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from cinefin.api.models import PlayoutHost, PlayoutSession
from cinefin.api.mpv_service import ProgrammeState, mpv_service
from cinefin.api.services import schedule_runner
from cinefin.api.services.playout_service import allowed_actions, next_screening, phase_of, playout_status

from .factories import (
    BumperFactory,
    CommandFactory,
    PlaylistFactory,
    PlaylistItemFactory,
    ProgrammeFactory,
    ProgrammeScheduleFactory,
)

pytestmark = pytest.mark.django_db

API = "/api/v2/playout"


def snap(pause=False, pos=None, time=1.0, duration=10.0):
    return {"pause": pause, "time": time, "duration": duration, "pos": pos, "path": ""}


@pytest.fixture
def svc(monkeypatch):
    """The mpv_service singleton, with nothing loaded and a player snapshot to set."""
    for name, value in {
        "current_programme": None,
        "current_playlist": None,
        "playlist_offset": 0,
        "programme_state": ProgrammeState.NOT_LOADED,
        "manual_items": [],
        "_executing_command": False,
        "_hold_progress": None,
    }.items():
        monkeypatch.setattr(mpv_service, name, value, raising=False)
    state = {"snap": snap()}
    monkeypatch.setattr(mpv_service, "snapshot", lambda: state["snap"])
    mpv_service.set_snap = lambda **kw: state.update(snap=snap(**kw))
    mpv_service.go_offline = lambda: state.update(snap=None)
    PlayoutHost.objects.all().delete()
    PlayoutHost.objects.create(name="Living room", base_url="http://10.0.0.5:8089", token="t", is_active=True)
    yield mpv_service
    del mpv_service.set_snap, mpv_service.go_offline


def load(svc, items=("bumper", "movie", "system"), offset=1, state=ProgrammeState.LOADED):
    programme = ProgrammeFactory(name="Friday Night")
    playlist = PlaylistFactory(programme=programme)
    for order, content_type in enumerate(items):
        extra = {"bumper": BumperFactory(title=f"Clip {order}")} if content_type == "bumper" else {}
        PlaylistItemFactory(playlist=playlist, order=order, content_type=content_type, **extra)
    svc.current_programme, svc.current_playlist = programme, playlist
    svc.playlist_offset, svc.programme_state = offset, state
    return programme


class TestPhase:
    def test_unreachable_player_is_offline(self, svc):
        svc.go_offline()
        status = playout_status()
        assert status.phase == "offline"
        assert status.label == "Living room is offline"
        assert status.actions == []
        assert status.player.name == "Living room"

    def test_no_player_set_up(self, svc):
        PlayoutHost.objects.all().delete()
        status = playout_status()
        assert (status.phase, status.player, status.label) == ("offline", None, "No player is set up")

    def test_nothing_loaded_is_standby_showing_the_ident(self, svc):
        status = playout_status()
        assert (status.phase, status.label, status.screen) == ("standby", "Standby", "System Ident")
        assert status.actions == ["cue"]
        assert status.playback is None and status.programme is None

    def test_loaded_is_cued_on_standby(self, svc):
        load(svc)
        svc.set_snap(pause=True, pos=0)
        status = playout_status()
        assert (status.phase, status.screen, status.label) == ("cued", "Standby", "Cued · Friday Night")
        assert status.actions == ["start", "cue", "end"]
        assert status.current_item is None
        assert status.next_item.title == "Clip 0"  # first up
        assert status.playlist.total_items == 2  # the end sentinel isn't counted

    def test_cued_on_a_held_title_card(self, svc):
        load(svc, offset=2)
        svc.set_snap(pause=True, pos=1)
        status = playout_status()
        assert (status.phase, status.screen) == ("cued", "Title card")
        assert status.current_item.type == "title"

    def test_started_on_the_title_card_is_preshow(self, svc):
        load(svc, offset=2, state=ProgrammeState.RUNNING)
        svc.set_snap(pos=1)
        status = playout_status()
        assert (status.phase, status.screen, status.label) == ("preshow", "Title card", "Pre-show · Title card")
        assert status.actions == ["pause", "next", "seek", "jump", "end"]
        assert status.playlist.current_position is None

    def test_an_item_playing(self, svc):
        load(svc, state=ProgrammeState.RUNNING)
        svc.set_snap(pos=1, time=4.0, duration=10.0)
        status = playout_status()
        assert status.phase == "playing"
        assert (status.screen, status.label) == ("Clip 0", "Item 1 of 2 · Clip 0")
        assert status.actions == ["pause", "previous", "next", "seek", "jump", "end"]
        assert (status.playback.position, status.playback.remaining, status.playback.percentage) == (4.0, 6.0, 40.0)

    def test_operator_pause_is_paused(self, svc):
        load(svc, state=ProgrammeState.RUNNING)
        svc.set_snap(pause=True, pos=1, time=75.0)
        status = playout_status()
        assert (status.phase, status.label) == ("paused", "Paused · Clip 0 at 1:15")
        assert status.actions == ["resume", "previous", "next", "seek", "jump", "end"]

    def test_paused_preshow_is_paused(self, svc):
        load(svc, offset=2, state=ProgrammeState.RUNNING)
        svc.set_snap(pause=True, pos=1)
        assert playout_status().phase == "paused"

    def test_a_command_holding_the_screen_is_hold_with_its_own_clock(self, svc):
        load(svc, items=("command", "system"), state=ProgrammeState.RUNNING)
        svc.current_playlist.items.filter(order=0).update(command=CommandFactory(name="Dim the lights"))
        svc._executing_command = True
        svc._hold_progress = {"duration": 40.0, "elapsed": 12.5}
        svc.set_snap(pos=1, time=2.0, duration=5.0)  # mpv's clock: the looping black clip
        status = playout_status()
        assert (status.phase, status.screen, status.label) == ("hold", "Black", "Hold · Dim the lights")
        assert "end_hold" in status.actions and "next" not in status.actions and "pause" not in status.actions
        assert (status.playback.duration, status.playback.position, status.playback.remaining) == (40.0, 12.5, 27.5)

    def test_manual_queue(self, svc):
        svc.manual_items = [{"title": "Dune", "kind": "trailer"}, {"title": "Alien", "kind": "movie"}]
        svc.set_snap(pos=1)
        status = playout_status()
        assert (status.phase, status.label, status.screen) == ("manual", "Manual · 2 of 2 · Alien", "Alien")
        assert status.actions == ["pause", "next", "seek", "end", "cue"]
        assert status.manual.position == 1

    def test_paused_manual_queue(self, svc):
        svc.manual_items = [{"title": "Dune", "kind": "trailer"}]
        svc.set_snap(pause=True, pos=0)
        status = playout_status()
        assert (status.phase, status.label) == ("paused", "Paused · Dune")
        assert status.actions == ["resume", "next", "seek", "end", "cue"]

    def test_phase_of_needs_no_status_build(self, svc):
        assert phase_of(None) == "offline"
        assert phase_of(snap()) == "standby"


class TestActions:
    @pytest.mark.parametrize(
        ("phase", "manual", "allowed"),
        [
            ("offline", False, []),
            ("standby", False, ["cue"]),
            ("cued", False, ["start", "cue", "end"]),
            ("hold", False, ["previous", "end_hold", "jump", "end"]),
            ("paused", True, ["resume", "next", "seek", "end", "cue"]),
        ],
    )
    def test_allowed_per_phase(self, phase, manual, allowed):
        assert allowed_actions(phase, manual) == allowed

    def test_disallowed_action_is_a_409_naming_the_phase(self, svc, client):
        response = client.post(f"{API}/control", {"action": "start"}, content_type="application/json")
        assert response.status_code == 409
        body = response.json()
        assert body["error_code"] == "ACTION_NOT_ALLOWED"
        assert body["details"] == {"phase": "standby", "actions": ["cue"]}
        assert "nothing is loaded" in body["error"]

    def test_next_during_a_hold_is_refused_but_end_hold_moves_on(self, svc, client, monkeypatch):
        load(svc, items=("command", "system"), state=ProgrammeState.RUNNING)
        svc._executing_command = True
        svc.set_snap(pos=1)
        moved = []
        monkeypatch.setattr(svc, "next", lambda: moved.append(True) or True)

        assert client.post(f"{API}/control", {"action": "next"}, content_type="application/json").status_code == 409
        response = client.post(f"{API}/control", {"action": "end_hold"}, content_type="application/json")
        assert response.status_code == 200 and moved == [True]

    def test_pause_goes_through_the_player_and_returns_the_status(self, svc, client, monkeypatch):
        load(svc, state=ProgrammeState.RUNNING)
        svc.set_snap(pos=1)

        def pause():
            svc.set_snap(pause=True, pos=1)
            return True

        monkeypatch.setattr(svc, "pause", pause)
        response = client.post(f"{API}/control", {"action": "pause"}, content_type="application/json")
        assert response.status_code == 200
        assert response.json()["data"]["phase"] == "paused"

    def test_seek_by_an_offset(self, svc, client, monkeypatch):
        load(svc, state=ProgrammeState.RUNNING)
        svc.set_snap(pos=1)
        seeks = []
        monkeypatch.setattr(svc, "seek_relative", lambda s: seeks.append(s) or True)
        response = client.post(f"{API}/control", {"action": "seek", "offset": -10}, content_type="application/json")
        assert response.status_code == 200 and seeks == [-10]

    def test_end_goes_to_standby(self, svc, client, monkeypatch):
        load(svc)
        svc.set_snap(pause=True, pos=0)
        ended = MagicMock(return_value=True)
        monkeypatch.setattr(svc, "standby", ended)
        assert client.post(f"{API}/control", {"action": "end"}, content_type="application/json").status_code == 200
        ended.assert_called_once_with()

    def test_cueing_over_a_programme_on_air_is_refused(self, svc, client):
        load(svc, state=ProgrammeState.RUNNING)
        svc.set_snap(pos=1)
        other = ProgrammeFactory()
        response = client.post(f"{API}/load", {"programme_id": other.id}, content_type="application/json")
        assert response.status_code == 409
        assert response.json()["details"]["phase"] == "playing"


class TestNextScreening:
    def test_none_scheduled(self, svc):
        assert next_screening() is None

    def test_the_next_one_still_to_play_with_its_cue_time(self, svc):
        now = timezone.now()
        ProgrammeScheduleFactory(start_time=now - timedelta(hours=3))  # already played
        ProgrammeScheduleFactory(start_time=now + timedelta(hours=1), status="cancelled")
        lights = CommandFactory(duration=90)
        later = ProgrammeScheduleFactory(start_time=now + timedelta(hours=3))
        soon = ProgrammeScheduleFactory(
            start_time=now + timedelta(hours=2),
            lead_in=300,
            preshow=[{"command": lights.id}, {"cue": True}],
        )

        screening = next_screening()
        assert screening.id == soon.id != later.id
        assert screening.programme_name == soon.programme.name
        assert screening.start_time == soon.start_time + timedelta(seconds=300)
        assert screening.cue_time == soon.start_time + timedelta(seconds=90)

    def test_in_the_status(self, svc):
        ProgrammeScheduleFactory()
        assert playout_status().next_screening is not None


class TestSessionMigration:
    def test_old_states_map_onto_the_three(self):
        from importlib import import_module

        from django.apps import apps

        migration = import_module("cinefin.api.migrations.0050_playout_session_states")
        programme = ProgrammeFactory()
        session = PlayoutSession.load()
        for old, new, keeps_programme in [
            ("paused", "running", True),
            ("completed", "not_loaded", False),
            ("error", "not_loaded", False),
            ("loaded", "loaded", True),
        ]:
            PlayoutSession.objects.filter(pk=session.pk).update(state=old, programme=programme)
            migration.reduce_states(apps, None)
            session.refresh_from_db()
            assert session.state == new
            assert (session.programme_id == programme.id) is keeps_programme


class TestScheduleRunnerStates:
    def test_busy_only_once_a_programme_has_started(self, monkeypatch):
        for state, busy in [
            (ProgrammeState.NOT_LOADED, False),
            (ProgrammeState.LOADED, False),
            (ProgrammeState.RUNNING, True),
        ]:
            monkeypatch.setattr(mpv_service, "programme_state", state, raising=False)
            assert schedule_runner._mpv_busy() is busy

    def test_a_started_programme_is_not_started_again(self, monkeypatch):
        schedule = ProgrammeScheduleFactory(status="running", start_time=timezone.now() - timedelta(seconds=10))
        monkeypatch.setattr("cinefin.api.services.preshow.run", lambda programme, steps: None)
        monkeypatch.setattr(mpv_service, "programme_state", ProgrammeState.RUNNING, raising=False)
        started = []
        monkeypatch.setattr(mpv_service, "start_programme", lambda: started.append(True) or True)
        monkeypatch.setattr(schedule_runner.time, "sleep", lambda s: None)

        schedule_runner.execute_schedule(schedule)
        assert started == []

    def test_a_cued_programme_is_started(self, monkeypatch):
        schedule = ProgrammeScheduleFactory(status="running", start_time=timezone.now() - timedelta(seconds=10))
        monkeypatch.setattr("cinefin.api.services.preshow.run", lambda programme, steps: None)
        monkeypatch.setattr(mpv_service, "programme_state", ProgrammeState.LOADED, raising=False)
        started = []
        monkeypatch.setattr(mpv_service, "start_programme", lambda: started.append(True) or True)
        monkeypatch.setattr(schedule_runner.time, "sleep", lambda s: None)

        schedule_runner.execute_schedule(schedule)
        assert started == [True]


def test_the_websocket_pushes_the_same_status(svc):
    """GET /playout/status and the WebSocket push share one builder, so their shapes can't drift."""
    import threading

    from cinefin.api.views.ws_events import _produce

    stop, sent = threading.Event(), []

    def put(msg):
        if msg["channel"] == "playout":
            sent.append(msg["data"])
            stop.set()

    _produce(put, stop, False)
    assert sent == [playout_status().dict()]


class TestPublicPayload:
    """GET /playout/status and the WebSocket's "playout" channel are readable without a session
    (public kiosks), so the status carries no address, token, socket path or stream URL."""

    SECRETS = ("sekrit-agent-token", "10.0.0.99", "/run/secret-mpv.sock", "?t=", "/stream/")

    def _payloads(self, svc):
        """The status as the WebSocket sends it, in every phase that has a programme or queue."""
        import json
        import threading

        from cinefin.api.views.ws_events import _produce

        def pushed():
            stop, sent = threading.Event(), []

            def put(msg):
                if msg["channel"] == "playout":
                    sent.append(msg["data"])
                    stop.set()

            _produce(put, stop, False)  # an unauthenticated (kiosk) socket
            return json.dumps(sent[0], default=str)

        blobs = [pushed()]  # standby
        programme = load(svc, offset=2)
        programme.title_file = "clips/title.mp4"
        programme.save()
        svc.current_playlist.items.update(file="http://10.0.0.99:8000/stream/bumper/1/?t=streamtoken")
        for state, pos, pause in [
            (ProgrammeState.LOADED, 1, True),  # cued on the title card
            (ProgrammeState.RUNNING, 1, False),  # pre-show
            (ProgrammeState.RUNNING, 2, False),  # playing
            (ProgrammeState.RUNNING, 3, True),  # paused
        ]:
            svc.programme_state = state
            svc.set_snap(pause=pause, pos=pos)
            blobs.append(pushed())
        svc.current_programme = svc.current_playlist = None
        svc.manual_items = [{"title": "Dune", "kind": "url"}]
        svc.set_snap(pos=0)
        blobs.append(pushed())
        svc.go_offline()
        blobs.append(pushed())
        return blobs

    @pytest.mark.parametrize("kind", [PlayoutHost.KIND_AGENT, PlayoutHost.KIND_LOCAL_SOCKET])
    def test_no_address_token_socket_or_stream_url(self, svc, kind):
        PlayoutHost.objects.all().delete()
        PlayoutHost.objects.create(
            name="Living room",
            kind=kind,
            base_url="http://10.0.0.99:8089",
            socket_path="/run/secret-mpv.sock",
            token="sekrit-agent-token",
            is_active=True,
        )
        ProgrammeScheduleFactory()  # a next screening too
        blobs = self._payloads(svc)
        assert len(blobs) == 7
        for blob in blobs:
            for secret in self.SECRETS:
                assert secret not in blob, f"{secret!r} in the public status: {blob}"
        assert '"name": "Living room"' in blobs[0]  # the player is still named
