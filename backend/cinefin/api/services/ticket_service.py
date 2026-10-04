"""Ticket text generation, layout, and ESC/POS printing (a design + context -> render ops shared by print and preview)."""

import base64
import io
import logging
import os
import random
import socket
import threading

from django.conf import settings as django_settings
from django.utils import timezone
from escpos.printer import File as FilePrinter
from escpos.printer import Network as NetworkPrinter
from PIL import Image
from pydantic import ValidationError as PydanticValidationError

from cinefin.api.exceptions import ValidationError
from cinefin.api.models import Settings, TicketIssue
from cinefin.api.schemas.tickets import ELEMENTS
from cinefin.api.services import config_check_service
from cinefin.api.utils.assets import asset_path

logger = logging.getLogger(__name__)

# Serialize: concurrent prints interleave byte streams on the one printer and produce gibberish.
_print_lock = threading.Lock()

# ESC/POS capabilities profile per paper width (printable dots); 384 (48 mm) is the default.
PRINTER_PROFILES = {
    384: "ZJ-5870",  # 58 mm paper, 48 mm printable
    576: "TM-T20II",  # 80 mm paper, 72 mm printable
}
DEFAULT_PAPER_WIDTH = 384

# python-escpos image impl per tickets.image_mode (printers vary in which renders cleanly; "off" skips images):
#   raster -> GS v 0 (default), column -> ESC *, graphics -> GS ( L
IMAGE_MODES = {
    "raster": "bitImageRaster",
    "column": "bitImageColumn",
    "graphics": "graphics",
    "off": None,
}
DEFAULT_IMAGE_MODE = "raster"


def image_impl() -> str | None:
    """The escpos image impl for tickets.image_mode, or None when images are off."""
    mode = Settings.get("tickets.image_mode", DEFAULT_IMAGE_MODE)
    return IMAGE_MODES.get(mode, IMAGE_MODES[DEFAULT_IMAGE_MODE])


# Element `size` -> ESC/POS double-width/double-height styling.
_TITLE_SIZE_FLAGS = {
    "wide": {"double_width": True, "double_height": False},
    "tall": {"double_width": False, "double_height": True},
    "large": {"double_width": True, "double_height": True},
}


# Barcode symbologies: id -> (label, python-escpos name). The data each one takes is checked by barcode_data().
BARCODE_SYMBOLOGIES = {
    "code128": ("Code 128", "CODE128"),
    "code39": ("Code 39", "CODE39"),
    "ean13": ("EAN-13", "EAN13"),
    "ean8": ("EAN-8", "EAN8"),
    "upca": ("UPC-A", "UPC-A"),
    "itf": ("ITF (Interleaved 2 of 5)", "ITF"),
    "codabar": ("Codabar", "NW7"),
}
_CODE39_CHARS = set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ -.$/+%")
_CODABAR_CHARS = set("0123456789-$:/.+")
# Digits before the check digit, which the printer (or python-barcode) adds itself.
_FIXED_DIGITS = {"ean13": 12, "ean8": 7, "upca": 11}

DATE_FORMATS = ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%a %d %b %Y")
TIME_FORMATS = ("%H:%M", "%I:%M %p")

# The surprise links a new design's fun-mode QR codes pick from.
DEFAULT_QR_LINKS = (
    "https://www.youtube.com/watch?v=V14PfDDwxlE",
    "https://www.youtube.com/watch?v=8wI4jMxveyI",
    "https://www.youtube.com/watch?v=qPGYBLaF15M",
    "https://www.youtube.com/watch?v=21h0G_gU9Tw",
    "https://www.youtube.com/watch?v=k8V9vgqeUPM",
    "https://www.youtube.com/watch?v=7bXjWRXDFV8",
    "https://www.youtube.com/watch?v=ZqZdfxc-fq0",
)
QR_LINKS_MAX = 50

# Fonts a design's columns rows can be drawn in (cinefin/static/fonts/): id -> (label, file).
TICKET_FONTS = {
    "courier": ("Courier Prime", "CourierPrime.ttf"),
    "inter": ("Inter", "Inter.ttf"),
    "oswald": ("Oswald", "Oswald.ttf"),
    "bebas": ("Bebas Neue", "BebasNeue.ttf"),
    "playfair": ("Playfair Display", "PlayfairDisplay.ttf"),
}
DEFAULT_FONT = "courier"

