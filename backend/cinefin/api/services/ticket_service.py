"""Ticket text generation, layout, and ESC/POS printing (a design + context -> render ops shared by print and preview)."""

import logging
import os
import random
import socket
import threading
from urllib.parse import quote

from django.conf import settings as django_settings
from django.utils import timezone
from escpos.printer import File as FilePrinter
from escpos.printer import Network as NetworkPrinter
from PIL import Image

from cinefin.api.exceptions import ValidationError
from cinefin.api.models import Settings, TicketIssue
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

# rating element `scale` -> fraction of printable width the symbol occupies.
RATING_SIZE_FRACTIONS = {"small": 0.18, "medium": 0.25, "large": 0.35}

QR_SIZE_MIN, QR_SIZE_MAX = 1, 16
DEFAULT_QR_SIZE = 6

DATE_FORMATS = ("%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%a %d %b %Y")
TIME_FORMATS = ("%H:%M", "%I:%M %p")

# Fallback for fun-mode QR when tickets.qr_fun_links is unset/malformed (a saved empty list is respected -> no QR).
FUN_QR_LINKS = list(Settings.DEFAULTS["tickets"]["qr_fun_links"])

RULE = "=============================\n"


def paper_width() -> int:
    """Printable width in dots (tickets.paper_width, one of PRINTER_PROFILES)."""
    width = Settings.get("tickets.paper_width", DEFAULT_PAPER_WIDTH)
    return width if width in PRINTER_PROFILES else DEFAULT_PAPER_WIDTH


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


def ticket_images_dir() -> str:
    return os.path.join(django_settings.MEDIA_ROOT, "ticket_images")


def _ticket_image_path(el: dict) -> str | None:
    name = os.path.basename(str(el.get("file") or ""))
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


ELEMENT_TYPES = ("text", "image", "rating", "qr", "barcode", "rule", "spacer")
ALIGNMENTS = ("left", "center", "right")
ELEMENT_SIZES = ("normal", "wide", "tall", "large")  # -> double width/height via _TITLE_SIZE_FLAGS
DESIGN_TOKENS = ("film", "film_list", "seat", "date", "time", "showtime", "ticket_no", "cinema", "programme")

# The shipped "Standard" default.
DEFAULT_DESIGN_ELEMENTS = [
    {"type": "text", "content": "{cinema}", "size": "large", "bold": True},
    {"type": "rule"},
    {"type": "text", "content": "ADMIT ONE"},
    {"type": "text", "content": "{seat}", "size": "wide", "bold": True},
    {"type": "text", "content": "{film_list}", "bold": True},
    {"type": "rating", "scale": "medium"},
    {"type": "text", "content": "{date} {time}"},
    {"type": "text", "content": "Ticket #{ticket_no}"},
    {"type": "qr", "mode": "fun", "size": 6},
    {"type": "rule"},
]


def _fun_qr_link() -> str | None:
    pool = Settings.get("tickets.qr_fun_links")
    if not isinstance(pool, list):
        pool = FUN_QR_LINKS
    pool = [str(x).strip() for x in pool if str(x).strip()]
    return random.choice(pool) if pool else None


def _substitute_tokens(text: str, tokens: dict[str, str]) -> str:
    for name in DESIGN_TOKENS:
        text = text.replace("{" + name + "}", tokens.get(name) or "")
    return text


def validate_elements(elements, *, field: str = "elements") -> list[dict]:
    """Validate/normalize a design's element list into clean dicts; raises ValidationError on a bad shape."""
    if not isinstance(elements, list):
        raise ValidationError("Ticket elements must be a list", details={"field": field})
    cleaned = []
    for raw in elements:
        if not isinstance(raw, dict) or raw.get("type") not in ELEMENT_TYPES:
            raise ValidationError(
                f"Each element needs a valid type ({', '.join(ELEMENT_TYPES)})", details={"field": field}
            )
        t = raw["type"]
        el: dict = {"type": t}
        if raw.get("align") in ALIGNMENTS:
            el["align"] = raw["align"]
        if raw.get("size") in ELEMENT_SIZES and raw["size"] != "normal":
            el["size"] = raw["size"]
        if raw.get("bold"):
            el["bold"] = True
        if raw.get("invert"):
            el["invert"] = True
        if t in ("text", "barcode"):
            el["content"] = str(raw.get("content", ""))[:500]
        elif t == "rating":
            el["scale"] = raw["scale"] if raw.get("scale") in RATING_SIZE_FRACTIONS else "medium"
        elif t == "qr":
            el["mode"] = "fun" if raw.get("mode") == "fun" else "content"
            if el["mode"] == "content":
                el["content"] = str(raw.get("content", ""))[:500]
            try:
                el["size"] = min(max(int(raw.get("size", DEFAULT_QR_SIZE)), QR_SIZE_MIN), QR_SIZE_MAX)
            except (TypeError, ValueError):
                el["size"] = DEFAULT_QR_SIZE
        elif t == "spacer":
            try:
                el["lines"] = min(max(int(raw.get("lines", 1)), 1), 10)
            except (TypeError, ValueError):
                el["lines"] = 1
        elif t == "image":
            # basename() blocks path traversal on the library-image filename.
            el["file"] = os.path.basename(str(raw.get("file") or ""))[:200]
        cleaned.append(el)
    return cleaned


