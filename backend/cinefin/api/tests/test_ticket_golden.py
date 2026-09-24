"""Golden-file regression tests for ticket rendering."""

import datetime as dt
import json
import os
from pathlib import Path

import pytest
from django.conf import settings as django_settings
from django.utils import timezone as djtz
from escpos.printer import Dummy
from PIL import Image

from cinefin.api.models import Settings
from cinefin.api.services import ticket_service

pytestmark = pytest.mark.django_db

GOLDEN_DIR = Path(__file__).parent / "golden" / "tickets"

REGEN_HINT = (
    "Golden mismatch for {name}. If this change to the ticket renderer is intentional, regenerate with:\n"
    "  UPDATE_GOLDEN=1 poetry run pytest cinefin/api/tests/test_ticket_golden.py\n"
    "then review the diff of cinefin/api/tests/golden/tickets/ and commit it."
)


def assert_matches_golden(name: str, content: str) -> None:
    path = GOLDEN_DIR / name
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return
    assert path.exists(), f"Missing golden file {path}.\n{REGEN_HINT.format(name=name)}"
    assert content == path.read_text(), REGEN_HINT.format(name=name)


FULL_DESIGN = [
    {"type": "image", "file": "logo.png"},
    {"type": "text", "content": "{cinema}", "size": "large", "bold": True},
    {"type": "rule"},
    {"type": "text", "content": "ADMIT ONE", "invert": True},
    {"type": "text", "content": "{programme}", "size": "wide", "bold": True},
    {"type": "text", "content": "{film}"},
    {"type": "text", "content": "{film_list}", "align": "left"},
    {"type": "rating", "scale": "large"},
    {"type": "text", "content": "Seat {seat}", "size": "tall", "align": "right"},
    {"type": "text", "content": "{date} {time}"},
    {"type": "text", "content": "Show: {showtime}"},
    {"type": "spacer", "lines": 2},
    {"type": "barcode", "content": "T{ticket_no}"},
    {"type": "qr", "mode": "content", "content": "https://tickets.example/check/{ticket_no}", "size": 4},
    {"type": "qr", "mode": "fun", "size": 6},
    {"type": "text", "content": "Ticket #{ticket_no}"},
    {"type": "rule", "align": "left"},
]

# 14 March 2026 is outside BST, so Europe/London localtime == the naive value.
FIXED_WHEN = dt.datetime(2026, 3, 14, 19, 30)

SINGLE_FEATURE = [{"title": "The Third Man", "year": 1949, "certification": "PG"}]
TRIPLE_FEATURE = [
    {"title": "The Third Man", "year": 1949, "certification": "PG"},
    {"title": "Brief Encounter", "year": 1945, "certification": "12A"},
    {"title": "Get Carter", "year": 1971, "certification": "15"},
]


@pytest.fixture
def pinned_settings():
    Settings.set("cinema.name", "The Regal")
    Settings.set("tickets.qr_fun_links", ["https://cinefin.example/fun"])  # one link -> deterministic choice
    Settings.set("tickets.date_format", "%d/%m/%Y")
    Settings.set("tickets.time_format", "%H:%M")
    Settings.set("tickets.paper_width", 384)
    Settings.set("tickets.image_mode", "raster")
    Settings.set("tickets.feed_lines", 2)


def _ctx(features, *, scheduled: bool, programme_name: str, ticket_no: int, seat: str) -> dict:
    return ticket_service.make_ticket_context(
        seat=seat,
        when=djtz.make_aware(FIXED_WHEN),
        scheduled=scheduled,
        ticket_no=ticket_no,
        programme_name=programme_name,
        features=features,
    )


def _normalised_ops_json(ops: list[dict]) -> str:
    prefixes = [
        (str(django_settings.CINEFIN_ASSETS_DIR), "<ASSETS>"),
        (str(django_settings.MEDIA_ROOT), "<MEDIA>"),
    ]
    normalised = []
    for op in ops:
        op = dict(op)
        for prefix, placeholder in prefixes:
            if "path" in op and op["path"].startswith(prefix):
                op["path"] = placeholder + op["path"][len(prefix) :]
        normalised.append(op)
    return json.dumps(normalised, indent=2, sort_keys=True) + "\n"


class TestRenderOpsGolden:
    @pytest.fixture(autouse=True)
    def _pin(self, pinned_settings, settings, tmp_path):
        settings.MEDIA_ROOT = str(tmp_path)
        images = tmp_path / "ticket_images"
        images.mkdir(parents=True, exist_ok=True)
        _bw_png(images / "logo.png", 96, 40)

    def test_single_feature_scheduled(self):
        ctx = _ctx(SINGLE_FEATURE, scheduled=True, programme_name="Noir Night", ticket_no=101, seat="C4")
        elements = ticket_service.validate_elements(FULL_DESIGN)
        ops = ticket_service.render_ticket_ops(elements, ctx)
        assert_matches_golden("ops_full_design_single_feature.json", _normalised_ops_json(ops))

    def test_triple_feature_unscheduled(self):
        ctx = _ctx(TRIPLE_FEATURE, scheduled=False, programme_name="Brit Grit Triple", ticket_no=202, seat="J12")
        elements = ticket_service.validate_elements(FULL_DESIGN)
        ops = ticket_service.render_ticket_ops(elements, ctx)
        assert_matches_golden("ops_full_design_triple_feature.json", _normalised_ops_json(ops))


def _bw_png(path: Path, width: int, height: int) -> str:
    # Pure 0/255 pixels narrower than the print target avoid dithering/resample,
    # so the golden bytes can't drift with the Pillow version.
    img = Image.new("L", (width, height), 255)
    px = img.load()
    for x in range(width):
        if (x // 2) % 2 == 0:
            for y in range(height):
                px[x, y] = 0
    img.save(path)
    return str(path)


class TestEscposByteGolden:
    def test_full_design_byte_stream(self, monkeypatch, settings, tmp_path, pinned_settings):
        settings.MEDIA_ROOT = str(tmp_path)

        device = tmp_path / "printer-device"
        device.write_bytes(b"")
        Settings.set("tickets.printer_device", str(device))

        images = tmp_path / "ticket_images"
        images.mkdir(parents=True)
        _bw_png(images / "logo.png", 96, 40)
        override_dir = tmp_path / "pos" / "bbfc"
        override_dir.mkdir(parents=True)
        _bw_png(override_dir / "PG.png", 64, 64)

        dummy = Dummy(profile=ticket_service.PRINTER_PROFILES[384])
        monkeypatch.setattr(ticket_service, "open_printer", lambda: dummy)

        ctx = _ctx(SINGLE_FEATURE, scheduled=True, programme_name="Noir Night", ticket_no=101, seat="C4")
        ticket_service.print_ticket(FULL_DESIGN, ctx)

        stream = dummy.output
        assert stream.startswith(b"\x1b@"), "every ticket must start with ESC @ (hw INIT)"

        hexdump = "\n".join(stream.hex()[i : i + 64] for i in range(0, len(stream.hex()), 64)) + "\n"
        assert_matches_golden("escpos_full_design_single_feature.hex", hexdump)