# The printer's font A is 12 dots wide: 32 characters on 58 mm paper, 48 on 80 mm.
CHAR_DOTS = 12


def paper_width() -> int:
    """Printable width in dots (tickets.paper_width, one of PRINTER_PROFILES)."""
    width = Settings.get("tickets.paper_width", DEFAULT_PAPER_WIDTH)
    return width if width in PRINTER_PROFILES else DEFAULT_PAPER_WIDTH


def chars_per_line(width: int) -> int:
    """How many font-A characters fit across `width` dots."""
    return width // CHAR_DOTS


def open_printer():
    """Open the configured ESC/POS printer ("file" local device, or "network" raw TCP port)."""
    profile = PRINTER_PROFILES[paper_width()]
    if (Settings.get("tickets.printer_type") or "file") == "network":
        host = (Settings.get("tickets.printer_host") or "").strip()
        if not host:
            raise RuntimeError("Network printer selected but no host configured (Settings → Tickets)")
        port = int(Settings.get("tickets.printer_port") or 9100)
        printer = NetworkPrinter(host, port=port, timeout=network_timeout(), profile=profile)
        # Disable Nagle: it batches small writes and can stall a slow printer mid-image. Best-effort.
        try:
            printer.device.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (AttributeError, OSError):
            pass
        return printer
    device = Settings.get("tickets.printer_device") or "/dev/usb/lp0"
    return FilePrinter(device, profile=profile)


def network_timeout() -> int:
    """Socket timeout (s) for network prints. Too short aborts mid-image and strands a partial bitmap (garbles the next ticket)."""
    try:
        value = int(Settings.get("tickets.printer_timeout") or 30)
    except (TypeError, ValueError):
        return 30
    return value if value > 0 else 30


def feed_lines() -> int:
    """Blank lines fed after each ticket (tickets.feed_lines), for slack past the tear bar. Clamped 0–20, default 2."""
    try:
        value = int(Settings.get("tickets.feed_lines", 2))
    except (TypeError, ValueError):
        return 2
    return max(0, min(20, value))


# ESC/POS GS V m: cut at the blade with no extra feed (feed_lines already fed the slack).
CUT_COMMANDS = {"partial": b"\x1dV\x01", "full": b"\x1dV\x00"}


def cut_mode() -> str:
    """Paper cut after each ticket (tickets.cut): off / partial / full. Anything else is off."""
    value = str(Settings.get("tickets.cut") or "off").lower()
    return value if value in CUT_COMMANDS else "off"


def ticket_images_dir() -> str:
    return os.path.join(django_settings.MEDIA_ROOT, "ticket_images")


def ticket_image_path(file: str | None) -> str | None:
    """Filesystem path of a ticket-library image, or None."""
    name = os.path.basename(str(file or ""))
    if not name:
        return None
    path = os.path.join(ticket_images_dir(), name)
    return path if os.path.exists(path) else None


def _rating_image_path(certification: str | None) -> str | None:
    """Printer-ready rating symbol, or None. A user MEDIA_ROOT/pos/<system>/<cert>.png wins over the bundled asset."""
    if not certification or certification not in Settings.get_valid_ratings():
        return None
    system = Settings.get_ratings_system()
    override = os.path.join(django_settings.MEDIA_ROOT, "pos", system.lower(), f"{certification}.png")
    if os.path.exists(override):
        return override
    bundled = asset_path("ratings", system, "pos", f"{certification}.png")
    return bundled if os.path.exists(bundled) else None


DESIGN_TOKENS = ("film", "film_list", "seat", "date", "time", "showtime", "ticket_no", "cinema", "programme")

# The shipped "Standard" default.
DEFAULT_DESIGN_ELEMENTS = [
    {"type": "text", "content": "{cinema}", "size": "large", "bold": True},
    {"type": "rule"},
    {"type": "text", "content": "ADMIT ONE"},
    {"type": "text", "content": "{seat}", "size": "wide", "bold": True},
    {"type": "text", "content": "{film_list}", "bold": True},
    {"type": "rating", "width": 25},
    {"type": "text", "content": "{date} {time}"},
    {"type": "text", "content": "Ticket #{ticket_no}"},
    {"type": "qr", "mode": "fun", "width": 55},
    {"type": "rule"},
]

