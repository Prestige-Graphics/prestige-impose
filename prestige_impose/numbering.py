"""
Numbered tickets (raffle tickets, numbered forms).

The ticket is a PDF: page 1 the front, page 2 the back (optional). Number
boxes are drawn on the front in the number editor; every box on a ticket
shows the same number (typically one on the ticket, one on the stub). Numbers
only go on the front (Leo, 2026-10-05: 9.9 times out of 10).

The ticket is laid out once (like Gangup repeat) and the plan repeats that
sheet as many times as the run needs, each piece carrying its number; the
numbers are drawn straight onto the sheet when the PDF is made
(draw_on_sheet). Numbers run in order across a sheet and on to the next:
sheet 1 has 1-10, sheet 2 has 11-20 and so on. The artwork goes into the PDF
once and every ticket refers to it, so thousands stay small and quick.
"""

import pymupdf as fitz

# name shown: MuPDF's built-in font (Nimbus, metric-compatible with these)
FONTS = {
    "Helvetica": "helv", "Helvetica Bold": "hebo",
    "Times": "tiro", "Times Bold": "tibo",
    "Courier": "cour", "Courier Bold": "cobo",
}
COLOURS = {"Red": (0.0, 1.0, 1.0, 0.0), "Black": (0.0, 0.0, 0.0, 1.0)}   # CMYK
ALIGNS = ("left", "center", "right")
ROTATIONS = (0, 90, 270)   # 90: reads bottom to top; 270: top to bottom
FONT_NAME = "PINum"
MAX_TICKETS = 50000


def number_text(n, s):
    """What one ticket's number reads, e.g. "No. 0042"."""
    digits = str(n)
    if s.num_zeros:
        digits = digits.zfill(len(str(s.num_start + s.num_count - 1)))
    return f"{s.num_prefix}{digits}"


def numbers(s):
    return range(s.num_start, s.num_start + s.num_count)


def _font(s):
    return fitz.Font(FONTS.get(s.num_font, "helv"))


BOX_COLOURS = {"White": (0.0, 0.0, 0.0, 0.0), "Yellow": (0.0, 0.0, 1.0, 0.0),
               "Black": (0.0, 0.0, 0.0, 1.0), "Red": (0.0, 1.0, 1.0, 0.0)}   # CMYK
FITS = ("number", "widest")   # background hugs each number, or is the widest number's width


def widest(s, font):
    """Width (at 1 pt) of the longest number in the run, text before included."""
    last = s.num_start + s.num_count - 1
    return max(font.text_length(number_text(n, s), 1) for n in {s.num_start, last})


def _half_height(font):
    """Half the height of the digits (in ems): numbers are centred on this."""
    return font.glyph_bbox(ord("8")).y1 / 2


def _parts(box, tw, ww, fs, length, scale):
    """
    One box laid out across its own width, before turning, as offsets from the
    box centre: (background left, right, or None) and where the text starts.
    tw is this number's width, ww the widest number's.
    """
    align = box.get("align", "center")
    framed = bool(box.get("bg") or box.get("border"))
    pad = float(box.get("pad", 2)) * scale if framed else 0.0
    grow = _grow(box) * scale    # the border's outer half: keep it inside the box too
    bw = (ww if box.get("bg_fit") == "widest" else tw) + 2 * pad
    x0 = {"left": -length / 2 + grow, "right": length / 2 - bw - grow}.get(align, -bw / 2)
    tx = {"left": x0 + pad, "right": x0 + bw - pad - tw}.get(align, -tw / 2)
    return ((x0, x0 + bw) if framed else None), tx


def _grow(box):
    return float(box.get("border_w", 0.5)) / 2 if box.get("border") else 0.0


def _draw_box(shape, box, text, s, font, ww, m=fitz.Identity, scale=1.0, angle=0):
    """One box's background, border and number, through mapping m (page to sheet)."""
    r = fitz.Rect(box["rect"])
    rot = int(box.get("rotate", 0)) % 360
    fs = float(box.get("size", 14)) * scale
    c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2) * m
    length = (r.width if rot in (0, 180) else r.height) * scale
    bg, tx = _parts(box, font.text_length(text, fs), ww * fs, fs, length, scale)
    half = _half_height(font) * fs
    # The box's own turn, then the piece's turn on the sheet (clockwise).
    turn = fitz.Matrix(rot) * fitz.Matrix(-angle)
    if bg:
        pad = float(box.get("pad", 2)) * scale
        border = box.get("border")
        shape.draw_rect(fitz.Rect(c.x + bg[0], c.y - half - pad, c.x + bg[1], c.y + half + pad))
        shape.finish(fill=tuple(box["bg"]) if box.get("bg") else None,
                     color=tuple(border) if border else None,
                     width=float(box.get("border_w", 0.5)) * scale if border else 0,
                     morph=(c, turn))
    shape.insert_text(fitz.Point(c.x + tx, c.y + half), text, fontname=FONT_NAME, fontsize=fs,
                      color=tuple(s.num_colour), morph=(c, turn))


