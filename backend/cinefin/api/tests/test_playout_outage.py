"""What the playout service does when the player's link drops and comes back, or Cinefin restarts."""

import time
from datetime import timedelta
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from cinefin.api.models import PlayoutSession, ProgrammeSchedule
from cinefin.api.mpv_service import MPVService, ProgrammeState
from cinefin.api.services import command_runner, schedule_runner

from .factories import CommandFactory, PlaylistFactory, PlaylistItemFactory, ProgrammeFactory

pytestmark = pytest.mark.django_db

STANDBY = {"filename": "http://cinefin/stream/system/ident/?t=a"}


def _programme(types=("bumper", "movie", "system")):
    playlist = PlaylistFactory(programme=ProgrammeFactory())
    for order, content_type in enumerate(types):
        PlaylistItemFactory(
            playlist=playlist, order=order, content_type=content_type, file=f"http://cinefin/stream/{order}/?t=a"
        )
    return playlist


def _entries(playlist, offset=1, token="b"):
    """MPV's playlist holding ``playlist`` behind standby (the stream tokens may differ)."""
    files = playlist.items.order_by("order").values_list("file", flat=True)
    return [STANDBY] * offset + [{"filename": f.split("?")[0] + f"?t={token}"} for f in files]


def _service(playlist=None, state=ProgrammeState.RUNNING):
    service = MPVService()
    service.controller = MagicMock()
    service._lazy_initialized = True
    service._session_restored = True
    if playlist is not None:
        service.current_programme, service.current_playlist = playlist.programme, playlist
        service.playlist_offset, service.programme_state = 1, state
    return service


def _persist(playlist, state=ProgrammeState.RUNNING):
    session = PlayoutSession.load()
    session.programme, session.state, session.playlist_offset = playlist.programme, state, 1
    session.save()


def _running_screening(programme):
    return ProgrammeSchedule.objects.create(
        programme=programme, start_time=timezone.now() - timedelta(minutes=5), runtime=120, status="running"
    )


class TestReconcileOnReconnect:
    def test_keeps_a_programme_the_player_still_holds(self):
        playlist = _programme()
        service = _service(playlist)
        service.controller.get_playlist.return_value = _entries(playlist)
        service._reconcile()
        assert service.programme_state == ProgrammeState.RUNNING

    def test_clears_a_programme_lost_to_a_player_restart(self):
        playlist = _programme()
        screening = _running_screening(playlist.programme)
        service = _service(playlist)
        service.controller.get_playlist.return_value = [STANDBY]
        service._reconcile()
        assert service.programme_state == ProgrammeState.NOT_LOADED and service.current_programme is None
        service.controller.load_file.assert_called_once()  # standby put back on screen
        assert PlayoutSession.load().state == ProgrammeState.NOT_LOADED
        screening.refresh_from_db()
        assert screening.status == "missed" and screening.last_error

    def test_clears_a_lost_manual_queue(self):
        service = _service()
        service.manual_items = [{"title": "Alien", "kind": "movie"}]
        service.controller.get_playlist.return_value = [STANDBY]
        service._reconcile()
        assert service.manual_items == []

    def test_leaves_it_alone_when_the_player_cannot_say(self):
        playlist = _programme()
        service = _service(playlist)
        service.controller.get_playlist.return_value = None
        service._reconcile()
        assert service.programme_state == ProgrammeState.RUNNING


