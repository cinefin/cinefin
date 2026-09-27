"""Per-screening lead-ins: the ordered steps, the runner's play-time handling, and overlap checks."""

from datetime import timedelta

import pytest
from django.utils import timezone

from cinefin.api.models import ProgrammeSchedule, Settings
from cinefin.api.services import command_runner, preshow, schedule_runner

from .factories import CommandFactory, PlaylistFactory, ProgrammeFactory, ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db

API = "/api/v2"


class TestSteps:
    def test_cue_is_prepended_when_absent(self):
        assert preshow.steps([{"command": 4}, {"command": 7}]) == [preshow.CUE, 4, 7]
        assert preshow.steps([]) == [preshow.CUE]

    def test_cue_position_is_kept(self):
        raw = [{"command": 4}, {"cue": True}, {"command": 7}]
        assert preshow.steps(raw) == [4, preshow.CUE, 7]
        assert preshow.command_ids(raw) == [4, 7]

    def test_duplicates_and_garbage_are_ignored(self):
        raw = [True, {"lead": 5}, "x", 3, {"cue": True}, {"cue": True}, {"command": 4}, {"command": 4}]
        assert preshow.steps(raw) == [preshow.CUE, 4]

    def test_clean_drops_unknown_commands(self):
        a = CommandFactory()
        assert preshow.clean([{"command": 9999}, {"command": a.id}]) == [{"cue": True}, {"command": a.id}]


class TestRun:
    def test_runs_commands_and_cue_in_list_order(self, monkeypatch):
        events = []
        monkeypatch.setattr(command_runner, "execute", lambda command, trigger, wait: events.append(command.name))
        monkeypatch.setattr(preshow, "_load", lambda programme: events.append("cue") or True)
        restart, av = CommandFactory(name="Restart mpv"), CommandFactory(name="AV up")
        steps = [{"command": restart.id}, {"cue": True}, {"command": av.id}, {"command": 9999}]
        programme = PlaylistFactory().programme

        preshow.run(programme, steps)
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

        monkeypatch.setattr(preshow, "run", lambda programme, steps: None)
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda: True, raising=False)
        slept = []
        monkeypatch.setattr(schedule_runner.time, "sleep", slept.append)
        s = ProgrammeScheduleFactory(start_time=timezone.now(), lead_in=600, status="running")

        schedule_runner.execute_schedule(s)
        assert slept and 590 < slept[0] <= 600

    def test_a_late_lead_in_still_plays_on_time(self, monkeypatch):
        """Player freed 5 min into a 10 min lead-in: the programme still plays at the planned time."""
        import cinefin.api.mpv_service as mpv_module

        monkeypatch.setattr(preshow, "run", lambda programme, steps: None)
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda: True, raising=False)
        slept = []
        monkeypatch.setattr(schedule_runner.time, "sleep", slept.append)
        s = ProgrammeScheduleFactory(start_time=timezone.now() - timedelta(minutes=5), lead_in=600, status="running")

        schedule_runner.execute_schedule(s)
        assert slept and 290 < slept[0] <= 300

    def test_removed_during_lead_in_does_not_start(self, monkeypatch):
        import cinefin.api.mpv_service as mpv_module

        monkeypatch.setattr(preshow, "run", lambda programme, steps: None)
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


class TestScheduleOwnsItsLeadIn:
    def test_runner_runs_the_screenings_own_steps(self, monkeypatch):
        import cinefin.api.mpv_service as mpv_module

        ran = []
        monkeypatch.setattr(preshow, "run", lambda programme, steps: ran.append(steps))
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda: True, raising=False)
        monkeypatch.setattr(schedule_runner.time, "sleep", lambda s: None)
        steps = [{"command": CommandFactory().id}, {"cue": True}]
        s = ProgrammeScheduleFactory(start_time=timezone.now(), preshow=steps, status="running")

        schedule_runner.execute_schedule(s)
        assert ran == [steps]

    def test_length_includes_the_lead_in(self):
        start = timezone.now() + timedelta(hours=1)
        s = ProgrammeScheduleFactory(start_time=start, runtime=90, lead_in=600)
        assert s.play_time() == start + timedelta(minutes=10)
        assert s.end_time() == start + timedelta(minutes=100)

    def test_create_and_list_carry_the_steps(self, client):
        cmd, programme = CommandFactory(), ProgrammeFactory()
        start = (timezone.now() + timedelta(days=2)).astimezone(timezone.UTC).replace(tzinfo=None, microsecond=0)
        body = {
            "programme_id": programme.id,
            "start_time": start.isoformat(),
            "timezone": "UTC",
            "lead_in": 300,
            "preshow": [{"command": cmd.id}, {"cue": True}, {"command": 9999}],
        }
        assert client.post(f"{API}/schedules/create", data=body, content_type="application/json").status_code == 201
        row = next(
            r
            for r in client.get(f"{API}/schedules/list").json()["data"]["schedules"]
            if r["programme"]["id"] == programme.id
        )
        assert row["lead_in"] == 300
        assert row["preshow"] == [{"command": cmd.id, "cue": False}, {"command": None, "cue": True}]

    def test_a_new_screening_is_cue_only(self):
        assert preshow.steps(ProgrammeScheduleFactory().preshow) == [preshow.CUE]

    def test_manual_lead_in_is_gone(self, client):
        r = client.post(f"{API}/playout/lead-in", data={"programme_id": 1}, content_type="application/json")
        assert r.status_code in (404, 405)


class TestMigration:
    def test_retires_the_global_scheduler_settings(self):
        """(The null -> global lead-in copy runs against the pre-migration schema, so only the
        settings clean-up is testable here.)"""
        import importlib

        from django.apps import apps

        migration = importlib.import_module("cinefin.api.migrations.0046_per_screening_lead_in")
        Settings.objects.update_or_create(id=1, defaults={"data": {"scheduler": {"lead_in": 600}, "cinema": {}}})
        migration.adopt_global_lead_in(apps, None)
        assert Settings.objects.get(id=1).data == {"cinema": {}}


class TestOverlap:
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
