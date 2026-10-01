"""
Imposition engine: put many copies (or many different pages) of a PDF onto a
press sheet, ready to send to the Fiery as a plain job.

Modelled on Fiery Impose's Gangup screen, cut down to what Prestige prints on
the C4070: business cards, flyers, postcards, folded cards. No booklets.

Everything here is pure: no windows, no file dialogs. app.py (the screen)
and cli.py (the command line) both call plan() and render().

Units: settings are in inches (what the shop thinks in); PDF work is in points.

Layout modes
  gangup + repeat   Every slot on a sheet gets the same page. Duplex: page 1 on
                    the front, page 2 on the back. A 2-page card file = 1 sheet.
                    More pages = one sheet (or sheet pair) per page (pair).
  gangup + unique   Each slot gets a different page, in order. Duplex: pages are
                    front/back pairs (1+2, 3+4...), and each back lands directly
                    behind its front.
  normal            Pages flow in reading order, like a document. Duplex: the
                    front takes the next N pages, the back takes the N after
                    that, top-left first as you look at the back.

Duplex backs are mirrored left/right to sit behind their fronts, which matches
the Fiery's default (Top-Top) for a portrait sheet.

Gutters, including negative ones
  The gutter is the space between neighbouring slots, like Fiery's. A negative
  gutter pulls slots over each other. That's how Illustrator card files are run
  here: the page is the card plus bleed plus Illustrator's own marks (e.g. a
  3.5 x 2 card on a 4.083 x 2.583 page, 0.2917" each side), so a gutter of
  -0.5833" makes the cut lines meet. Where two slots overlap, the overlap is
  split down the middle and each piece is trimmed to its own half, so no piece
  ever prints over its neighbour. A positive gutter leaves the space between
  them empty (or, with Trim Box, lets bleed run to the middle of the gap).
"""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields, replace
from math import ceil, floor

import pymupdf as fitz

from .paths import PRESETS_FILE

PT = 72.0
INF = 1e9

# Optional guillotine marks (off by default; card files bring their own).
# Same style as the production agent's crop marks tool.
MARK_OFFSET_IN = 0.125   # gap between the cut line and the start of a mark
MARK_LENGTH_IN = 0.25
MARK_MIN_GAP_IN = 0.0625  # a mark never starts closer than this to printed art
MARK_WIDTH_PT = 0.25     # hairline
MARK_CMYK = (0.0, 0.0, 0.0, 1.0)  # 100% K, not rich black

# Fiery's default layout margin is 2.54 mm (0.1"), shown in its Settings panel
# as "Margin: Default". Like Fiery, anything that falls in this strip around the
# sheet edge is left blank: the press can't print there anyway.
SHEET_MARGIN_IN = 0.1

SHEETS = {  # name: (width, height) in inches, portrait
    "12 x 18": (12.0, 18.0),
    "13 x 19": (13.0, 19.0),
    "11 x 17": (11.0, 17.0),
    "8.5 x 11 (Letter)": (8.5, 11.0),
    "8.5 x 14 (Legal)": (8.5, 14.0),
}



@dataclass
class Settings:
    layout: str = "gangup"          # gangup | normal
    gang: str = "repeat"            # repeat | unique   (gangup only)
    finish: str = "crop"            # crop | trim  (what counts as one slot)
    sheet_w: float = 12.0           # inches, as named (portrait)
    sheet_h: float = 18.0
    orientation: str = "portrait"   # portrait | landscape
    duplex: bool = False
    rows: int = 1
    cols: int = 1
    gutter_x: float = 0.0           # inches between columns (negative = overlap)
    gutter_y: float = 0.0           # inches between rows
    scaling: str = "none"           # none | fit | custom
    scale_pct: float = 100.0        # used when scaling == custom
    marks: bool = False             # our guillotine marks; files usually carry their own

    def sheet_size(self):
        a, b = sorted((self.sheet_w, self.sheet_h))
        return (a, b) if self.orientation == "portrait" else (b, a)

    @classmethod
    def from_dict(cls, d):
        # "marks" isn't a preset setting any more: files bring their own.
        known = {f.name for f in fields(cls)} - {"marks"}
        d = dict(d)
        if isinstance(d.get("duplex"), str):  # older form: "off" / "leftright"
            d["duplex"] = d["duplex"] != "off"
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Placement:
    """One page drawn into one slot."""
    pno: int
    visible: fitz.Rect   # where it lands on the sheet (after trimming overlaps)
    clip: fitz.Rect      # the matching part of the source page
    cut: fitz.Rect       # where this piece is cut, on the sheet