def effective_certification(features) -> str | None:
    """The most restrictive certificate among features, per the active ratings system's severity order."""
    order = Settings.RATINGS_BBFC_ORDER if Settings.get_ratings_system() == "BBFC" else Settings.RATINGS_MPAA_ORDER
    best = -1
    for feat in features or []:
        cert = feat.get("certification")
        if cert in order:
            best = max(best, order.index(cert))
    return order[best] if best >= 0 else None


def make_ticket_context(
    *,
    seat=None,
    when=None,
    scheduled=False,
    ticket_no=None,
    programme_name=None,
    features=None,
) -> dict:
    """Build the token/render context. `scheduled` populates {showtime}; `features` drives {film_list}/{film}/rating."""
    when = when or timezone.localtime()
    when = timezone.localtime(when) if timezone.is_aware(when) else when
    date_fmt = Settings.get("tickets.date_format", DATE_FORMATS[0])
    time_fmt = Settings.get("tickets.time_format", TIME_FORMATS[0])
    date_str = when.strftime(date_fmt if date_fmt in DATE_FORMATS else DATE_FORMATS[0])
    time_str = when.strftime(time_fmt if time_fmt in TIME_FORMATS else TIME_FORMATS[0])
    features = features or []
    film = ""
    if len(features) == 1:
        film = str(features[0].get("title") or "")
        if film and features[0].get("year"):
            film += f" ({features[0]['year']})"
    film_lines = []
    for feat in features:
        line = str(feat.get("title") or "")
        if not line:
            continue
        if feat.get("year"):
            line += f" ({feat['year']})"
        if feat.get("certification"):
            line += f" [{feat['certification']}]"
        film_lines.append(line)
    return {
        "cinema": Settings.get("cinema.name", "Cinefin"),
        "film": film,
        "film_list": "\n".join(film_lines),
        "certification": effective_certification(features),
        "seat": seat or "",
        "date": date_str,
        "time": time_str,
        "showtime": f"{date_str} {time_str}" if scheduled else "",
        "ticket_no": str(ticket_no) if ticket_no else "",
        "programme": programme_name or "",
        "features": features,
    }


def _style_of(el: dict) -> dict:
    return {
        "align": el.get("align", "center"),
        "size": el.get("size", "normal"),
        "bold": bool(el.get("bold")),
        "invert": bool(el.get("invert")),
    }


def _design_elements(design) -> list:
    if design is None:
        return DEFAULT_DESIGN_ELEMENTS
    if isinstance(design, list):
        return design
    return design.elements or DEFAULT_DESIGN_ELEMENTS


def resolve_ticket_design(programme=None):
    """The design to print for `programme` — its override, else the default."""
    from cinefin.api.models import TicketDesign

    if programme is not None and getattr(programme, "ticket_design_id", None):
        return programme.ticket_design
    return TicketDesign.get_default()


def programme_features(programme) -> list[dict]:
    """The movie features of a programme, for the {film_list} token."""
    feats = []
    for block in programme.blocks.filter(content_type="movie"):
        movie = block.content_object
        if movie is None:
            continue
        feats.append(
            {
                "title": movie.title,
                "year": getattr(movie, "year", None),
                "certification": getattr(movie, "certification", None),
            }
        )
    return feats


