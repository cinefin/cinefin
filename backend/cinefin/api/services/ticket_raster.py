"""Tickets as pictures: columns rows (which print as one bitmap) and the designer's preview of a whole ticket.

A columns row's cells sit side by side, each a short stack of elements, with text in the design's font sized
to match the printer's own font A (12 x 24 dots). The preview draws every print op the way the printer
will, onto one image the paper's width, and says where each line, cell and item landed so the designer can
make them clickable. Lines that print nothing show there as grey placeholders, which never print.
"""

import functools
import textwrap
from types import SimpleNamespace

import qrcode
import qrcode.constants
from PIL import Image, ImageDraw, ImageFont

from cinefin.api.services import ticket_service as ts
from cinefin.api.services.titlegen_service import bundled_fonts_dir

GUTTER = 12  # dots between cells
PADDING = 4  # dots above and below a columns row
LINE = 24  # dots per text line in a columns row: font A's height
PRINTER_LINE = 30  # dots per printed text line: font A plus the printer's default line spacing
INK, PAPER, PLACEHOLDER, PLACEHOLDER_INK = 0, 255, 232, 130
# Font size (px) per font that gives each roughly font A's height; Courier Prime at 20 px is 12 dots a character.
FONT_SIZES = {"courier": 20, "inter": 18, "oswald": 20, "bebas": 24, "playfair": 19}
# Element `size` -> (horizontal, vertical) stretch, as the printer's double width/height does.
SIZE_SCALES = {"wide": (2, 1), "tall": (1, 2), "large": (2, 2)}
QR_ERRORS = {
    "low": qrcode.constants.ERROR_CORRECT_L,
    "medium": qrcode.constants.ERROR_CORRECT_M,
    "quartile": qrcode.constants.ERROR_CORRECT_Q,
    "high": qrcode.constants.ERROR_CORRECT_H,
}


