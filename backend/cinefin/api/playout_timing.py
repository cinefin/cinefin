"""Pure playout timing decisions (no I/O, no sleeping, no Django): how long a
hold-black command item keeps the screen, which cues fire on a jump, when a
credits marker triggers. ``mpv_service`` owns the I/O and feeds observations in."""

# HoldDwell.tick() verdicts.
CONTINUE = "continue"  # keep holding
ABORT = "abort"  # stop silently: programme stopped or the operator moved on
TIMEOUT = "timeout"  # overtime exhausted with the command still running: advance anyway


def cue_window(previous_order, new_order):
    """The order range ``(gt, lte]`` of command cues to fire when the cursor moves
    from ``previous_order`` to ``new_order``: moving forward fires every cue passed
    over; moving backward (or not moving) fires nothing (None)."""
    if new_order is None or previous_order is None or new_order <= previous_order:
        return None
    return (previous_order, new_order)


def credits_due(time_pos, credits_marker):
    """True when playback has reached a credits marker (0 or less = no marker),
    compared on whole seconds."""
    if time_pos is None or not credits_marker or credits_marker <= 0:
        return False
    return int(time_pos) >= credits_marker


class HoldDwell:
    """The clock for one hold-black command item.

    A hold lasts until the command has finished AND ``duration`` seconds of
    unpaused screen time have passed (a minimum dwell, not a cap). A command that
    outlives the dwell gets ``overtime`` more seconds before the hold advances
    anyway. Paused time counts towards neither clock.

    ``tick`` returns CONTINUE; ABORT when the programme stopped or playback left
    the hold's entry (do not advance); or TIMEOUT when overtime ran out (advance).
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