def render_ticket_ops(elements, ctx: dict) -> list[dict]:
    """Design elements + context -> the dict ops shared by print and preview. rule/spacer expand to text; blank text is skipped."""
    tokens = {k: (ctx.get(k) or "") for k in DESIGN_TOKENS}
    ops: list[dict] = []
    for el in elements or []:
        t = el.get("type")
        style = _style_of(el)
        if t == "text":
            value = _substitute_tokens(el.get("content", ""), tokens)
            if value.strip():
                ops.append({"op": "text", "value": value.rstrip("\n") + "\n", **style})
        elif t == "rule":
            ops.append({"op": "text", "value": RULE, **style})
        elif t == "spacer":
            ops.append({"op": "text", "value": "\n" * int(el.get("lines", 1) or 1)})
        elif t == "image":
            path = _ticket_image_path(el)
            if path:
                ops.append({"op": "image", "path": path, "file": el.get("file"), **style})
        elif t == "rating":
            path = _rating_image_path(ctx.get("certification"))
            if path:
                frac = RATING_SIZE_FRACTIONS.get(el.get("scale", "medium"), RATING_SIZE_FRACTIONS["medium"])
                ops.append({"op": "rating", "path": path, "scale": frac, **style})
        elif t == "qr":
            data = (
                _fun_qr_link() if el.get("mode") == "fun" else _substitute_tokens(el.get("content", ""), tokens).strip()
            )
            if data:
                ops.append(
                    {"op": "qr", "data": data, "size": int(el.get("size", DEFAULT_QR_SIZE) or DEFAULT_QR_SIZE), **style}
                )
        elif t == "barcode":
            data = _substitute_tokens(el.get("content", ""), tokens).strip()
            if data:
                ops.append({"op": "barcode", "data": data, **style})
    return ops


def _scaled_image_size(width: int, height: int, max_width: int) -> tuple[int, int]:
    """Cap width at max_width dots, keep aspect."""
    if width > max_width:
        return max_width, max(1, round(height * max_width / width))
    return width, height


def flatten_transparency(img: Image.Image) -> Image.Image:
    """Composite transparency onto white first — PIL's convert("L"/"1") ignores alpha, so a transparent bg prints solid black."""
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.split()[-1])
        return background
    return img


def _prepare_image(path: str, max_width: int) -> Image.Image:
    """Downscale to at most max_width dots (LANCZOS, keep aspect) and convert to 1-bit — unscaled images overflow the printer."""
    img = flatten_transparency(Image.open(path))
    target = _scaled_image_size(img.width, img.height, max_width)
    if target != img.size:
        img = img.resize(target, Image.Resampling.LANCZOS)
    return img.convert("1")


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


def _print_barcode(printer, data: str) -> None:
    """Native Code128 barcode; skipped (logged, not fatal) if it can't print."""
    try:
        printer.barcode(data, "CODE128", width=2, height=64, pos="BELOW", align_ct=True, check=False)
    except Exception as e:  # noqa: BLE001
        logger.warning("Skipping unprintable barcode %r: %s", data, e)


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
        if not impl:  # images off
            return
        max_width = width if kind == "image" else int(width * op["scale"])
        printer.set(align=align)
        printer.image(_prepare_image(op["path"], max_width), center=(align == "center"), impl=impl)
    elif kind == "qr":
        printer.set(align=align)
        printer.qr(op["data"], size=op["size"])
    elif kind == "barcode":
        printer.set(align=align)
        _print_barcode(printer, op["data"])


def print_ticket(design, ctx: dict):
    """Render `design` (TicketDesign / elements list / None) for `ctx` and print; raises RuntimeError with a human reason."""
    ops = render_ticket_ops(_design_elements(design), ctx)
    width = paper_width()
    # Held across the whole open->write->close so no other job interleaves bytes (see _print_lock).
    with _print_lock:
        probe_printer()
        try:
            printer = open_printer()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Could not open printer: {e}") from e

        try:
            # ESC @ resets to a known state — python-escpos never sends it, so a ticket would inherit the prior job's state.
            printer.hw("INIT")
            printer.set(align="center", font=0)
            printer.text("\n")
            impl = image_impl()  # None = images off
            for op in ops:
                _emit_op(printer, op, width, impl)
            pad = feed_lines()
            if pad:
                printer.text("\n" * pad)
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
        probe_printer()
        try:
            printer = open_printer()
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Could not open printer: {e}") from e
        try:
            printer.hw("INIT")
            printer.text("\n\n\n")
            printer.close()
        except Exception as e:
            raise RuntimeError(f"Printer reset failed: {e}") from e