@dataclass
class Plan:
    """Everything worked out, before anything is drawn."""
    settings: Settings
    sheet: tuple                    # (w, h) points, after orientation
    finish: tuple                   # (w, h) points of one slot's page area, unscaled
    scale: float
    cell: tuple                     # (w, h) points of one slot on the sheet
    grid: fitz.Rect                 # bounding box of all slots
    slots: list                     # fitz.Rect per slot, reading order, front side
    sides: list                     # [(front, back or None)], each a list of Placement
    errors: list = field(default_factory=list)    # stop: output would be wrong
    warnings: list = field(default_factory=list)  # look before printing

    @property
    def sheet_count(self):
        return len(self.sides)

    @property
    def per_sheet(self):
        return len(self.slots)


# ------------------------------------------------------------------- presets

def load_presets():
    """{name: Settings}. Missing or unreadable file = no presets."""
    try:
        raw = json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {name: Settings.from_dict(d) for name, d in raw.items()}


def _write_presets(presets):
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {name: asdict(s) for name, s in sorted(presets.items(), key=lambda kv: kv[0].lower())}
    fd, tmp = tempfile.mkstemp(dir=PRESETS_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PRESETS_FILE)  # never leaves a half-written file


def save_preset(name, settings):
    presets = load_presets()
    presets[name] = settings
    _write_presets(presets)


def delete_preset(name):
    presets = load_presets()
    if presets.pop(name, None) is not None:
        _write_presets(presets)


# ------------------------------------------------------------------ geometry

def finish_rect(page, finish):
    """
    The part of a source page that fills one slot, in page.rect coordinates
    (the page as you see it: crop box, rotation applied).

    crop: the whole visible page.
    trim: the TrimBox; anything outside it is bleed.
    """
    if finish == "crop":
        return fitz.Rect(page.rect)
    return trim_rect(page)


def trim_rect(page):
    trim = fitz.Rect(page.trimbox)
    crop = fitz.Rect(page.cropbox)
    trim = trim - (crop.x0, crop.y0, crop.x0, crop.y0)
    trim = trim * page.rotation_matrix
    trim.normalize()
    return trim & page.rect


def has_bleed(page):
    """True if the file declares a TrimBox smaller than the page: bleed built in."""
    t, r = trim_rect(page), page.rect
    return (t.width < r.width - 0.5) or (t.height < r.height - 0.5)


def bleed_sides(page):
    """(left, top, right, bottom) points between the trim box and the page edge."""
    t, r = trim_rect(page), page.rect
    return (t.x0 - r.x0, t.y0 - r.y0, r.x1 - t.x1, r.y1 - t.y1)


def mark_space():
    return (MARK_OFFSET_IN + MARK_LENGTH_IN) * PT


def usable_area(s):
    """Sheet area left for the grid once the margin and crop marks are allowed for."""
    w, h = (v * PT for v in s.sheet_size())
    edge = SHEET_MARGIN_IN * PT + (mark_space() if s.marks else 0)
    return w - 2 * edge, h - 2 * edge


def most_that_fit(s, finish_w, finish_h, scale=1.0):
    """(rows, cols) that fit on the sheet at this scale and gutter."""
    aw, ah = usable_area(s)
    cw, ch = finish_w * scale, finish_h * scale
    gx, gy = s.gutter_x * PT, s.gutter_y * PT
    cols = max(0, floor((aw + gx + 0.01) / (cw + gx))) if cw + gx > 0 else 0
    rows = max(0, floor((ah + gy + 0.01) / (ch + gy))) if ch + gy > 0 else 0
    return rows, cols


