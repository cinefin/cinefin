"""The playout status: one phase, label and set of actions for every surface."""

from datetime import timedelta

import pytest
from django.utils import timezone

from cinefin.api.models import PlayoutHost, PlayoutSession
from cinefin.api.mpv_service import ProgrammeState, mpv_service
from cinefin.api.services import schedule_runner
from cinefin.api.services.playout_service import next_screening, playout_status

from .factories import (
    BumperFactory,
    CommandFactory,
    MovieFactory,
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


RUNNING = ProgrammeState.RUNNING
TRANSPORT = ["previous", "next", "seek", "jump", "end"]
MANUAL = ["next", "seek", "end", "cue"]


class TestPhase:
    def test_unreachable_or_missing_player_is_offline(self, svc):
        svc.go_offline()
        status = playout_status()
        assert (status.phase, status.label, status.actions) == ("offline", "Living room is offline", [])
        assert status.player.name == "Living room"
        PlayoutHost.objects.all().delete()
        status = playout_status()
        assert (status.phase, status.player, status.label) == ("offline", None, "No player is set up")

    @pytest.mark.parametrize(
        ("programme", "manual", "snapped", "expected"),
        [
            (None, None, {}, ("standby", "System Ident", "Standby", ["cue"])),
            ({}, None, {"pause": True, "pos": 0}, ("cued", "Standby", "Cued · Friday Night", ["start", "cue", "end"])),
            (
                {"offset": 2},
                None,
                {"pause": True, "pos": 1},
                ("cued", "Title card", "Cued · Friday Night", ["start", "cue", "end"]),
            ),
            (
                {"offset": 2, "state": RUNNING},
                None,
                {"pos": 1},
                ("preshow", "Title card", "Pre-show · Title card", ["pause", "next", "seek", "jump", "end"]),
            ),
            (
                {"offset": 2, "state": RUNNING},
                None,
                {"pause": True, "pos": 1},
                ("paused", "Title card", "Pre-show · paused", ["resume", *TRANSPORT]),
            ),
            (
                {"state": RUNNING},
                None,
                {"pos": 1},
                ("playing", "Clip 0", "Item 1 of 2 · Clip 0", ["pause", *TRANSPORT]),
            ),
            (
                {"state": RUNNING},
                None,
                {"pause": True, "pos": 1, "time": 75.0},
                ("paused", "Clip 0", "Paused · Clip 0 at 1:15", ["resume", *TRANSPORT]),
            ),
            (None, ["Dune", "Alien"], {"pos": 1}, ("manual", "Alien", "Manual · 2 of 2 · Alien", ["pause", *MANUAL])),
            (None, ["Dune"], {"pause": True, "pos": 0}, ("paused", "Dune", "Paused · Dune", ["resume", *MANUAL])),
        ],
    )
    def test_phase_screen_label_and_actions(self, svc, programme, manual, snapped, expected):
        if programme is not None:
            load(svc, **programme)
        if manual:
            svc.manual_items = [{"title": t, "kind": "url"} for t in manual]
        svc.set_snap(**snapped)
        status = playout_status()
        assert (status.phase, status.screen, status.label, status.actions) == expected

    def test_cued_and_playing_details(self, svc):
        assert playout_status().playback is None
        load(svc)
        svc.set_snap(pause=True, pos=0)
        status = playout_status()
        assert status.current_item is None and status.next_item.title == "Clip 0"
        assert status.playlist.total_items == 2  # the end sentinel isn't counted
        svc.programme_state = RUNNING
        svc.set_snap(pos=1, time=4.0, duration=10.0)
        playback = playout_status().playback
        assert (playback.position, playback.remaining, playback.percentage) == (4.0, 6.0, 40.0)

    def test_a_command_holding_the_screen_is_hold_with_its_own_clock(self, svc):
        load(svc, items=("command", "system"), state=RUNNING)
        svc.current_playlist.items.filter(order=0).update(command=CommandFactory(name="Dim the lights"))
        svc._executing_command = True
        svc._hold_progress = {"duration": 40.0, "elapsed": 12.5}
        svc.set_snap(pos=1, time=2.0, duration=5.0)  # mpv's clock: the looping black clip
        status = playout_status()
        assert (status.phase, status.screen, status.label) == ("hold", "Black", "Hold · Dim the lights")
        assert status.actions == ["previous", "end_hold", "jump", "end"]
        assert (status.playback.duration, status.playback.position, status.playback.remaining) == (40.0, 12.5, 27.5)


class TestActions:
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

    def test_cueing_over_a_programme_on_air_is_refused(self, svc, client):
        load(svc, state=ProgrammeState.RUNNING)
        svc.set_snap(pos=1)
        other = ProgrammeFactory()
        response = client.post(f"{API}/load", {"programme_id": other.id}, content_type="application/json")
        assert response.status_code == 409
        assert response.json()["details"]["phase"] == "playing"


class TestNextScreening:
    def test_the_next_one_still_to_play_with_its_cue_time(self, svc):
        assert next_screening() is None
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
        assert playout_status().next_screening.id == soon.id


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
    @pytest.mark.parametrize("state,starts", [(ProgrammeState.RUNNING, False), (ProgrammeState.LOADED, True)])
    def test_only_a_cued_programme_is_started(self, monkeypatch, state, starts):
        schedule = ProgrammeScheduleFactory(status="running", start_time=timezone.now() - timedelta(seconds=10))
        monkeypatch.setattr("cinefin.api.services.preshow.run", lambda programme, steps: None)
        monkeypatch.setattr(mpv_service, "programme_state", state, raising=False)
        started = []
        monkeypatch.setattr(mpv_service, "start_programme", lambda: started.append(True) or True)
        monkeypatch.setattr(schedule_runner.time, "sleep", lambda s: None)
        schedule_runner.execute_schedule(schedule)
        assert bool(started) is starts


def pushed():
    """The status as the WebSocket's "playout" channel sends it to an unauthenticated socket."""
    import threading

    from cinefin.api.views.ws_events import _produce

    stop, sent = threading.Event(), []

    def put(msg):
        if msg["channel"] == "playout":
            sent.append(msg["data"])
            stop.set()

    _produce(put, stop, False)
    return sent[0]


def test_the_websocket_pushes_the_same_status(svc):
    assert pushed() == playout_status().dict()


class TestPublicPayload:
    """GET /playout/status and the WebSocket's "playout" channel are readable without a session
    (public kiosks), so the status carries no address, token, socket path or stream URL."""

    SECRETS = ("sekrit-agent-token", "10.0.0.99", "/run/secret-mpv.sock", "?t=", "/stream/")

    def _payloads(self, svc):
        """The pushed status in every phase that has a programme or queue."""
        import json

        def blob():
            return json.dumps(pushed(), default=str)

        blobs = [blob()]  # standby
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
            blobs.append(blob())
        svc.current_programme = svc.current_playlist = None
        svc.manual_items = [{"title": "Dune", "kind": "url"}]
        svc.set_snap(pos=0)
        blobs.append(blob())
        svc.go_offline()
        blobs.append(blob())
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


def test_manual_play_needs_an_http_url_and_ending_a_loaded_programme(svc, client, monkeypatch):
    from cinefin.api.ninja_views import playout_ninja

    url = f"{API}/manual"
    bad = client.post(url, {"kind": "url", "url": "file:///etc/passwd"}, content_type="application/json")
    assert bad.status_code == 400
    calls = []
    monkeypatch.setattr(playout_ninja, "resolve_media_path", lambda obj: "http://d/film")
    svc.current_programme = ProgrammeFactory()
    monkeypatch.setattr(svc, "standby", lambda: calls.append("standby") or True)
    monkeypatch.setattr(svc, "manual_add", lambda *a, **k: calls.append(a) or True)
    body = {"kind": "movie", "id": MovieFactory().id}
    assert client.post(url, body, content_type="application/json").status_code == 409  # PROGRAMME_LOADED
    body["end_programme"] = True
    assert client.post(url, body, content_type="application/json").status_code == 200
    assert calls[0] == "standby" and calls[1][1:] == ("movie", "http://d/film")
