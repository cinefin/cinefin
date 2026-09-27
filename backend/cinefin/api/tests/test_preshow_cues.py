"""The lead-in: the ordered pre-show sequence, the runner's play-time handling, and overlap checks."""

import threading
from datetime import timedelta

import pytest
from django.utils import timezone

from cinefin.api.models import ProgrammeSchedule, Settings
from cinefin.api.services import command_runner, preshow, schedule_runner

from .factories import CommandFactory, PlaylistFactory, ProgrammeFactory, ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db

API = "/api/v2"


class TestSteps:
    def test_cue_is_prepended_when_absent_and_legacy_entries_read_as_commands(self):
        a, b = CommandFactory(), CommandFactory()
        Settings.set("scheduler.preshow_commands", [{"command": a.id, "lead": 120}, b.id])
        assert preshow.steps() == [preshow.CUE, a.id, b.id]

    def test_cue_position_is_kept(self):
        a, b = CommandFactory(), CommandFactory()
        Settings.set("scheduler.preshow_commands", [{"command": a.id}, {"cue": True}, {"command": b.id}])
        assert preshow.steps() == [a.id, preshow.CUE, b.id]
        assert preshow.command_ids() == [a.id, b.id]

    def test_duplicates_and_garbage_are_ignored(self):
        a = CommandFactory()
        Settings.set(
            "scheduler.preshow_commands",
            [True, {"lead": 5}, "x", {"cue": True}, {"cue": True}, {"command": a.id}, a.id],
        )
        assert preshow.steps() == [preshow.CUE, a.id]


class TestRun:
    def test_runs_commands_and_cue_in_list_order(self, monkeypatch):
        events = []
        monkeypatch.setattr(command_runner, "execute", lambda command, trigger, wait: events.append(command.name))
        monkeypatch.setattr(preshow, "_load", lambda programme: events.append("cue") or True)
        restart, av = CommandFactory(name="Restart mpv"), CommandFactory(name="AV up")
        Settings.set(
            "scheduler.preshow_commands",
            [{"command": restart.id}, {"cue": True}, {"command": av.id}, {"command": 9999}],
        )
        programme = PlaylistFactory().programme

        preshow.run(programme)
        assert events == ["Restart mpv", "cue", "AV up"]

    def test_a_command_holds_for_its_duration(self, monkeypatch):
        slept = []
        monkeypatch.setattr(command_runner, "execute", lambda *a, **kw: None)
        monkeypatch.setattr(preshow.time, "sleep", slept.append)
        preshow._run_command(CommandFactory(duration=20))
        assert slept and 19 < slept[0] <= 20

    def test_cue_retries_while_the_player_comes_back(self, monkeypatch):
        answers = iter([False, False, True])
        monkeypatch.setattr(preshow, "_load", lambda programme: next(answers))
        monkeypatch.setattr(preshow.time, "sleep", lambda s: None)
        preshow._cue(PlaylistFactory().programme)  # no raise: the third attempt loads