def _place(src, pno, slot, grid, s, scale, safe):
    """Work out one page in one slot: what shows, from where, and where it's cut."""
    page = src[pno]
    fin = finish_rect(page, s.finish)
    k = scale
    w, h = fin.width * k, fin.height * k
    cx, cy = (slot.x0 + slot.x1) / 2, (slot.y0 + slot.y1) / 2
    tf = fitz.Rect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)  # fin, on the sheet

    def to_sheet(r):
        return fitz.Rect(tf.x0 + (r.x0 - fin.x0) * k, tf.y0 + (r.y0 - fin.y0) * k,
                         tf.x0 + (r.x1 - fin.x0) * k, tf.y0 + (r.y1 - fin.y0) * k)

    # How far past its slot a piece may show on each side: all the way on the
    # outside of the layout, half the gutter where it meets a neighbour. A
    # negative half-gutter trims the piece back to the middle of the overlap.
    hx, hy = s.gutter_x * PT / 2, s.gutter_y * PT / 2
    on = lambda a, b: abs(a - b) < 0.01  # noqa: E731
    bound = fitz.Rect(slot.x0 - (INF if on(slot.x0, grid.x0) else hx),
                      slot.y0 - (INF if on(slot.y0, grid.y0) else hy),
                      slot.x1 + (INF if on(slot.x1, grid.x1) else hx),
                      slot.y1 + (INF if on(slot.y1, grid.y1) else hy))
    visible = to_sheet(page.rect) & bound & safe  # blank in the margin, like Fiery
    if visible.is_empty:
        return None
    clip = fitz.Rect(fin.x0 + (visible.x0 - tf.x0) / k, fin.y0 + (visible.y0 - tf.y0) / k,
                     fin.x0 + (visible.x1 - tf.x0) / k, fin.y0 + (visible.y1 - tf.y0) / k)
    # The cut: the file's own trim box if it has one, else the edge of what shows.
    cut = to_sheet(trim_rect(page)) if has_bleed(page) else fitz.Rect(visible)
    return Placement(pno, visible, clip, cut)


def _merge(values, tol=0.5):
    """Cut positions closer than tol points are one cut (a rounded gutter like
    -0.5833 leaves neighbours a hair apart)."""
    out = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def mark_lines(placements):
    """
    Guillotine marks: one per cut line, outside everything printed. Gutter 0
    means neighbouring pieces share a cut, so it gets one mark.
    Returns a list of (Point, Point).
    """
    if not placements:
        return []
    content = fitz.Rect(placements[0].visible)
    cut_box = fitz.Rect(placements[0].cut)
    for p in placements[1:]:
        content |= p.visible
        cut_box |= p.cut
    off, gap, length = MARK_OFFSET_IN * PT, MARK_MIN_GAP_IN * PT, MARK_LENGTH_IN * PT
    top = min(cut_box.y0 - off, content.y0 - gap)
    bottom = max(cut_box.y1 + off, content.y1 + gap)
    left = min(cut_box.x0 - off, content.x0 - gap)
    right = max(cut_box.x1 + off, content.x1 + gap)
    xs = _merge(v for p in placements for v in (p.cut.x0, p.cut.x1))
    ys = _merge(v for p in placements for v in (p.cut.y0, p.cut.y1))
    lines = []
    for x in xs:
        lines.append((fitz.Point(x, top), fitz.Point(x, top - length)))
        lines.append((fitz.Point(x, bottom), fitz.Point(x, bottom + length)))
    for y in ys:
        lines.append((fitz.Point(left, y), fitz.Point(left - length, y)))
        lines.append((fitz.Point(right, y), fitz.Point(right + length, y)))
    return lines


# ---------------------------------------------------------------------- plan