# What a new design can start from.
STARTER_DESIGNS = {
    "standard": DEFAULT_DESIGN_ELEMENTS,
    "compact": [
        {"type": "text", "content": "{cinema}", "size": "wide", "bold": True},
        {"type": "rule"},
        {
            "type": "columns",
            "widths": [1, 2],
            "cells": [
                [{"type": "qr", "mode": "fun", "width": 100}],
                [
                    {"type": "text", "content": "{film_list}", "align": "left", "bold": True},
                    {"type": "text", "content": "Seat {seat}", "align": "left", "size": "wide"},
                    {"type": "text", "content": "{date} {time}", "align": "left"},
                    {"type": "rating", "width": 40, "align": "left"},
                ],
            ],
        },
        {"type": "rule"},
    ],
    "blank": [],
}


def _substitute_tokens(text: str, tokens: dict[str, str]) -> str:
    for name in DESIGN_TOKENS:
        text = text.replace("{" + name + "}", tokens.get(name) or "")
    return text


def parse_elements(elements) -> list:
    """Stored or posted element dicts -> typed elements (schemas/tickets.py); raises ValidationError."""
    try:
        return ELEMENTS.validate_python(elements or [])
    except PydanticValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise ValidationError(f"Ticket element {where}: {first['msg']}", details={"field": "elements"}) from None


def dump_elements(elements) -> list[dict]:
    """Typed elements -> the JSON they store and travel as."""
    return ELEMENTS.dump_python(elements, mode="json")


def validate_design(data: dict) -> dict:
    """Clean the design fields present in `data` (elements, formats, links, font); raises ValidationError."""
    cleaned: dict = {}
    if data.get("elements") is not None:
        cleaned["elements"] = dump_elements(parse_elements(data["elements"]))
    for key, choices in (("date_format", DATE_FORMATS), ("time_format", TIME_FORMATS), ("font", TICKET_FONTS)):
        if data.get(key) is not None:
            if data[key] not in choices:
                raise ValidationError(f"Unknown {key.replace('_', ' ')}", details={"field": key})
            cleaned[key] = data[key]
    if data.get("qr_links") is not None:
        links = [str(link).strip() for link in data["qr_links"] if str(link).strip()]
        if len(links) > QR_LINKS_MAX or not all(link.startswith(("http://", "https://")) for link in links):
            raise ValidationError(f"Up to {QR_LINKS_MAX} http(s) links", details={"field": "qr_links"})
        cleaned["qr_links"] = links
    return cleaned


def design_spec(design) -> dict:
    """Everything rendering needs from a design: a TicketDesign, a draft dict of its fields, a bare element
    list, or None (the built-in layout), with its elements typed. Missing or unknown values fall back to the
    defaults."""
    if design is None:
        fields = {}
    elif isinstance(design, list):
        fields = {"elements": design}
    elif isinstance(design, dict):
        fields = design
    else:
        fields = {key: getattr(design, key) for key in ("elements", "date_format", "time_format", "qr_links", "font")}
    links = fields.get("qr_links")
    elements = fields.get("elements")
    return {
        "elements": parse_elements(DEFAULT_DESIGN_ELEMENTS if elements is None else elements),
        "date_format": fields.get("date_format") if fields.get("date_format") in DATE_FORMATS else DATE_FORMATS[0],
        "time_format": fields.get("time_format") if fields.get("time_format") in TIME_FORMATS else TIME_FORMATS[0],
        "qr_links": list(DEFAULT_QR_LINKS) if links is None else [str(x).strip() for x in links if str(x).strip()],
        "font": fields.get("font") if fields.get("font") in TICKET_FONTS else DEFAULT_FONT,
    }


def effective_certification(features) -> str | None:
    """The most restrictive certificate among features, per the active ratings system's severity order."""
    order = Settings.RATINGS_BBFC_ORDER if Settings.get_ratings_system() == "BBFC" else Settings.RATINGS_MPAA_ORDER
    ranks = [order.index(f.get("certification")) for f in features or [] if f.get("certification") in order]
    return order[max(ranks)] if ranks else None


