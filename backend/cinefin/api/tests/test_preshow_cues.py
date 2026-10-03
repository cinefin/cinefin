"""Per-screening lead-ins: the ordered steps, the runner's play-time handling, and overlap checks."""

from datetime import timedelta

import pytest
from django.utils import timezone

import cinefin.api.mpv_service as mpv_module
from cinefin.api.models import Settings
from cinefin.api.services import command_runner, preshow, schedule_runner

from .factories import CommandFactory, PlaylistFactory, ProgrammeFactory, ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db

API = "/api/v2"
CUE = preshow.CUE


@pytest.mark.parametrize(
    ("raw", "steps"),
    [
        ([{"command": 4}, {"command": 7}], [CUE, 4, 7]),  # the cue is prepended when absent
        ([], [CUE]),
        ([{"command": 4}, {"cue": True}, {"command": 7}], [4, CUE, 7]),
        ([True, {"lead": 5}, "x", 3, {"cue": True}, {"cue": True}, {"command": 4}, {"command": 4}], [CUE, 4]),
    ],
)
def test_steps(raw, steps):
    assert preshow.steps(raw) == steps


def test_clean_drops_unknown_commands_and_a_new_screening_is_cue_only():
    a = CommandFactory()
    assert preshow.clean([{"command": 9999}, {"command": a.id}]) == [{"cue": True}, {"command": a.id}]
    assert preshow.command_ids([{"command": 4}, {"cue": True}, {"command": 7}]) == [4, 7]
    assert preshow.steps(ProgrammeScheduleFactory().preshow) == [CUE]


class TestRun:
    def test_runs_commands_and_cue_in_list_order(self, monkeypatch):
        events = []
        monkeypatch.setattr(command_runner, "execute", lambda command, trigger, wait: events.append(command.name))
        monkeypatch.setattr(preshow, "_load", lambda programme: events.append("cue") or True)
        restart, av = CommandFactory(name="Restart mpv"), CommandFactory(name="AV up")
        preshow.run(
            PlaylistFactory().programme, [{"command": restart.id}, {"cue": True}, {"command": av.id}, {"command": 9999}]
        )
        assert events == ["Restart mpv", "cue", "AV up"]

    def test_a_command_holds_for_its_duration(self, monkeypatch):
        slept = []
        monkeypatch.setattr(command_runner, "execute", lambda *a, **kw: None)
        monkeypatch.setattr(preshow.time, "sleep", slept.append)
        preshow._run_command(CommandFactory(duration=20))
        assert slept and 19 < slept[0] <= 20


class TestRunner:
    @pytest.fixture(autouse=True)
    def _free_lock(self):
        yield
        if preshow.lock.locked():
            preshow.lock.release()

    @pytest.fixture
    def execute(self, monkeypatch):
        """Run execute_schedule with the lead-in stubbed; returns (sleeps, steps run, starts)."""
        slept, ran, started = [], [], []
        monkeypatch.setattr(preshow, "run", lambda programme, steps: ran.append(steps))
        monkeypatch.setattr(mpv_module.mpv_service, "start_programme", lambda: started.append(1) or True, raising=False)
        monkeypatch.setattr(schedule_runner.time, "sleep", slept.append)

        def run(schedule):
            schedule_runner.execute_schedule(schedule)
            return slept, ran, started

        return run

    def test_row_is_due_when_its_lead_in_begins(self, monkeypatch):
        monkeypatch.setattr(schedule_runner, "_mpv_busy", lambda: False)
        spawned = []
        monkeypatch.setattr(schedule_runner, "_spawn", spawned.append)
        s = ProgrammeScheduleFactory(start_time=timezone.now() - timedelta(seconds=5), lead_in=600)
        assert schedule_runner.tick()["fired"] == 1
        assert [x.id for x in spawned] == [s.id]

    @pytest.mark.parametrize(("began_ago", "wait"), [(0, 600), (300, 300)], ids=["on-time", "late-lead-in"])
    def test_plays_at_the_play_time(self, execute, began_ago, wait):
        s = ProgrammeScheduleFactory(
            start_time=timezone.now() - timedelta(seconds=began_ago), lead_in=600, status="running"
        )
        slept, _, started = execute(s)
        assert slept and wait - 10 < slept[0] <= wait and started

    def test_runs_the_screenings_own_steps(self, execute):
        steps = [{"command": CommandFactory().id}, {"cue": True}]
        s = ProgrammeScheduleFactory(start_time=timezone.now(), preshow=steps, status="running")
        assert execute(s)[1] == [steps]

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


def _utc(dt):
    return dt.astimezone(timezone.UTC).replace(tzinfo=None, microsecond=0).isoformat()


class TestScheduleApi:
    def test_create_and_list_carry_the_steps(self, client):
        cmd, programme = CommandFactory(), ProgrammeFactory()
        body = {
            "programme_id": programme.id,
            "start_time": _utc(timezone.now() + timedelta(days=2)),
            "timezone": "UTC",
            "lead_in": 300,
            "preshow": [{"command": cmd.id}, {"cue": True}, {"command": 9999}],
        }
        assert client.post(f"{API}/schedules/create", data=body, content_type="application/json").status_code == 201
        rows = client.get(f"{API}/schedules/list").json()["data"]["schedules"]
        row = next(r for r in rows if r["programme"]["id"] == programme.id)
        assert row["lead_in"] == 300
        assert row["preshow"] == [{"command": cmd.id, "cue": False}, {"command": None, "cue": True}]

    def test_overlap_with_the_lead_in_is_rejected(self, client):
        start = timezone.now().replace(microsecond=0) + timedelta(days=1)
        ProgrammeScheduleFactory(start_time=start, runtime=60, lead_in=600)  # occupies start to +70 min
        body = {
            "programme_id": ProgrammeFactory().id,
            "start_time": _utc(start + timedelta(minutes=65)),
            "timezone": "UTC",
        }
        assert client.post(f"{API}/schedules/create", data=body, content_type="application/json").status_code == 409


def test_migration_retires_the_global_scheduler_settings():
    # The null -> global lead-in copy runs against the pre-migration schema; only the clean-up is testable.
    import importlib

    from django.apps import apps

    migration = importlib.import_module("cinefin.api.migrations.0046_per_screening_lead_in")
    Settings.objects.update_or_create(id=1, defaults={"data": {"scheduler": {"lead_in": 600}, "cinema": {}}})
    migration.adopt_global_lead_in(apps, None)
    assert Settings.objects.get(id=1).data == {"cinema": {}}