def plan(src, s):
    """Work out the layout for an open fitz.Document. Draws nothing."""
    s = replace(s)
    errors, warnings = [], []
    n_pages = len(src)
    sheet_w, sheet_h = (v * PT for v in s.sheet_size())
    sheet_rect = fitz.Rect(0, 0, sheet_w, sheet_h)
    m = SHEET_MARGIN_IN * PT
    safe = sheet_rect + (m, m, -m, -m)

    if s.rows < 1 or s.cols < 1:
        errors.append("Rows and columns must each be at least 1.")
        s.rows, s.cols = max(1, s.rows), max(1, s.cols)

    # The slot size: the largest page area across the file.
    finishes = [finish_rect(p, s.finish) for p in src]
    fw = max(r.width for r in finishes)
    fh = max(r.height for r in finishes)
    sizes = {(round(r.width / PT, 3), round(r.height / PT, 3)) for r in finishes}
    if len(sizes) > 1:
        shown = ", ".join(f'{w}" x {h}"' for w, h in sorted(sizes))
        warnings.append(f"Pages aren't all the same size ({shown}). Each slot is sized "
                        "for the largest and smaller pages are centred in it.")

    # Scale.
    gx, gy = s.gutter_x * PT, s.gutter_y * PT
    if s.scaling == "fit":
        aw, ah = usable_area(s)
        scale = min((aw - (s.cols - 1) * gx) / (s.cols * fw),
                    (ah - (s.rows - 1) * gy) / (s.rows * fh))
        if scale <= 0:
            errors.append("The gutters alone are wider than the sheet.")
            scale = 1.0
    elif s.scaling == "custom":
        if s.scale_pct <= 0:
            errors.append("Custom scale must be more than 0%.")
            scale = 1.0
        else:
            scale = s.scale_pct / 100.0
    else:
        scale = 1.0
    if abs(scale - 1.0) > 1e-6:
        warnings.append(f"Artwork is scaled to {scale * 100:.1f}%, so the finished pieces "
                        "won't be the file's size.")

    cw, ch = fw * scale, fh * scale
    if (s.cols > 1 and cw + gx <= 0) or (s.rows > 1 and ch + gy <= 0):
        errors.append("The negative gutter is bigger than the piece itself.")
        gx, gy = max(gx, -cw + 1), max(gy, -ch + 1)

    grid_w = s.cols * cw + (s.cols - 1) * gx
    grid_h = s.rows * ch + (s.rows - 1) * gy
    x0, y0 = (sheet_w - grid_w) / 2, (sheet_h - grid_h) / 2
    grid = fitz.Rect(x0, y0, x0 + grid_w, y0 + grid_h)
    slots = [fitz.Rect(x0 + c * (cw + gx), y0 + r * (ch + gy),
                       x0 + c * (cw + gx) + cw, y0 + r * (ch + gy) + ch)
             for r in range(s.rows) for c in range(s.cols)]
    per = len(slots)

    def mirror(rect):  # left/right, so a back sits behind its front
        return fitz.Rect(sheet_w - rect.x1, rect.y0, sheet_w - rect.x0, rect.y1)

    # Which page goes in which slot.
    sides = []  # [(front, back)] of [(slot, pno)]
    if s.layout == "gangup" and s.gang == "repeat":
        step = 2 if s.duplex else 1
        for p in range(0, n_pages, step):
            front = [(r, p) for r in slots]
            back = None
            if s.duplex:
                back = [(mirror(r), p + 1) for r in slots] if p + 1 < n_pages else []
            sides.append((front, back))
        if s.duplex and n_pages % 2:
            warnings.append(f"Duplex is on but the file has {n_pages} pages (odd), so the "
                            "last sheet has a blank back.")
    elif s.layout == "gangup":  # unique
        if s.duplex:
            if n_pages % 2:
                warnings.append(f"Duplex is on but the file has {n_pages} pages (odd). "
                                "Pages pair up as front/back, so the last piece has no back.")
            pieces = ceil(n_pages / 2)
            for start in range(0, pieces, per):
                front, back = [], []
                for j, piece in enumerate(range(start, min(start + per, pieces))):
                    front.append((slots[j], 2 * piece))
                    if 2 * piece + 1 < n_pages:
                        back.append((mirror(slots[j]), 2 * piece + 1))
                sides.append((front, back))
        else:
            for start in range(0, n_pages, per):
                sides.append(([(slots[j], p) for j, p in
                               enumerate(range(start, min(start + per, n_pages)))], None))
    else:  # normal: document order
        chunk = per * (2 if s.duplex else 1)
        for start in range(0, n_pages, chunk):
            front = [(slots[j], p) for j, p in
                     enumerate(range(start, min(start + per, n_pages)))]
            back = None
            if s.duplex:
                back = [(slots[j], p) for j, p in
                        enumerate(range(start + per, min(start + chunk, n_pages)))]
            sides.append((front, back))

    if s.layout == "gangup" and s.gang == "repeat" and n_pages > (2 if s.duplex else 1):
        warnings.append(f"Repeat with a {n_pages}-page file makes {len(sides)} different "
                        "sheets, one per " + ("front/back pair." if s.duplex else "page."))
    if s.layout != "gangup" or s.gang != "repeat":
        filled = sum(len(f) for f, _ in sides)
        empty = len(sides) * per - filled
        if empty:
            warnings.append(f"{empty} slot(s) on the last sheet are empty.")

    # Resolve each (slot, page) into what actually prints.
    s_eff = replace(s, gutter_x=gx / PT, gutter_y=gy / PT)
    mgrid = mirror(grid)

    def resolve(entries, back=False):
        if entries is None:
            return None
        g = mgrid if back else grid
        out = []
        for slot, pno in entries:
            pl = _place(src, pno, slot, g, s_eff, scale, safe)
            if pl:
                out.append(pl)
        return out

    resolved = [(resolve(f), resolve(b, back=s.layout != "normal")) for f, b in sides]

    # Bigger than the sheet is allowed (sometimes on purpose); just say so.
    if not sheet_rect.contains(grid):
        warnings.append(
            f'The layout is {grid_w / PT:.3f}" x {grid_h / PT:.3f}", bigger than the '
            f'{sheet_w / PT:g}" x {sheet_h / PT:g}" sheet. Whatever falls past the '
            f'{SHEET_MARGIN_IN}" margin is left blank.')

    return Plan(settings=s, sheet=(sheet_w, sheet_h), finish=(fw, fh), scale=scale,
                cell=(cw, ch), grid=grid, slots=slots, sides=resolved,
                errors=errors, warnings=warnings)


