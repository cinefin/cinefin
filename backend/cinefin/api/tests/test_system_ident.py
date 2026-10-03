import struct

from cinefin.api.utils.assets import SYSTEM_IDENT_LOOP, system_ident_path


def _mp4_duration(path: str) -> float:
    """Movie duration from the mp4's mvhd box (moov is at the front: +faststart)."""
    with open(path, "rb") as f:
        data = f.read(1 << 20)
    i = data.index(b"mvhd")
    version = data[i + 4]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", data[i + 24 : i + 36])
    else:
        timescale, duration = struct.unpack(">II", data[i + 16 : i + 24])
    return duration / timescale


def test_loop_range_is_the_intro_then_a_30s_hold():
    start, end = SYSTEM_IDENT_LOOP
    assert (start, end) == (4.0, 34.0)
    assert end - start == 30.0


def test_bundled_ident_ends_at_the_loop_end():
    assert abs(_mp4_duration(system_ident_path()) - SYSTEM_IDENT_LOOP[1]) < 0.05
