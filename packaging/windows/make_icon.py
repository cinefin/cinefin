"""Generate a square multi-size .ico from a (possibly non-square) brand mark.

Padding to a square canvas first keeps the mark's aspect ratio — writing a
non-square image straight to .ico would squish it. Usage: make_icon.py SRC DST
"""

import sys

from PIL import Image

src, dst = sys.argv[1], sys.argv[2]
im = Image.open(src).convert("RGBA")
side = max(im.size)
canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
canvas.save(dst, sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