def make_ticket_context(
    *,
    seat=None,
    when=None,
    scheduled=False,
    ticket_no=None,
    programme_name=None,
    features=None,
) -> dict:
    """Build the render context: what a ticket says, before a design formats it. `scheduled` populates
    {showtime}; `features` drives {film_list}/{film}/rating."""
    when = when or timezone.localtime()
    when = timezone.localtime(when) if timezone.is_aware(when) else when
    features = features or []
    film = ""
    if len(features) == 1:
        film = str(features[0].get("title") or "")
        if film and features[0].get("year"):
            film += f" ({features[0]['year']})"
    film_lines = [
        str(feat["title"])
        + (f" ({feat['year']})" if feat.get("year") else "")
        + (f" [{feat['certification']}]" if feat.get("certification") else "")
        for feat in features
        if feat.get("title")
    ]
    return {
        "cinema": Settings.get("cinema.name", "Cinefin"),
        "film": film,
        "film_list": "\n".join(film_lines),
        "certification": effective_certification(features),
        "seat": seat or "",
        "when": when,
        "scheduled": scheduled,
        "ticket_no": str(ticket_no) if ticket_no else "",
        "programme": programme_name or "",
        "features": features,
    }


def _style_of(el) -> dict:
    return {
        "align": getattr(el, "align", "center"),
        "size": getattr(el, "size", "normal"),
        "bold": getattr(el, "bold", False),
        "invert": getattr(el, "invert", False),
    }


def resolve_ticket_design(programme=None):
    """The design to print for `programme` — its override, else the default."""
    from cinefin.api.models import TicketDesign

    if programme is not None and getattr(programme, "ticket_design_id", None):
        return programme.ticket_design
    return TicketDesign.get_default()


def programme_features(programme) -> list[dict]:
    """The movie features of a programme, for the {film_list} token."""
    movies = (block.content_object for block in programme.blocks.filter(content_type="movie"))
    return [{"title": m.title, "year": m.year, "certification": m.certification} for m in movies if m is not None]


def design_tokens(ctx: dict, spec: dict) -> dict[str, str]:
    """The {token} values for a ticket: the context's facts, with dates and times in the design's formats."""
    when = ctx["when"]
    date, time = when.strftime(spec["date_format"]), when.strftime(spec["time_format"])
    values = {**ctx, "date": date, "time": time, "showtime": f"{date} {time}" if ctx.get("scheduled") else ""}
    return {k: str(values.get(k) or "") for k in DESIGN_TOKENS}


def qr_data(el, tokens: dict, spec: dict) -> str | None:
    """What a QR element encodes: one of the design's surprise links, or its content with tokens filled in."""
    if el.mode == "fun":
        return random.choice(spec["qr_links"]) if spec["qr_links"] else None
    return _substitute_tokens(el.content, tokens).strip() or None


def render_ticket_ops(
    design, ctx: dict, *, width: int | None = None, images: bool = True, preview: bool = False
) -> list[dict]:
    """A design (anything design_spec takes) + context -> the dict ops shared by print and preview.
    rule/spacer expand to text; blank text is skipped. A columns row becomes one bitmap, or with `images`
    off its text cells side by side. Each op carries `element` (its element's index) so the preview can
    map a line back to what made it; with `preview`, an element that prints nothing gives an "empty" op."""
    from cinefin.api.services import ticket_raster

    spec = design_spec(design)
    width = width if width in PRINTER_PROFILES else paper_width()
    tokens = design_tokens(ctx, spec)
    ops: list[dict] = []
    for index, el in enumerate(spec["elements"]):
        op = None
        style = {**_style_of(el), "element": index}
        if el.type == "text":
            value = _substitute_tokens(el.content, tokens)
            if value.strip():
                op = {"op": "text", "value": value.rstrip("\n") + "\n", **style}
        elif el.type == "rule":
            op = {"op": "text", "value": "=" * chars_per_line(width) + "\n", **style}
        elif el.type == "spacer":
            op = {"op": "text", "value": "\n" * el.lines, **style}
        elif el.type == "columns":
            if images:
                image, regions = ticket_raster.render_row(el, tokens, spec, ctx, width, preview=preview)
                op = {"op": "columns", "image": image, "regions": regions, "element": index}
            elif text := ticket_raster.row_as_text(el, tokens, width):
                op = {"op": "text", "value": text, **style, "align": "left"}
        elif el.type in ("image", "rating"):
            path = ticket_image_path(el.file) if el.type == "image" else _rating_image_path(ctx.get("certification"))
            if path and images:
                op = {"op": el.type, "path": path, "width": el.width, **style}
            elif path and preview:
                op = {"op": "empty", "label": f"{el.type.title()}: images are off", "element": index}
        elif el.type == "qr":
            if data := qr_data(el, tokens, spec):
                size = ticket_raster.qr_box(data, el.error, ticket_raster.share(width, el.width))
                op = {"op": "qr", **style, "data": data, "size": size, "error": el.error, "render": el.render}
        elif el.type == "barcode":
            if data := _substitute_tokens(el.content, tokens).strip():
                op = {"op": "barcode", "symbology": el.symbology, "data": data, **style}
                try:
                    op["data"] = barcode_data(el.symbology, data)
                except ValueError as e:
                    op["problem"] = str(e)  # previewed as a warning; printing skips it
        if op is None and preview:
            op = {"op": "empty", "label": ticket_raster.placeholder_label(el), "element": index}
        if op is not None:
            ops.append(op)
    return ops