def share(width: int, percent: int) -> int:
    return max(1, width * percent // 100)


def cell_widths(widths: list[int], total: int, gutter: int) -> list[int]:
    """Split `total` into cells in the ratio `widths`, `gutter` between each; the last takes the rounding."""
    room = total - gutter * (len(widths) - 1)
    sizes = [room * w // sum(widths) for w in widths[:-1]]
    return [*sizes, room - sum(sizes)]


@functools.cache
def _font(name: str, bold: bool) -> tuple[ImageFont.FreeTypeFont, int]:
    """The design font (and a stroke width that fakes bold for fonts without a Bold weight)."""
    font = ImageFont.truetype(str(bundled_fonts_dir() / ts.TICKET_FONTS[name][1]), FONT_SIZES[name])
    if not bold:
        return font, 0
    try:
        font.set_variation_by_name("Bold")
        return font, 0
    except (OSError, ValueError):
        return font, 1


# ── QR codes ──────────────────────────────────────────────────────────────────


def _qr_code(data: str, error: str, box: int) -> qrcode.QRCode:
    code = qrcode.QRCode(box_size=box, border=1, error_correction=QR_ERRORS[error])
    code.add_data(data)
    code.make(fit=True)
    return code


def qr_box(data: str, error: str, target: int) -> int:
    """The module size (dots, 1-16, as the printer takes it) that makes the QR at most `target` dots wide."""
    modules = _qr_code(data, error, 1).modules_count + 2  # the 1-module border each side
    return max(1, min(16, target // modules))


def qr_image(data: str, error: str, box: int) -> Image.Image:
    return _qr_code(data, error, box).make_image().get_image().convert("L")


# ── Text ────────────────────────────────────────────────────────────────────────


def _wrap(text: str, fits) -> list[str]:
    """Greedy word wrap; a word too long for a line is broken where it overflows."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if fits(candidate):
                line = candidate
                continue
            if line:
                lines.append(line)
            while not fits(word) and len(word) > 1:
                cut = next(i for i in range(len(word), 0, -1) if fits(word[:i]) or i == 1)
                lines.append(word[:cut])
                word = word[cut:]
            line = word
        lines.append(line)
    return lines


def _draw_lines(lines, el, font_name: str, width: int, line_h: int, fill_line: bool) -> Image.Image:
    """Lines of text `width` dots wide, aligned and styled as `el` says. `fill_line` inverts the whole line
    (a cell), else just behind the characters (as the printer does)."""
    font, stroke = _font(font_name, el.bold)
    sx, sy = SIZE_SCALES.get(el.size, (1, 1))
    out = Image.new("L", (width, line_h * sy * len(lines)), INK if (el.invert and fill_line) else PAPER)
    for i, line in enumerate(lines):
        strip = Image.new("L", (max(1, width // sx), line_h), PAPER)
        draw = ImageDraw.Draw(strip)
        w = font.getlength(line) + 2 * stroke
        x = {"left": 0, "right": strip.width - w}.get(el.align, (strip.width - w) / 2)
        ink = INK
        if el.invert:
            if fill_line:
                strip.paste(INK, (0, 0, strip.width, line_h))
            else:
                draw.rectangle((x, 0, x + w, line_h - 1), fill=INK)
            ink = PAPER
        draw.text(
            (x + stroke, line_h / 2), line, font=font, fill=ink, anchor="lm", stroke_width=stroke, stroke_fill=ink
        )
        if (sx, sy) != (1, 1):
            strip = strip.resize((strip.width * sx, line_h * sy), Image.Resampling.NEAREST)
        out.paste(strip, (0, line_h * sy * i))
    return out


def _cell_text(el, value: str, font_name: str, width: int) -> Image.Image | None:
    if not value.strip():
        return None
    font, stroke = _font(font_name, el.bold)
    sx, _ = SIZE_SCALES.get(el.size, (1, 1))
    lines = _wrap(value.rstrip("\n"), lambda s: font.getlength(s) + 2 * stroke <= width / sx)
    return _draw_lines(lines, el, font_name, width, LINE, fill_line=True)


def _placeholder(label: str, width: int, height: int = LINE) -> Image.Image:
    """A grey band naming an element that prints nothing: preview only."""
    image = Image.new("L", (width, height), PLACEHOLDER)
    font, _ = _font("inter", False)
    text = (
        label
        if font.getlength(label) <= width - 8
        else label[: max(1, int(len(label) * (width - 8) / font.getlength(label)) - 1)] + "…"
    )
    ImageDraw.Draw(image).text((width / 2, height / 2), text, font=font, fill=PLACEHOLDER_INK, anchor="mm")
    return image


def placeholder_label(el) -> str:
    """What a line that prints nothing would say in the preview."""
    if el.type == "text":
        return f"{el.content.strip() or 'Empty text'}: blank here"
    return {
        "image": "Image: none chosen",
        "rating": "Rating: no certificate",
        "qr": "QR code: no link",
        "barcode": "Barcode: no content",
    }.get(el.type, "Prints nothing")


# ── Columns rows ──────────────────────────────────────────────────────────────


def _item(el, tokens: dict, spec: dict, ctx: dict, width: int) -> Image.Image | None:
    """One cell item as a greyscale image at most `width` dots wide, or None when it prints nothing."""
    if el.type == "text":
        return _cell_text(el, ts._substitute_tokens(el.content, tokens), spec["font"], width)
    if el.type == "rule":
        image = Image.new("L", (width, 14), PAPER)
        ImageDraw.Draw(image).rectangle((0, 6, width - 1, 7), fill=INK)
        return image
    if el.type == "spacer":
        return Image.new("L", (width, LINE * el.lines), PAPER)
    if el.type == "qr":
        data = ts.qr_data(el, tokens, spec)
        return qr_image(data, el.error, qr_box(data, el.error, share(width, el.width))) if data else None
    if el.type == "rating":
        path = ts._rating_image_path(ctx.get("certification"))
        return ts._prepare_image(path, width, el.width).convert("L") if path else None
    if el.type == "image":
        path = ts.ticket_image_path(el.file)
        return ts._prepare_image(path, width, el.width).convert("L") if path else None
    return None


def render_row(el, tokens: dict, spec: dict, ctx: dict, paper: int, *, preview: bool = False):
    """The row as an image `paper` dots wide (1-bit to print; greyscale with placeholders to preview), and
    where each cell and item landed on it, in dots: `[{x, w, items: [{y, h}, ...]}, ...]`."""
    widths = cell_widths(el.widths, paper, GUTTER)
    cells = []
    for cell, w in zip(el.cells, widths, strict=True):
        images = [_item(item, tokens, spec, ctx, w) for item in cell]
        if preview:
            images = [img or _placeholder(placeholder_label(item), w) for img, item in zip(images, cell, strict=True)]
        cells.append(images)
    height = max([LINE] + [sum(i.height for i in items if i) for items in cells]) + 2 * PADDING
    row = Image.new("L", (paper, height), PAPER)
    regions, x = [], 0
    for images, cell, w in zip(cells, el.cells, widths, strict=True):
        y, boxes = PADDING, []
        for image, item in zip(images, cell, strict=True):
            if image is None:
                boxes.append({"y": y, "h": 0})
                continue
            offset = {"left": 0, "right": w - image.width}.get(getattr(item, "align", "center"), (w - image.width) // 2)
            row.paste(image, (x + offset, y))
            boxes.append({"y": y, "h": image.height})
            y += image.height
        regions.append({"x": x, "w": w, "items": boxes})
        x += w + GUTTER
    if preview:
        return row, regions
    return row.point(lambda p: PAPER if p > 127 else INK, mode="1"), regions


def row_as_text(el, tokens: dict, paper: int) -> str:
    """With images off: the row's text, rules and spacers side by side in the printer's own font."""
    widths = cell_widths(el.widths, ts.chars_per_line(paper), 1)
    columns = []
    for cell, w in zip(el.cells, widths, strict=True):
        lines = []
        for item in cell:
            if item.type == "text":
                value = ts._substitute_tokens(item.content, tokens)
                if not value.strip():
                    continue
                pad = {"left": str.ljust, "right": str.rjust}.get(item.align, str.center)
                for paragraph in value.rstrip("\n").split("\n"):
                    lines += [pad(part, w) for part in textwrap.wrap(paragraph, w) or [""]]
            elif item.type == "rule":
                lines.append("-" * w)
            elif item.type == "spacer":
                lines += [" " * w] * item.lines
        columns.append([line.ljust(w) for line in lines])
    # A cell that runs out of lines keeps its width in blanks, so the cells after it stay put.
    rows = [
        " ".join((col[i] if i < len(col) else " " * w) for col, w in zip(columns, widths, strict=True)).rstrip()
        for i in range(max((len(c) for c in columns), default=0))
    ]
    return "\n".join(rows) + "\n" if any(rows) else ""


# ── The preview ───────────────────────────────────────────────────────────────


def _printer_text(op: dict, paper: int) -> Image.Image:
    """A text op as the printer lays it out: font A, wrapped at the paper's character width."""
    sx, _ = SIZE_SCALES.get(op["size"], (1, 1))
    per_line = ts.chars_per_line(paper) // sx
    lines = []
    for line in op["value"].rstrip("\n").split("\n"):
        lines += [line[i : i + per_line] for i in range(0, len(line), per_line)] or [""]
    style = SimpleNamespace(
        align=op.get("align", "center"),
        size=op.get("size", "normal"),
        bold=op.get("bold", False),
        invert=op.get("invert", False),
    )
    return _draw_lines(lines, style, "courier", paper, PRINTER_LINE, fill_line=False)


def _barcode_image(symbology: str, data: str) -> Image.Image:
    """A barcode as the printer draws it: 2-dot modules, 64 dots tall, the value beneath."""
    import barcode
    from barcode.writer import ImageWriter

    # Our symbology ids are python-barcode's names.
    code = barcode.get_barcode_class(symbology)(data, writer=ImageWriter())
    # At the writer's dpi, 0.25 mm is 2 dots and 8 mm is 64.
    options = {"module_width": 0.25, "module_height": 8.0, "dpi": 203, "font_size": 9, "text_distance": 5.0}
    return code.render({**options, "quiet_zone": 1.0}).convert("L")


def _op_image(op: dict, paper: int) -> Image.Image | None:
    kind = op["op"]
    if kind == "text":
        return _printer_text(op, paper)
    if kind in ("image", "rating"):
        return ts._prepare_image(op["path"], paper, op.get("width")).convert("L")
    if kind == "qr":
        return qr_image(op["data"], op["error"], op["size"])
    if kind == "barcode":
        if op.get("problem"):
            return _placeholder(f"Barcode won't print: {op['problem']}", paper, PRINTER_LINE)
        try:
            image = _barcode_image(op["symbology"], op["data"])
        except Exception:  # noqa: BLE001 - the printer may still draw what python-barcode won't
            return _placeholder(f"Barcode {op['data']}", paper, PRINTER_LINE)
        return image if image.width <= paper else image.resize((paper, image.height))
    if kind == "columns":
        return op["image"]
    if kind == "empty":
        return _placeholder(op["label"], paper, PRINTER_LINE)
    return None


def render_preview(ops: list[dict], paper: int) -> tuple[Image.Image, list[dict]]:
    """The ticket as one greyscale image, and each line's place on it, in dots: `[{element, y, h, empty,
    cells?}]`; a columns line's `cells` are `[{x, w, items: [{y, h}]}]` with y measured down the whole image."""
    pieces = [(op, image) for op in ops if (image := _op_image(op, paper)) is not None]
    top = PRINTER_LINE  # the blank line every ticket starts with
    height = top + sum(image.height for _, image in pieces) + PRINTER_LINE
    canvas = Image.new("L", (paper, height), PAPER)
    lines, y = [], top
    for op, image in pieces:
        align = op.get("align", "center") if op["op"] not in ("text", "columns", "empty") else "center"
        x = {"left": 0, "right": paper - image.width}.get(align, (paper - image.width) // 2)
        canvas.paste(image, (x, y))
        line = {"element": op["element"], "y": y, "h": image.height, "empty": op["op"] == "empty"}
        if op["op"] == "columns":
            line["cells"] = [
                {**cell, "items": [{"y": y + item["y"], "h": item["h"]} for item in cell["items"]]}
                for cell in op["regions"]
            ]
        lines.append(line)
        y += image.height
    return canvas, lines
