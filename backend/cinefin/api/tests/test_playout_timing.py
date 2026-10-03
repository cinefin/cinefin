import pytest

from cinefin.api.playout_timing import ABORT, CONTINUE, TIMEOUT, HoldDwell, credits_due, cue_window


@pytest.mark.parametrize(
    ("cursor", "pos", "window"),
    [(0, 1, (0, 1)), (1, 5, (1, 5)), (-1, 0, (-1, 0)), (4, 2, None), (3, 3, None), (None, 3, None), (3, None, None)],
)
def test_cue_window(cursor, pos, window):
    assert cue_window(cursor, pos) == window


@pytest.mark.parametrize(
    ("time", "marker", "due"),
    [
        (120.0, 120, True),
        (500.9, 120, True),
        (119.9, 120, False),
        (119.999, 120, False),
        (500.0, 0, False),
        (500.0, None, False),
        (None, 120, False),
    ],
)
def test_credits_due(time, marker, due):
    assert credits_due(time, marker) is due


def run_dwell(dwell, ticks, command_done_after=None):
    wall = 0.0
    for n in range(1, ticks + 1):
        if dwell.satisfied(command_done_after is None or wall >= command_done_after):
            return "satisfied", n - 1
        wall += 0.25
        done = command_done_after is None or wall >= command_done_after
        verdict = dwell.tick(0.25, running=True, on_item=True, paused=False, command_done=done)
        if verdict != CONTINUE:
            return verdict, n
    return "ran-out", ticks


class TestHoldDwell:
    @pytest.mark.parametrize(
        ("duration", "overtime", "done_after", "result"),
        [
            (2.0, 35.0, None, ("satisfied", 8)),  # the duration is a minimum dwell
            (0, 35.0, None, ("satisfied", 0)),
            (1.0, 35.0, 3.0, ("satisfied", 12)),  # a slow command extends past it
            (1.0, 2.0, 10_000, (TIMEOUT, 12)),  # the overtime backstop advances a stuck command
        ],
    )
    def test_dwell(self, duration, overtime, done_after, result):
        assert run_dwell(HoldDwell(duration, overtime=overtime), 1000, done_after) == result

    @pytest.mark.parametrize(("running", "on_item"), [(False, True), (True, False)], ids=["stopped", "skipped"])
    def test_aborts(self, running, on_item):
        assert (
            HoldDwell(5.0, overtime=35.0).tick(0.25, running=running, on_item=on_item, paused=False, command_done=False)
            == ABORT
        )

    def test_pause_freezes_both_clocks(self):
        dwell = HoldDwell(1.0, overtime=35.0)
        for _ in range(100):
            assert dwell.tick(0.25, running=True, on_item=True, paused=True, command_done=True) == CONTINUE
        assert dwell.elapsed == 0.0 and not dwell.satisfied(True)

        dwell = HoldDwell(0.25, overtime=1.0)
        dwell.tick(0.25, running=True, on_item=True, paused=False, command_done=False)
        for _ in range(100):
            dwell.tick(0.25, running=True, on_item=True, paused=True, command_done=False)
        verdicts = [dwell.tick(0.25, running=True, on_item=True, paused=False, command_done=False) for _ in range(4)]
        assert verdicts[-1] == TIMEOUT

    def test_progress_caps_at_the_duration_and_bad_durations_are_zero(self):
        dwell = HoldDwell(1.0, overtime=35.0)
        for _ in range(10):
            dwell.tick(0.25, running=True, on_item=True, paused=False, command_done=False)
        assert dwell.progress == {"duration": 1.0, "elapsed": 1.0}
        assert HoldDwell(None, overtime=1.0).duration == HoldDwell(-3, overtime=1.0).duration == 0.0