def _scaled_image_size(width: int, height: int, max_width: int, percent: int | None = None) -> tuple[int, int]:
    """Keep aspect: fill `percent` of max_width dots (up or down) when given, else just cap the width at it."""
    target = max(1, max_width * percent // 100) if percent else min(width, max_width)
    if target != width:
        return target, max(1, round(height * target / width))
    return width, height


def flatten_transparency(img: Image.Image) -> Image.Image:
    """Composite transparency onto white first — PIL's convert("L"/"1") ignores alpha, so a transparent bg prints solid black."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return img


def _prepare_image(path: str, max_width: int, percent: int | None = None) -> Image.Image:
    """Scale to fit max_width dots (LANCZOS, keep aspect; see _scaled_image_size) and convert to 1-bit — unscaled
    images overflow the printer."""
    img = flatten_transparency(Image.open(path))
    target = _scaled_image_size(img.width, img.height, max_width, percent)
    if target != img.size:
        img = img.resize(target, Image.Resampling.LANCZOS)
    return img.convert("1")


def _open_checked_printer():
    """Probe, then open the printer; any failure but our own RuntimeError gets a human reason."""
    probe_printer()
    try:
        return open_printer()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Could not open printer: {e}") from e


def probe_printer():
    """
    Check a file-mode printer device is usable before sending bytes (File printer opens lazily -> misleading mid-print errors).

    Network printers are deliberately NOT probed: a connect-and-close before the real connection kills
    single-connection listeners (socat without `fork`) and breaks the following print with a broken pipe.
    """
    if (Settings.get("tickets.printer_type") or "file") != "file":
        return
    result = config_check_service.test_printer()
    if not result["ok"]:
        raise RuntimeError(result["message"])


def barcode_data(symbology: str, data: str) -> str:
    """`data` as `symbology` can carry it (upper-cased, zero-padded, start/stop added); ValueError says why it can't."""
    name = BARCODE_SYMBOLOGIES[symbology][0]
    if symbology == "code128":
        if not all(32 <= ord(c) < 127 for c in data):
            raise ValueError(f"{name} takes plain letters, digits and punctuation")
        return data
    if symbology == "code39":
        data = data.upper()
        if not set(data) <= _CODE39_CHARS:
            raise ValueError(f"{name} takes letters, digits, spaces and - . $ / + %")
        return data
    if symbology == "codabar":
        if not set(data) <= _CODABAR_CHARS:
            raise ValueError(f"{name} takes digits and - $ : / . +")
        return f"A{data}A"
    if not data.isdigit():
        raise ValueError(f"{name} takes digits only")
    if symbology == "itf":
        return data.zfill(len(data) + len(data) % 2)  # pairs of digits
    digits = _FIXED_DIGITS[symbology]
    if len(data) > digits:
        raise ValueError(f"{name} holds at most {digits} digits")
    return data.zfill(digits)


def _print_barcode(printer, op: dict) -> None:
    """A barcode, drawn by the printer when its profile has a barcode engine, else as an image; skipped (logged) if it can't print."""
    symbology = op["symbology"]
    if op.get("problem"):
        logger.warning("Skipping barcode %r: %s", op["data"], op["problem"])
        return
    bc = BARCODE_SYMBOLOGIES[symbology][1]
    align_ct = op.get("align", "center") == "center"
    try:
        if printer.profile.supports("barcodeB") or printer.profile.supports("barcodeA"):
            # The printer's own Code128 needs a code-set prefix (Epson, the GS k spec), else it prints nothing.
            code = "{B" + op["data"].replace("{", "{{") if symbology == "code128" else op["data"]
            printer.barcode(
                code,
                bc,
                width=2,
                height=64,
                pos="BELOW",
                align_ct=align_ct,
                function_type="B" if symbology == "code128" else None,
                check=False,
            )
        else:
            printer.barcode(op["data"], bc, width=2, height=64, align_ct=align_ct, force_software=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("Skipping unprintable barcode %r: %s", op["data"], e)


def _print_qr(printer, op: dict) -> None:
    """A QR code, drawn as an image here or by the printer's own QR engine (op['render'])."""
    from escpos.constants import QR_ECLEVEL_H, QR_ECLEVEL_L, QR_ECLEVEL_M, QR_ECLEVEL_Q

    ec = {"low": QR_ECLEVEL_L, "medium": QR_ECLEVEL_M, "quartile": QR_ECLEVEL_Q, "high": QR_ECLEVEL_H}[op["error"]]
    if op.get("render") == "printer":
        printer.qr(op["data"], ec=ec, size=op["size"], native=True)
    else:
        printer.qr(op["data"], ec=ec, size=op["size"])


def _emit_op(printer, op: dict, width: int, impl: str | None) -> None:
    """Send one render op to the printer, applying its align/size/bold/invert."""
    kind = op["op"]
    align = op.get("align", "center")
    if kind == "text":
        flags = dict(_TITLE_SIZE_FLAGS.get(op.get("size"), {}))
        printer.set(align=align, bold=bool(op.get("bold")), invert=bool(op.get("invert")), **flags)
        printer.text(op["value"])
        printer.set(align="center", bold=False, invert=False, normal_textsize=True)
    elif kind in ("image", "rating"):
        printer.set(align=align)
        printer.image(_prepare_image(op["path"], width, op["width"]), center=(align == "center"), impl=impl)
    elif kind == "qr":
        printer.set(align=align)
        _print_qr(printer, op)
    elif kind == "barcode":
        printer.set(align=align)
        _print_barcode(printer, op)
    elif kind == "columns":
        printer.set(align="center")
        printer.image(op["image"], impl=impl)


def print_ticket(design, ctx: dict):
    """Render `design` (anything design_spec takes) for `ctx` and print; raises RuntimeError with a human reason."""
    width = paper_width()
    ops = render_ticket_ops(design, ctx, width=width, images=image_impl() is not None)
    # Held across the whole open->write->close so no other job interleaves bytes (see _print_lock).
    with _print_lock:
        printer = _open_checked_printer()
        try:
            # ESC @ resets to a known state — python-escpos never sends it, so a ticket would inherit the prior job's state.
            printer.hw("INIT")
            printer.set(align="center", font=0)
            printer.text("\n")
            impl = image_impl()  # None = images off
            for op in ops:
                _emit_op(printer, op, width, impl)
            if pad := feed_lines():
                printer.text("\n" * pad)
            cut = cut_mode()
            if cut != "off":
                # Raw bytes, not printer.cut(): its feed=False path always sends a partial cut.
                printer._raw(CUT_COMMANDS[cut])
            printer.close()
        except BrokenPipeError as e:
            # EPIPE: the other end stopped taking bytes mid-write — a transport-state problem, not a data problem.
            if (Settings.get("tickets.printer_type") or "file") == "network":
                raise RuntimeError(
                    "Printing failed: the connection dropped mid-write (broken "
                    "pipe). The listener accepted the connection but stopped "
                    "reading — check the printer is idle and, if it's exposed via "
                    "socat, that the listener uses `fork` so it survives "
                    "reconnects: socat TCP-LISTEN:<port>,fork,reuseaddr "
                    "OPEN:/dev/usb/lp0"
                ) from e
            raise RuntimeError(
                "Printing failed: the printer stalled mid-write (broken pipe). "
                "Usually the printer is out of paper, in an error state, powered "
                "off, or the device is claimed by another driver (e.g. CUPS). "
                "Power-cycle the printer and check a shell write works: "
                "echo test > <device>"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Printing failed: {e}") from e


def reset_printer():
    """
    Recover a printer left mid-bitmap (a truncated raster leaves it eating tickets as bitmap data): ESC @ + blank feed.

    Best effort — a stubborn jam may swallow the INIT and need a second reset or power-cycle. Serialised on _print_lock.
    """
    with _print_lock:
        printer = _open_checked_printer()
        try:
            printer.hw("INIT")
            printer.text("\n\n\n")
            printer.close()
        except Exception as e:
            raise RuntimeError(f"Printer reset failed: {e}") from e


def reprint_issue(issue) -> None:
    """Reprint a stored TicketIssue WITHOUT recording a new issue or touching seat occupancy. Falls back to the title snapshot if FKs were nulled."""
    when = issue.schedule.play_time() if issue.schedule_id and issue.schedule else None
    base = {"seat": issue.seat or None, "when": when, "scheduled": when is not None, "ticket_no": issue.ticket_number}
    programme_name = issue.programme.name if issue.programme_id and issue.programme else None

    if issue.kind == TicketIssue.KIND_MOVIE and issue.movie:
        # Legacy per-feature ticket: reprint as a programme ticket scoped to that one film.
        movie = issue.movie
        features = [{"title": movie.title, "year": movie.year, "certification": movie.certification}]
    elif issue.kind == TicketIssue.KIND_PROGRAMME and issue.programme_id and issue.programme:
        features = programme_features(issue.programme)
    else:
        # Custom ticket, or the referenced movie/programme was deleted — reprint the snapshot title as a one-off text ticket.
        print_ticket([{"type": "text", "content": issue.title or ""}], make_ticket_context(**base))
        return
    ctx = make_ticket_context(**base, programme_name=programme_name, features=features)
    print_ticket(resolve_ticket_design(issue.programme), ctx)


def preview_ticket(design, ctx: dict, *, width: int | None = None) -> dict:
    """The designer's preview: the ticket drawn as it prints (lines that print nothing as grey placeholders),
    as a PNG data URL, with where each line, cell and item sits on it, in printer dots."""
    from cinefin.api.services import ticket_raster

    width = width if width in PRINTER_PROFILES else paper_width()
    ops = render_ticket_ops(design, ctx, width=width, images=image_impl() is not None, preview=True)
    image, lines = ticket_raster.render_preview(ops, width)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    return {"url": url, "width": image.width, "height": image.height, "lines": lines}


def occupied_seats(programme, schedule=None) -> set[str]:
    """Seats taken for one screening; with no screening, only the programme's unscheduled tickets count."""
    issues = TicketIssue.objects.filter(programme=programme, schedule=schedule).exclude(seat="")
    return set(issues.values_list("seat", flat=True))


def next_available_seat(programme=None, schedule=None, exclude=()) -> str:
    """Pick a random free seat, skipping `occupied_seats` and `exclude`; raises when full."""
    total_rows = Settings.get("tickets.total_rows", 10)
    seats_per_row = Settings.get("tickets.seats_per_row", 20)

    occupied = set(exclude)
    if programme is not None:
        occupied |= occupied_seats(programme, schedule)

    available = [
        seat
        for row in range(total_rows)
        for num in range(1, seats_per_row + 1)
        if (seat := f"{chr(65 + row)}{num}") not in occupied
    ]
    if not available:
        raise ValidationError(
            "Auditorium is full — every seat already has a ticket for this screening",
            error_code="AUDITORIUM_FULL",
        )
    return random.choice(available)


def print_run(
    *,
    kind: str,
    title: str,
    design,
    copies: int = 1,
    seat: str | None = None,
    seats: list[str] | None = None,
    programme=None,
    schedule=None,
    when=None,
    scheduled: bool = False,
    programme_name: str | None = None,
    features: list[dict] | None = None,
) -> list[TicketIssue]:
    """
    Print one ticket per resolved seat and record a TicketIssue each.

    Seat resolution: `seats` prints exactly those (overrides `copies`/`seat`); else `copies` tickets, `seat` first then
    auto-assigned. The ticket number is allocated *before* printing (so it can appear on the ticket); a failed print
    deletes its just-created issue, so only successful prints stay recorded.
    """
    seat_list = list(seats or [])
    if not seats:
        for index in range(copies):
            seat_list.append(
                seat if (index == 0 and seat) else next_available_seat(programme, schedule, exclude=set(seat_list))
            )

    issues: list[TicketIssue] = []
    for this_seat in seat_list:
        issue = TicketIssue.issue(kind=kind, title=title[:500], seat=this_seat, programme=programme, schedule=schedule)
        ctx = make_ticket_context(
            seat=this_seat,
            when=when,
            scheduled=scheduled,
            ticket_no=issue.ticket_number,
            programme_name=programme_name,
            features=features,
        )
        try:
            print_ticket(design, ctx)
        except Exception:
            issue.delete()  # a failed print isn't a sold ticket
            raise
        issues.append(issue)
    return issues