class TestRunner:
    @pytest.fixture(autouse=True)
    def _free_lock(self):
        yield
        if preshow.lock.locked():
            preshow.lock.release()

    def test_row_is_due_when_its_lead_in_begins(self, monkeypatch):
        monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: False)
        spawned = []
        monkeypatch.setattr(schedule_runner, "_spawn", spawned.append)
        s = ProgrammeScheduleFactory(start_time=timezone.now() - timedelta(seconds=5), lead_in=600)

        assert schedule_runner.tick()["fired"] == 1
        assert [x.id for x in spawned] == [s.id]

    def test_execute_waits_for_the_play_time(self, monkeypatch):
        import cinefin.api.mpv_service as mpv_module

        monkeypatch.setattr(preshow, "run", lambda programme: None)
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda: True, raising=False)
        slept = []
        monkeypatch.setattr(schedule_runner.time, "sleep", slept.append)
        s = ProgrammeScheduleFactory(start_time=timezone.now(), lead_in=600, status="running")

        schedule_runner.execute_schedule(s)
        assert slept and 590 < slept[0] <= 600

    def test_a_late_lead_in_still_plays_on_time(self, monkeypatch):
        """Player freed 5 min into a 10 min lead-in: the programme still plays at the planned time."""
        import cinefin.api.mpv_service as mpv_module

        monkeypatch.setattr(preshow, "run", lambda programme: None)
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda: True, raising=False)
        slept = []
        monkeypatch.setattr(schedule_runner.time, "sleep", slept.append)
        s = ProgrammeScheduleFactory(start_time=timezone.now() - timedelta(minutes=5), lead_in=600, status="running")

        schedule_runner.execute_schedule(s)
        assert slept and 290 < slept[0] <= 300

    def test_removed_during_lead_in_does_not_start(self, monkeypatch):
        import cinefin.api.mpv_service as mpv_module

        monkeypatch.setattr(preshow, "run", lambda programme: None)
        monkeypatch.setattr(schedule_runner.time, "sleep", lambda s: None)
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda: pytest.fail("must not start"))
        s = ProgrammeScheduleFactory(start_time=timezone.now(), lead_in=60, status="running")
        ProgrammeSchedule.objects.filter(id=s.id).delete()

        schedule_runner.execute_schedule(s)

    def test_deferred_while_another_lead_in_runs(self, monkeypatch):
        monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: False)
        monkeypatch.setattr(schedule_runner, "_spawn", lambda s: pytest.fail("must wait"))
        s = ProgrammeScheduleFactory(start_time=timezone.now() - timedelta(seconds=5))
        preshow.lock.acquire()

        assert schedule_runner.tick()["fired"] == 0
        s.refresh_from_db()
        assert s.status == "scheduled"

    def test_missed_is_judged_on_the_play_time(self, monkeypatch):
        monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: True)
        # Lead-in began 20 min ago but the programme plays in 10: still in time, not missed.
        s = ProgrammeScheduleFactory(start_time=timezone.now() - timedelta(minutes=20), lead_in=1800)
        schedule_runner.tick()
        s.refresh_from_db()
        assert s.status == "scheduled"


class TestLengthAndOverlap:
    def test_length_includes_the_lead_in(self):
        Settings.set("scheduler.lead_in", 600)
        start = timezone.now() + timedelta(hours=1)
        s = ProgrammeScheduleFactory(start_time=start, runtime=90)
        assert s.play_time() == start + timedelta(minutes=10)
        assert s.end_time() == start + timedelta(minutes=100)
        s.lead_in = 0  # a per-screening override wins over the default
        assert s.end_time() == start + timedelta(minutes=90)

    def test_list_reports_play_time_and_default(self, client):
        Settings.set("scheduler.lead_in", 300)
        s = ProgrammeScheduleFactory(start_time=timezone.now() + timedelta(hours=1))
        data = client.get(f"{API}/schedules/list").json()["data"]
        assert data["default_lead_in"] == 300
        row = next(r for r in data["schedules"] if r["id"] == s.id)
        assert row["lead_in"] is None
        assert row["play_time"] == (s.start_time + timedelta(seconds=300)).isoformat()

    def test_overlap_with_the_lead_in_is_rejected(self, client):
        start = timezone.now().replace(microsecond=0) + timedelta(days=1)
        ProgrammeScheduleFactory(start_time=start, runtime=60, lead_in=600)  # occupies start → +70 min
        programme = ProgrammeFactory()
        new_start = (start + timedelta(minutes=65)).astimezone(timezone.UTC).replace(tzinfo=None).isoformat()
        r = client.post(
            f"{API}/schedules/create",
            data={"programme_id": programme.id, "start_time": new_start, "timezone": "UTC"},
            content_type="application/json",
        )
        assert r.status_code == 409


class TestManualLeadIn:
    @pytest.fixture(autouse=True)
    def _free_lock(self):
        yield
        if preshow.lock.locked():
            preshow.lock.release()

    def test_starts_the_sequence(self, client, monkeypatch):
        ran = []
        monkeypatch.setattr(preshow, "run", ran.append)

        class Inline:
            def __init__(self, target, **kw):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(threading, "Thread", Inline)
        programme = ProgrammeFactory()
        r = client.post(f"{API}/playout/lead-in", data={"programme_id": programme.id}, content_type="application/json")
        assert r.status_code == 200
        assert [p.id for p in ran] == [programme.id]
        assert not preshow.lock.locked()

    def test_refused_while_one_is_running(self, client):
        preshow.lock.acquire()
        r = client.post(
            f"{API}/playout/lead-in", data={"programme_id": ProgrammeFactory().id}, content_type="application/json"
        )
        assert r.status_code == 409
