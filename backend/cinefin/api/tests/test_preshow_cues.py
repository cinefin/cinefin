"""Pre-show cue parsing, at-start firing, and the schedule runner's lead-time pre-fire."""

from datetime import timedelta

import pytest
from django.utils import timezone

from cinefin.api.models import Settings
from cinefin.api.services import command_runner, preshow, schedule_runner

from .factories import CommandFactory, ProgrammeFactory, ProgrammeScheduleFactory

pytestmark = pytest.mark.django_db


class TestCueParsing:
    def test_objects_and_legacy_ints_both_parse(self):
        a, b = CommandFactory(), CommandFactory()
        Settings.set("scheduler.preshow_commands", [{"command": a.id, "lead": 120}, b.id])
        assert preshow.cues() == [(a.id, 120), (b.id, 0)]
        assert preshow.command_ids() == [a.id, b.id]

    def test_advance_cues_are_lead_positive_earliest_first(self):
        a, b, c = CommandFactory(), CommandFactory(), CommandFactory()
        Settings.set(
            "scheduler.preshow_commands",
            [{"command": a.id, "lead": 30}, {"command": b.id, "lead": 0}, {"command": c.id, "lead": 120}],
        )
        assert preshow.advance_cues() == [(c.id, 120), (a.id, 30)]

    def test_garbage_entries_are_ignored(self):
        Settings.set("scheduler.preshow_commands", [True, {"lead": 5}, "x", {"command": "y"}])
        assert preshow.cues() == []


class TestAtStartFiring:
    def test_only_lead_zero_cues_fire_at_start(self, monkeypatch):
        fired = []
        monkeypatch.setattr(
            command_runner, "execute_many_sequential", lambda commands, trigger: fired.append(list(commands))
        )
        at_start, advance = CommandFactory(), CommandFactory()
        Settings.set(
            "scheduler.preshow_commands",
            [{"command": advance.id, "lead": 90}, {"command": at_start.id, "lead": 0}],
        )
        preshow.fire_at_start()
        assert fired == [[at_start]]

    def test_fire_all_fires_every_cue_in_order(self, monkeypatch):
        fired = []
        monkeypatch.setattr(
            command_runner, "execute_many_sequential", lambda commands, trigger: fired.append(list(commands))
        )
        a, b = CommandFactory(), CommandFactory()
        Settings.set("scheduler.preshow_commands", [{"command": a.id, "lead": 90}, {"command": b.id, "lead": 0}])
        assert preshow.fire_all() == 2
        assert fired == [[a, b]]


class TestRunnerPrefire:
    def _capture(self, monkeypatch):
        fired = []
        monkeypatch.setattr(command_runner, "execute_many_sequential", lambda commands, trigger: fired.extend(commands))
        schedule_runner._prefired.clear()
        return fired

    def test_advance_cue_fires_once_inside_its_lead_window(self, monkeypatch):
        fired = self._capture(monkeypatch)
        cmd = CommandFactory()
        Settings.set("scheduler.preshow_commands", [{"command": cmd.id, "lead": 120}])
        # Start in 90s: inside the 120s lead window, so the cue is due.
        ProgrammeScheduleFactory(programme=ProgrammeFactory(), start_time=timezone.now() + timedelta(seconds=90))

        schedule_runner.tick()
        assert fired == [cmd]
        # A second tick must not refire it.
        schedule_runner.tick()
        assert fired == [cmd]

    def test_advance_cue_waits_until_its_lead_window(self, monkeypatch):
        fired = self._capture(monkeypatch)
        cmd = CommandFactory()
        Settings.set("scheduler.preshow_commands", [{"command": cmd.id, "lead": 30}])
        # Start in 10 minutes: the 30s lead hasn't arrived, so nothing fires yet.
        ProgrammeScheduleFactory(programme=ProgrammeFactory(), start_time=timezone.now() + timedelta(minutes=10))

        schedule_runner.tick()
        assert fired == []

    def test_lead_zero_cue_never_prefires(self, monkeypatch):
        fired = self._capture(monkeypatch)
        cmd = CommandFactory()
        Settings.set("scheduler.preshow_commands", [{"command": cmd.id, "lead": 0}])
        ProgrammeScheduleFactory(programme=ProgrammeFactory(), start_time=timezone.now() + timedelta(seconds=5))

        schedule_runner.tick()
        assert fired == []