def box_size(box, s, font=None):
    """How long (along the text) and how thick a box is: it wraps the longest
    number in the run, plus padding and border when it has a background or border."""
    font = font or _font(s)
    fs = float(box.get("size", 14))
    framed = bool(box.get("bg") or box.get("border"))
    edge = (float(box.get("pad", 2)) if framed else 0.0) + _grow(box)
    return widest(s, font) * fs + 2 * edge, 2 * _half_height(font) * fs + 2 * edge


def _along(rot):
    """Which way the text runs on the page (a unit step)."""
    return fitz.Point(1, 0) * fitz.Matrix(-rot)   # morph turns in PDF space (y up)


def fit_box(box, s, font=None):
    """
    The box resized to wrap what's in it (the longest number, padding, border),
    keeping its aligned end where it is: a left-aligned box grows to the right,
    a right-aligned one to the left, a centred one both ways. Boxes are always
    drawn fitted, so a longer run or a bigger size grows them automatically.
    """
    r = fitz.Rect(box["rect"])
    rot = int(box.get("rotate", 0)) % 360
    u = _along(rot)
    side = {"left": -1, "right": 1}.get(box.get("align", "center"), 0)
    old = r.width if rot in (0, 180) else r.height
    length, thick = box_size(box, s, font)
    c = (r.tl + r.br) * 0.5 + u * (side * (old - length) / 2)
    w, h = (length, thick) if rot in (0, 180) else (thick, length)
    return {**box, "rect": [round(v, 2) for v in (c.x - w / 2, c.y - h / 2,
                                                  c.x + w / 2, c.y + h / 2)]}


def draw_numbers(page, s, n, font=None):
    """Draw ticket number n in every box on this page (page coordinates)."""
    font = font or _font(s)
    page.insert_font(fontname=FONT_NAME, fontbuffer=font.buffer)
    text, ww = number_text(n, s), widest(s, font)
    shape = page.new_shape()
    for box in (fit_box(b, s, font) for b in s.num_boxes):
        _draw_box(shape, box, text, s, font, ww)
    shape.commit()


def number_sheet(sheet, placements, s, scale, font=None):
    """
    Write the ticket numbers of one imposed sheet: each placement's number in
    each box, mapped from the front page to where that piece landed (scaled,
    turned). All in one go per sheet, which keeps a long run quick. Backgrounds
    go under every number (a shape's drawings come before its text).
    """
    font = font or _font(s)
    sheet.insert_font(fontname=FONT_NAME, fontbuffer=font.buffer)
    ww = widest(s, font)
    boxes = [fit_box(b, s, font) for b in s.num_boxes]
    shape = sheet.new_shape()
    for pl in placements:
        if pl.number is None:
            continue
        text = number_text(pl.number, s)
        m = page_to_sheet(pl, scale)
        for box in boxes:
            _draw_box(shape, box, text, s, font, ww, m, scale, pl.angle)
    shape.commit()


def page_to_sheet(pl, scale):
    """Matrix taking front-page points to sheet points for a placement (the
    same mapping the placement was drawn with)."""
    m = (fitz.Matrix(1, 0, 0, 1, -pl.clip.x0, -pl.clip.y0) * fitz.Matrix(scale, scale)
         * fitz.Matrix(pl.angle))
    turned = fitz.Rect(pl.clip) * m
    return m * fitz.Matrix(1, 0, 0, 1, pl.visible.x0 - turned.x0, pl.visible.y0 - turned.y0)


def sample_page(src, s, n=None):
    """The front with number n (default: the first) drawn on it, for the editor."""
    doc = fitz.open()
    page = doc.new_page(width=src[0].rect.width, height=src[0].rect.height)
    page.show_pdf_page(page.rect, src, 0)
    if s.num_boxes:
        draw_numbers(page, s, s.num_start if n is None else n)
    return doc