class TestRestore:
    def test_re_attaches_when_the_player_holds_the_programme(self):
        playlist = _programme()
        _persist(playlist)
        service = _service()
        service._session_restored = False
        service.controller.get_playlist.return_value = _entries(playlist)
        service.controller.get_property.return_value = None
        service._restore_session()
        assert service.programme_state == ProgrammeState.RUNNING and service.current_playlist == playlist

    def test_does_not_take_another_playlist_of_the_same_length_for_it(self):
        playlist = _programme()
        _persist(playlist)
        screening = _running_screening(playlist.programme)
        service = _service()
        service._session_restored = False
        service.controller.get_playlist.return_value = [STANDBY] + [{"filename": "http://elsewhere/x"}] * 3
        service._restore_session()
        assert service.programme_state == ProgrammeState.NOT_LOADED
        screening.refresh_from_db()
        assert screening.status == "missed"

    def test_fires_the_cues_passed_while_cinefin_was_away(self, monkeypatch):
        fired = []
        monkeypatch.setattr(command_runner, "execute_many_sequential", lambda commands, trigger: fired.extend(commands))
        playlist = _programme()
        command = CommandFactory()
        playlist.cues.create(command=command, command_name=command.name, fires_before_order=1)
        _persist(playlist)
        session = PlayoutSession.load()
        session.programme_cursor = 0
        session.save()
        service = _service()
        service._session_restored = False
        c = service.controller
        c.get_playlist.return_value = _entries(playlist)
        c.get_property.side_effect = lambda name, quiet=False: {"path": "http://cinefin/stream/1/", "playlist_pos": 2}[
            name
        ]
        service._restore_session()
        assert fired == [command] and PlayoutSession.load().programme_cursor == 1

    def test_restores_manual_play(self):
        session = PlayoutSession.load()
        session.manual_items = [{"title": "Alien", "kind": "movie"}]
        session.save()
        service = _service()
        service._session_restored = False
        service.controller.get_playlist.return_value = [{"filename": "a"}, {"filename": "black"}]
        service._restore_session()
        assert service.manual_items == [{"title": "Alien", "kind": "movie"}]


def test_the_manual_queue_is_persisted():
    service = _service()
    c = service.controller
    c.load_file.return_value = c.enqueue_file.return_value = c.pause.return_value = True
    service.manual_add("Alien", "movie", "http://x/alien")
    assert PlayoutSession.load().manual_items == [{"title": "Alien", "kind": "movie"}]


def test_a_failed_start_leaves_the_programme_cued():
    playlist = _programme()
    service = _service(playlist, state=ProgrammeState.LOADED)
    service.controller.get_property.return_value = 3
    service.controller.play.return_value = False
    assert service.start_programme() is False
    assert service.programme_state == ProgrammeState.LOADED
    assert PlayoutSession.load().state == ProgrammeState.LOADED


def test_an_unknown_position_never_ends_the_programme():
    playlist = _programme()
    service = _service(playlist)
    service.controller.get_property.return_value = None  # the link is down
    service.standby = MagicMock()
    service._handle_file_start("http://cinefin/stream/system/black/")
    service.standby.assert_not_called()
    assert service.programme_state == ProgrammeState.RUNNING


class TestHoldAcrossAnOutage:
    def test_the_position_coming_back_does_not_start_the_hold_again(self):
        playlist = _programme(("command", "movie", "system"))
        service = _service(playlist)
        service._hold = MagicMock()
        service._handle_playlist_change(1)
        service._handle_playlist_change(1)  # re-sent when the link comes back
        time.sleep(0.1)
        service._hold.assert_called_once()

    def test_a_hold_waits_out_a_dropped_link_and_fires_once(self, monkeypatch):
        executed = []
        monkeypatch.setattr(command_runner, "execute", lambda cmd, trigger, **kw: executed.append(cmd.name))
        playlist = _programme(("command", "system"))
        item = playlist.items.get(order=0)
        item.command = CommandFactory(name="Curtains", duration=0.25)
        item.save()
        service = _service(playlist)
        reads = {"n": 0}

        def get_property(name, quiet=False):
            if name == "pause":
                return False
            reads["n"] += 1
            return None if reads["n"] <= 4 else 1  # down for a second, then back on the hold

        service.controller.get_property.side_effect = get_property
        service.controller.set_property.return_value = True
        service._run_hold_item(item, 1)
        assert executed == ["Curtains"]
        service.controller.next.assert_called_once()


class TestScheduleRecovery:
    def test_a_screening_still_on_air_survives_a_restart(self, monkeypatch):
        from cinefin.api.mpv_service import mpv_service

        monkeypatch.setattr(mpv_service, "_session_restored", False)
        playlist = _programme()
        _persist(playlist)
        screening = _running_screening(playlist.programme)
        schedule_runner.recover_orphans()
        screening.refresh_from_db()
        assert screening.status == "running"

    def test_the_player_counts_as_busy_until_re_attached(self, monkeypatch):
        from cinefin.api.mpv_service import mpv_service

        monkeypatch.setattr(mpv_service, "_session_restored", False)
        _persist(_programme())
        assert schedule_runner._mpv_busy() is True


