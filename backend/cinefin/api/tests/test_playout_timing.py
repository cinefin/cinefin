from cinefin.api import playout_timing
from cinefin.api.playout_timing import ABORT, CONTINUE, TIMEOUT, HoldDwell, credits_due, cue_window


class TestCueWindow:
    def test_forward_move_fires_the_passed_range(self):
        assert cue_window(0, 1) == (0, 1)

    def test_forward_jump_fires_every_skipped_cue(self):
        assert cue_window(1, 5) == (1, 5)

    def test_from_preshow_cursor(self):
        assert cue_window(-1, 0) == (-1, 0)

    def test_backward_move_fires_nothing(self):
        assert cue_window(4, 2) is None

    def test_no_move_fires_nothing(self):
        assert cue_window(3, 3) is None

    def test_none_positions_fire_nothing(self):
        assert cue_window(None, 3) is None
        assert cue_window(3, None) is None


class TestCreditsDue:
    def test_due_at_marker(self):
        assert credits_due(120.0, 120) is True

    def test_due_past_marker(self):
        assert credits_due(500.9, 120) is True

    def test_not_due_before_marker(self):
        assert credits_due(119.9, 120) is False

    def test_whole_second_comparison(self):
        assert credits_due(119.999, 120) is False

    def test_no_marker_never_due(self):
        assert credits_due(500.0, 0) is False
        assert credits_due(500.0, None) is False

    def test_no_time_never_due(self):
        assert credits_due(None, 120) is False


def run_dwell(dwell, ticks, *, running=True, on_item=True, paused=False, command_done_after=None):
    wall = 0.0
    for n in range(1, ticks + 1):
        done = command_done_after is None or wall >= command_done_after
        if dwell.satisfied(done):
            return ("satisfied", n - 1)
        wall += 0.25
        done = command_done_after is None or wall >= command_done_after
        verdict = dwell.tick(0.25, running=running, on_item=on_item, paused=paused, command_done=done)
        if verdict != CONTINUE:
            return (verdict, n)
    return (
        "satisfied" if dwell.satisfied(command_done_after is None or wall >= command_done_after) else "ran-out",
        ticks,
    )


class TestHoldDwell:
    def test_duration_is_a_minimum_dwell(self):
        dwell = HoldDwell(2.0, overtime=35.0)
        verdict, ticks = run_dwell(dwell, 100)
        assert verdict == "satisfied"
        assert ticks == 8

    def test_zero_duration_with_done_command_ends_immediately(self):
        dwell = HoldDwell(0, overtime=35.0)
        assert dwell.satisfied(True)

    def test_slow_command_extends_past_duration(self):
        dwell = HoldDwell(1.0, overtime=35.0)
        verdict, ticks = run_dwell(dwell, 100, command_done_after=3.0)
        assert verdict == "satisfied"
        assert ticks == 12

    def test_overtime_backstop_advances_a_stuck_command(self):
        dwell = HoldDwell(1.0, overtime=2.0)
        verdict, ticks = run_dwell(dwell, 1000, command_done_after=10_000)
        assert verdict == TIMEOUT
        assert ticks == 12

    def test_programme_stop_aborts(self):
        dwell = HoldDwell(5.0, overtime=35.0)
        assert dwell.tick(0.25, running=False, on_item=True, paused=False, command_done=False) == ABORT

    def test_operator_skip_aborts(self):
        dwell = HoldDwell(5.0, overtime=35.0)
        assert dwell.tick(0.25, running=True, on_item=False, paused=False, command_done=False) == ABORT

    def test_pause_freezes_the_dwell_clock(self):
        dwell = HoldDwell(1.0, overtime=35.0)
        for _ in range(100):
            assert dwell.tick(0.25, running=True, on_item=True, paused=True, command_done=True) == CONTINUE
        assert dwell.elapsed == 0.0
        assert not dwell.satisfied(True)

    def test_pause_freezes_the_overtime_clock(self):
        dwell = HoldDwell(0.25, overtime=1.0)
        dwell.tick(0.25, running=True, on_item=True, paused=False, command_done=False)
        for _ in range(100):
            assert dwell.tick(0.25, running=True, on_item=True, paused=True, command_done=False) == CONTINUE
        verdict = CONTINUE
        for _ in range(4):
            verdict = dwell.tick(0.25, running=True, on_item=True, paused=False, command_done=False)
        assert verdict == TIMEOUT

    def test_progress_caps_elapsed_at_duration(self):
        dwell = HoldDwell(1.0, overtime=35.0)
        for _ in range(10):
            dwell.tick(0.25, running=True, on_item=True, paused=False, command_done=False)
        assert dwell.progress == {"duration": 1.0, "elapsed": 1.0}

    def test_negative_or_none_duration_treated_as_zero(self):
        assert HoldDwell(None, overtime=1.0).duration == 0.0
        assert HoldDwell(-3, overtime=1.0).duration == 0.0


class TestVerdictConstants:
    def test_distinct(self):
        assert len({playout_timing.CONTINUE, playout_timing.ABORT, playout_timing.TIMEOUT}) == 3
