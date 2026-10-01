"""
Draw the app icon (a press sheet with a 2 x 3 gang of cards) and write:
  assets/icon.ico   Windows, multi-size
  assets/icon.png   1024 px, converted to .icns by the Mac build

    python tools/make_icon.py
"""

import struct
from pathlib import Path

import pymupdf as fitz

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def icon_png(px):
    doc = fitz.open()
    page = doc.new_page(width=256, height=256)
    shape = page.new_shape()
    shape.draw_rect(fitz.Rect(8, 8, 248, 248), radius=0.18)
    shape.finish(fill=(0.16, 0.18, 0.22), color=None)
    shape.draw_rect(fitz.Rect(58, 30, 198, 226))            # the sheet
    shape.finish(fill=(1, 1, 1), color=None)
    colours = [(0.0, 0.62, 0.86), (0.86, 0.1, 0.5), (0.98, 0.8, 0.1)]
    for r in range(3):
        for c in range(2):
            x0, y0 = 70 + c * 60, 44 + r * 60
            shape.draw_rect(fitz.Rect(x0, y0, x0 + 56, y0 + 48))
            shape.finish(fill=colours[r], color=None)
    shape.commit()
    return page.get_pixmap(matrix=fitz.Matrix(px / 256, px / 256), alpha=True).tobytes("png")


def main():
    ASSETS.mkdir(exist_ok=True)
    sizes = [256, 64, 48, 32, 16]
    images = [icon_png(s) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, data in zip(sizes, images):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
    (ASSETS / "icon.ico").write_bytes(header + entries + b"".join(images))
    (ASSETS / "icon.png").write_bytes(icon_png(1024))
    print("wrote assets/icon.ico and assets/icon.png")


if __name__ == "__main__":
    main()