# -------------------------------------------------------------------- render

def render(src, plan_, sheets=None):
    """
    Build the imposed PDF as a new fitz.Document. `sheets` limits it to some
    sheet indexes (the preview only needs one).
    """
    out = fitz.open()
    sw, sh = plan_.sheet
    indexes = range(plan_.sheet_count) if sheets is None else sheets
    for i in indexes:
        for entries in plan_.sides[i]:
            if entries is None:
                continue
            page = out.new_page(width=sw, height=sh)
            for pl in entries:
                page.show_pdf_page(pl.visible, src, pl.pno, clip=pl.clip,
                                   keep_proportion=False)
            if plan_.settings.marks and entries:
                shape = page.new_shape()
                for a, b in mark_lines(entries):
                    shape.draw_line(a, b)
                # closePath=False: a trailing 'h' would double-stroke the last mark.
                shape.finish(color=MARK_CMYK, width=MARK_WIDTH_PT, closePath=False)
                shape.commit()
            if entries:
                cut = fitz.Rect(entries[0].cut)
                for pl in entries[1:]:
                    cut |= pl.cut
                cut &= page.rect
                if not cut.is_empty:
                    page.set_trimbox(cut)
    return out


def describe(plan_, n_pages):
    """One-paragraph summary for the screen and the command line."""
    s = plan_.settings
    fw, fh = (v / PT for v in plan_.finish)
    sw, sh = (v / PT for v in plan_.sheet)
    mode = "Normal" if s.layout == "normal" else f"Gangup, {s.gang}"
    dup = "duplex" if s.duplex else "single-sided"
    return (f'{n_pages} page(s), {fw:.3f}" x {fh:.3f}" each. {mode}, {s.rows} x {s.cols} = '
            f'{plan_.per_sheet} up on {sw:g}" x {sh:g}" {s.orientation}, {dup}. '
            f"{plan_.sheet_count} sheet(s) to print.")


# ------------------------------------------------------------------- preview

def render_preview(src, plan_, sheet_index, zoom, cache):
    """
    Fast on-screen picture of one sheet (front, and back if duplex), as
    Pixmaps. Each source page is drawn once at preview size and kept in
    `cache` (a dict the caller owns and clears when the file changes); every
    slot is then a pixel copy of the visible part. Same layout as render(),
    but the saved PDF always comes from render(), never from this.
    """
    sw, sh = plan_.sheet
    k = plan_.scale
    out = []
    for entries in plan_.sides[sheet_index]:
        if entries is None:
            continue
        sheet = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, round(sw * zoom), round(sh * zoom)), False)
        sheet.clear_with(255)
        for pl in entries:
            page = src[pl.pno]
            key = (pl.pno, round(zoom * k, 5))
            pix = cache.get(key)
            if pix is None:
                pix = page.get_pixmap(matrix=fitz.Matrix(zoom * k, zoom * k), alpha=False)
                cache[key] = pix
            # Where the whole page would sit on the sheet; show only `visible`.
            pr = page.rect
            full_x0 = pl.visible.x0 - (pl.clip.x0 - pr.x0) * k
            full_y0 = pl.visible.y0 - (pl.clip.y0 - pr.y0) * k
            pix.set_origin(round(full_x0 * zoom), round(full_y0 * zoom))
            sheet.copy(pix, fitz.IRect(round(pl.visible.x0 * zoom), round(pl.visible.y0 * zoom),
                                       round(pl.visible.x1 * zoom), round(pl.visible.y1 * zoom)))
        out.append(sheet)
    return out