class TestScreeningEndsWithItsProgramme:
    def test_standby_on_air_completes_the_screening_and_frees_its_slot(self):
        from cinefin.api.ninja_views.schedules_ninja import _reject_overlap

        playlist = _programme()
        screening = _running_screening(playlist.programme)
        _service(playlist).standby()
        screening.refresh_from_db()
        assert screening.status == "completed"
        _reject_overlap(ProgrammeSchedule(programme=playlist.programme, start_time=timezone.now(), runtime=60))

    def test_a_cued_programme_in_its_lead_in_stays_running(self):
        playlist = _programme()
        screening = _running_screening(playlist.programme)
        _service(playlist, state=ProgrammeState.LOADED).standby()
        screening.refresh_from_db()
        assert screening.status == "running"


class TestResumeInterrupted:
    def _lost(self, screening=True):
        playlist = _programme(("bumper", "movie", "system"))
        schedule = _running_screening(playlist.programme) if screening else None
        service = _service(playlist)
        service._programme_cursor = 1
        service._live["time"] = 3733.0
        service.controller.get_playlist.return_value = [STANDBY]
        service._reconcile()
        return service, playlist, schedule

    def test_a_programme_lost_on_air_is_offered_back(self):
        service, playlist, schedule = self._lost()
        assert service.interrupted["order"] == 1 and service.interrupted["seconds"] == 3733.0
        assert service.interrupted["schedule_id"] == schedule.id

    def test_the_status_offers_resume_and_dismiss_on_standby(self, monkeypatch):
        from cinefin.api.services import playout_service

        service, playlist, _ = self._lost()
        monkeypatch.setattr(playout_service, "PlayoutHost", MagicMock(get_active=lambda: None))
        info = playout_service._interrupted(service.interrupted)
        assert (info.programme_name, info.position, info.seconds) == (playlist.programme.name, 1, 3733.0)
        assert {"recover", "dismiss"} <= set(playout_service.allowed_actions("standby", False, True))
        assert "recover" not in playout_service.allowed_actions("playing", False, True)

    def test_resume_plays_on_from_the_item_and_second(self, monkeypatch):
        service, playlist, schedule = self._lost()

        def load(programme):
            service.current_programme, service.current_playlist, service.playlist_offset = programme, playlist, 1
            service.interrupted = None
            return True

        service.load_programme = load
        service._leave_standby = MagicMock()
        seeks = []
        service._seek_once_loaded = lambda index, seconds: seeks.append((index, seconds))
        monkeypatch.setattr("threading.Thread", lambda target, args, daemon: MagicMock(start=lambda: target(*args)))
        service.controller.play.return_value = True
        assert service.resume_interrupted() is True
        service._leave_standby.assert_called_once()
        assert service._leave_standby.call_args.args[0] == 2  # offset 1 + item 1
        assert seeks == [(2, 3733.0)]
        assert service.programme_state == ProgrammeState.RUNNING and service._programme_cursor == 1
        assert service.interrupted is None
        schedule.refresh_from_db()
        assert schedule.status == "running" and schedule.last_error == ""

    def test_dismiss_forgets_it(self):
        service, _, _ = self._lost(screening=False)
        service.dismiss_interrupted()
        assert service.interrupted is None

    def test_cueing_something_else_forgets_it(self):
        service, _, _ = self._lost(screening=False)
        service._ensure_standby = MagicMock(return_value=False)
        service.load_programme(ProgrammeFactory())
        assert service.interrupted is None

    def test_a_restart_that_lost_a_running_programme_offers_it_from_the_item_start(self):
        playlist = _programme()
        _persist(playlist)
        session = PlayoutSession.load()
        session.programme_cursor = 1
        session.save()
        service = _service()
        service._session_restored = False
        service.controller.get_playlist.return_value = [STANDBY]
        service._restore_session()
        assert service.interrupted["order"] == 1 and service.interrupted["seconds"] is None