def reprint_issue(issue) -> None:
    """Reprint a stored TicketIssue WITHOUT recording a new issue or touching seat occupancy. Falls back to the title snapshot if FKs were nulled."""
    when = issue.schedule.start_time if issue.schedule_id and issue.schedule else None
    scheduled = when is not None
    design = resolve_ticket_design(issue.programme)
    programme_name = issue.programme.name if issue.programme_id and issue.programme else None

    if issue.kind == TicketIssue.KIND_MOVIE and issue.movie:
        # Legacy per-feature ticket: reprint as a programme ticket scoped to that one film.
        ctx = make_ticket_context(
            seat=issue.seat or None,
            when=when,
            scheduled=scheduled,
            ticket_no=issue.ticket_number,
            programme_name=programme_name,
            features=[
                {
                    "title": issue.movie.title,
                    "year": issue.movie.year,
                    "certification": issue.movie.certification,
                }
            ],
        )
    elif issue.kind == TicketIssue.KIND_PROGRAMME and issue.programme_id and issue.programme:
        ctx = make_ticket_context(
            seat=issue.seat or None,
            when=when,
            scheduled=scheduled,
            ticket_no=issue.ticket_number,
            programme_name=programme_name,
            features=programme_features(issue.programme),
        )
    else:
        # Custom ticket, or the referenced movie/programme was deleted — reprint the snapshot title as a one-off text ticket.
        ctx = make_ticket_context(
            seat=issue.seat or None, when=when, scheduled=scheduled, ticket_no=issue.ticket_number
        )
        print_ticket([{"type": "text", "content": issue.title or ""}], ctx)
        return

    print_ticket(design, ctx)


def preview_ticket(elements, ctx: dict) -> list[str]:
    """Plain-text rendering of a design + context, for the UI text preview."""
    lines: list[str] = []
    for op in render_ticket_ops(elements, ctx):
        kind = op["op"]
        if kind == "text":
            lines.extend(part for part in op["value"].split("\n") if part)
        elif kind == "image":
            lines.append(f"[ {op.get('file') or 'image'} ]")
        elif kind == "rating":
            lines.append(f"[ {os.path.basename(op['path'])} ]")
        elif kind == "qr":
            lines.append(f"[ QR → {op['data']} ]")
        elif kind == "barcode":
            lines.append(f"[ |||| {op['data']} ]")
    return lines


def preview_ticket_ops(elements, ctx: dict, *, width: int | None = None) -> tuple[list[dict], int]:
    """JSON-safe styled-preview ops (+ printable width). Uses the print path's scaling math; images served via /tickets/preview/asset (bundled symbols aren't web-reachable)."""
    if width not in PRINTER_PROFILES:
        width = paper_width()
    style_keys = ("align", "size", "bold", "invert")
    result: list[dict] = []
    for op in render_ticket_ops(elements, ctx):
        kind = op["op"]
        style = {k: op[k] for k in style_keys if k in op}
        if kind == "text":
            result.append({"type": "text", "value": op["value"], **style})
        elif kind in ("image", "rating"):
            max_width = width if kind == "image" else int(width * op["scale"])
            with Image.open(op["path"]) as img:
                scaled_w, scaled_h = _scaled_image_size(img.width, img.height, max_width)
            if kind == "rating":
                url = f"/api/v2/tickets/preview/asset?kind=rating&cert={quote(ctx.get('certification') or '')}"
            else:
                url = f"/api/v2/tickets/preview/asset?kind=image&file={quote(op.get('file') or '')}"
            result.append(
                {"type": "image", "kind": kind, "width_px": scaled_w, "height_px": scaled_h, "url": url, **style}
            )
        elif kind == "qr":
            result.append({"type": "qr", "url": op["data"], "size": op["size"], **style})
        elif kind == "barcode":
            result.append({"type": "barcode", "value": op["data"], **style})
    return result, width


def next_available_seat(programme=None, schedule=None, exclude=()) -> str:
    """Pick a random free seat. Occupied = programme's TicketIssue seats (narrowed to schedule if given) plus `exclude`; raises when full."""
    total_rows = Settings.get("tickets.total_rows", 10)
    seats_per_row = Settings.get("tickets.seats_per_row", 20)

    occupied = set(exclude)
    if programme is not None:
        issues = TicketIssue.objects.filter(programme=programme).exclude(seat="")
        if schedule is not None:
            issues = issues.filter(schedule=schedule)
        occupied.update(issues.values_list("seat", flat=True))

    available = [
        seat
        for row in range(total_rows)
        for num in range(1, seats_per_row + 1)
        if (seat := f"{chr(65 + row)}{num}") not in occupied
    ]
    if not available:
        raise ValidationError(
            "Auditorium is full — every seat already has a ticket for this programme",
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
    if seats:
        seat_list = list(seats)
    else:
        seat_list = []
        assigned: set[str] = set()
        for index in range(copies):
            this_seat = seat if (index == 0 and seat) else next_available_seat(programme, schedule, exclude=assigned)
            assigned.add(this_seat)
            seat_list.append(this_seat)

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


def preview_asset_path(kind: str, cert: str | None = None, file: str | None = None) -> str | None:
    """Filesystem path of a ticket image for the styled preview, or None."""
    if kind == "rating":
        return _rating_image_path(cert)
    if kind == "image":
        return _ticket_image_path({"file": file})
    return None
