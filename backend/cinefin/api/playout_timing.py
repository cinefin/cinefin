"""
Pure playout timing decisions — no I/O, no sleeping, no Django.

The MPV service's trickiest behaviour is *when* things happen: how long a
hold-black command item keeps the screen, which command cues fire on a
playlist jump, when a credits marker triggers. Historically those decisions
lived inline in ``mpv_service`` between controller round-trips and
``time.sleep`` calls, which made them impossible to test without a live
player. This module owns the decisions; ``mpv_service`` owns the I/O and
feeds observations in. Everything here is deterministic and unit-tested
exhaustively in ``tests/test_playout_timing.py``.
"""

# HoldDwell.tick() verdicts.
CONTINUE = "continue"  # keep holding
ABORT = "abort"  # stop silently: programme stopped or the operator moved on
TIMEOUT = "timeout"  # overtime exhausted with the command still running — advance anyway


def cue_window(previous_order, new_order):
    """The half-open order range ``(gt, lte]`` of command cues to fire when the
    programme cursor moves from ``previous_order`` to ``new_order``.

    Cue policy (see the handbook in ``_handle_playlist_change``): moving
    forward fires every cue passed over — a jump that skips items still fires
    their cues, in order. Moving backward (or not moving) fires nothing; the
    cues re-fire when playback passes them again. Returns ``None`` when
    nothing should fire.
    """
    if new_order is None or previous_order is None or new_order <= previous_order:
        return None
    return (previous_order, new_order)


def credits_due(time_pos, credits_marker):
    """True when playback has reached a movie's credits marker.

    A marker of 0 (or negative) means "no marker set". Comparison is on whole
    seconds, matching the marker's resolution.
    """
    if time_pos is None or not credits_marker or credits_marker <= 0:
        return False
    return int(time_pos) >= credits_marker


class HoldDwell:
    """The clock for one hold-black command item.

    A hold keeps the looping black clip on screen until the command has
    finished AND at least ``duration`` seconds of unpaused screen time have
    passed — the duration is a minimum dwell, not a cap. A command that
    outlives its dwell gets ``overtime`` further seconds before the hold gives
    up and advances anyway (the backstop for a runner thread that never
    signals).

    The service loop drives this with observations::

        dwell = HoldDwell(duration=cmd.duration, overtime=TIMEOUT_SECONDS + 5)
        while not dwell.satisfied(command_done):
            time.sleep(TICK)
            verdict = dwell.tick(TICK, running=..., on_item=..., paused=...,
                                 command_done=...)
            ...

    ``tick`` mutates the clock and returns a verdict:

    - :data:`CONTINUE` — keep holding;
    - :data:`ABORT` — the programme stopped or playback left the hold's
      playlist entry (operator skipped): stop holding, do NOT advance;
    - :data:`TIMEOUT` — overtime exhausted with the command still running:
      stop holding and advance anyway.

    Pause-awareness: while paused, neither the dwell nor the overtime clock
    runs — a paused auditorium doesn't burn hold time.
    """

    def __init__(self, duration, overtime):
        self.duration = max(float(duration or 0.0), 0.0)
        self.overtime = float(overtime)
        self.elapsed = 0.0  # unpaused seconds spent inside the dwell
        self._overtime_used = 0.0  # unpaused seconds spent past the dwell

    def satisfied(self, command_done):
        """True when the hold may end normally: dwell served and command done."""
        return self.elapsed >= self.duration and command_done

    def tick(self, dt, *, running, on_item, paused, command_done):
        """Advance the clock by ``dt`` seconds of wall time and decide."""
        if not running or not on_item:
            return ABORT
        if not paused:
            if self.elapsed < self.duration:
                self.elapsed += dt
            elif not command_done:
                self._overtime_used += dt
                if self._overtime_used >= self.overtime:
                    return TIMEOUT
        return CONTINUE

    @property
    def progress(self):
        """``{'duration', 'elapsed'}`` for status surfaces (elapsed capped)."""
        return {"duration": self.duration, "elapsed": min(self.elapsed, self.duration)}
