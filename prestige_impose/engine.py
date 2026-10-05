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
  normal            One page per sheet, in order, like a document (as in Fiery;
                    rows, columns and gutters don't apply). Duplex: page 1 on
                    the front, page 2 on the back, and so on.

Duplex backs are mirrored left/right to sit behind their fronts, which matches
the Fiery's default (Top-Top) for a portrait sheet. A turned piece's back is
turned the other way, so it still lines up after the sheet flips.

Turning pieces
  rotate 90         every piece is turned a quarter turn (to fit more on a sheet).
  layout style      like Fiery Impose: standard; head to head (row 1 upside
                    down, row 2 upright, so their tops meet; and so on in
                    pairs); foot to foot (row 2 upside down, so their bottoms
                    meet). With pieces turned 90 it's pairs of columns.
  180 slot rotation every piece on the front, the back, or both turned upside
                    down (Fiery's "top finished edge", for top-bound duplex).

Crop marks
  none / outside    marks around the layout, at every cut line (or none).
  stretch / enlarge each piece keeps 0.125" of bleed and gets marks. A page
                    with no bleed has bleed made first, either by mirroring its
                    outer 0.125" outward (stretch: the design isn't touched) or
                    by enlarging the whole page (enlarge: edges get cut off).
                    Either way it still cuts to its original size.

Cut lines
  The cut line of a piece is the file's TrimBox if it has one. If it doesn't,
  the file's own crop marks are looked for (short lines running in from the
  page edge, as Illustrator and InDesign export them).

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

from .paths import PRESETS_FILE   # mypresets.activate() points this at this computer's list

PT = 72.0
INF = 1e9

# Optional guillotine marks (off by default; card files bring their own).
# Same style as the production agent's crop marks tool.
MARK_OFFSET_IN = 0.125   # gap between the cut line and the start of a mark
MARK_LENGTH_IN = 0.25
MARK_MIN_GAP_IN = 0.0625  # a mark never starts closer than this to printed art
MARK_MIN_IN = 0.05       # marks are shortened to fit the sheet margin, but not below this
MARK_WIDTH_PT = 0.25     # hairline
MARK_CMYK = (0.0, 0.0, 0.0, 1.0)  # 100% K, not rich black
BLEED_IN = 0.125         # crop marks "with bleed": each piece keeps this much past its cut
BLEED_MODES = ("stretch", "enlarge")
LAYOUT_STYLES = ("standard", "head", "foot")
SLOT_180 = ("none", "front", "back", "both")

# How much of a file's own crop marks must still show between pieces when they
# are pulled in. From Leo's "Illustrator Business Cards 12x18" preset: on an
# Illustrator card (marks start 0.083" outside the cut, 0.458" of slug) his
# -0.63" gutter leaves 0.06" of every mark showing, enough to cut by.
MARK_SHOW_IN = 0.06

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
    back_same: bool = False         # duplex with each page printed on both sides
    rows: int = 1
    cols: int = 1
    gutter_x: float = 0.0           # inches between columns (negative = overlap)
    gutter_y: float = 0.0           # inches between rows
    scaling: str = "none"           # none | fit | custom
    scale_pct: float = 100.0        # used when scaling == custom
    rotate: int = 0                 # 0 | 90: turn every piece a quarter turn
    layout_style: str = "standard"  # standard | head | foot (head to head, foot to foot)
    slot_180: str = "none"          # none | front | back | both: those pieces upside down
    crop_marks: str = "none"        # none | outside | stretch | enlarge (see the top)
    # Presets only: the gutters were "pulled in" when it was saved, so each file
    # gets its own pull-in gutters instead of the saved numbers (cards with
    # different amounts of slug around them need different gutters).
    pull_in: bool = False

    @property
    def marks(self):
        return self.crop_marks != "none"

    @property
    def adds_bleed(self):
        return self.crop_marks in BLEED_MODES

    def sheet_size(self):
        a, b = sorted((self.sheet_w, self.sheet_h))
        return (a, b) if self.orientation == "portrait" else (b, a)

    @classmethod
    def from_dict(cls, d):
        # Old presets had a "marks" yes/no; crop marks are now "crop_marks".
        known = {f.name for f in fields(cls)}
        d = dict(d)
        if isinstance(d.get("duplex"), str):  # older form: "off" / "leftright"
            d["duplex"] = d["duplex"] != "off"
        if d.get("crop_marks") == "between":  # 1.2.0's "outside + between pieces"
            d["crop_marks"] = "outside"
        # 1.2.0's head-to-head turned rows 2, 4, 6..., which is foot to foot.
        if "layout_style" not in d and d.get("head_to_head"):
            d["layout_style"] = "foot"
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class Placement:
    """One page drawn into one slot."""
    pno: int
    visible: fitz.Rect   # where it lands on the sheet (after trimming overlaps)
    clip: fitz.Rect      # the matching part of the source page
    cut: fitz.Rect       # where this piece is cut, on the sheet
    angle: int = 0       # clockwise turn of the piece on the sheet: 0, 90, 180, 270


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
    finished: tuple = (0.0, 0.0)    # (w, h) points each piece ends up after cutting
    source: object = None           # the document placed (src, or src with bleed made)
    errors: list = field(default_factory=list)    # stop: output would be wrong
    warnings: list = field(default_factory=list)  # look before printing

    @property
    def sheet_count(self):
        return len(self.sides)

    @property
    def per_sheet(self):
        return len(self.slots)


# ------------------------------------------------------------------- presets

def _read_presets_file():
    try:
        return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def load_presets():
    """{name: Settings}. Missing or unreadable file = no presets."""
    return {name: Settings.from_dict(d) for name, d in _read_presets_file().items()}


def load_preset_sizes():
    """{name: (w, h) inches} of the file each preset was saved with, where known."""
    out = {}
    for name, d in _read_presets_file().items():
        size = d.get("match_size")
        if isinstance(size, list) and len(size) == 2:
            out[name] = (float(size[0]), float(size[1]))
    return out


def presets_for_size(w_in, h_in, tol=0.01):
    """Preset names saved with a file of this page size (either way round)."""
    hits = []
    for name, (pw, ph) in load_preset_sizes().items():
        if ((abs(pw - w_in) <= tol and abs(ph - h_in) <= tol)
                or (abs(pw - h_in) <= tol and abs(ph - w_in) <= tol)):
            hits.append(name)
    return hits


def presets_for_file(src):
    """
    Preset names to suggest for an open file, best first. A preset matches if
    it was saved with a file of the same page size, or with a file that cuts
    to the same size and either pulls in per file (pull_in) or pulls in to the
    preset's own gutters. A preset with fixed gutters isn't offered for a card
    whose marks those gutters would hide.
    """
    page = src[0]
    w, h = page.rect.width / PT, page.rect.height / PT
    t = trim_rect(page)
    cw, ch = t.width / PT, t.height / PT

    def same(a, b, tol=0.01):
        return ((abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol)
                or (abs(a[0] - b[1]) <= tol and abs(a[1] - b[0]) <= tol))

    exact, close = [], []
    for name, d in _read_presets_file().items():
        size, cut = d.get("match_size"), d.get("match_cut")
        if isinstance(size, list) and len(size) == 2 and same(size, (w, h)):
            exact.append(name)
        elif isinstance(cut, list) and len(cut) == 2 and same(cut, (cw, ch)):
            s = Settings.from_dict(d)
            pull = pull_in_gutters(src, s)
            if pull and (s.pull_in or (abs(pull[0] - s.gutter_x) <= 0.02
                                       and abs(pull[1] - s.gutter_y) <= 0.02)):
                close.append(name)
    return exact + close


def settings_for_file(src, s):
    """A preset's settings for this file: pull_in presets get this file's own
    pull-in gutters (if it has a cut line to go by)."""
    s = replace(s)
    if s.pull_in:
        g = pull_in_gutters(src, s)
        if g:
            s.gutter_x, s.gutter_y = g
    return s


def _write_presets(raw):
    PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = dict(sorted(raw.items(), key=lambda kv: kv[0].lower()))
    fd, tmp = tempfile.mkstemp(dir=PRESETS_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, PRESETS_FILE)  # never leaves a half-written file


def save_preset(name, settings, match_size=None, match_cut=None):
    """match_size / match_cut: (w, h) inches of the page and cut of the file it
    was made with, to suggest it later (see presets_for_file)."""
    raw = _read_presets_file()
    entry = asdict(settings)
    for key, value in (("match_size", match_size), ("match_cut", match_cut)):
        if value:
            entry[key] = [round(value[0], 4), round(value[1], 4)]
        elif isinstance(raw.get(name, {}).get(key), list):
            entry[key] = raw[name][key]
    raw[name] = entry
    _write_presets(raw)


def delete_preset(name):
    raw = _read_presets_file()
    if raw.pop(name, None) is not None:
        _write_presets(raw)


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


def _declared_trim(page):
    trim = fitz.Rect(page.trimbox)
    crop = fitz.Rect(page.cropbox)
    trim = trim - (crop.x0, crop.y0, crop.x0, crop.y0)
    trim = trim * page.rotation_matrix
    trim.normalize()
    return trim & page.rect


def _inset(t, r):
    return (t.width < r.width - 0.5) or (t.height < r.height - 0.5)


def _scan_marks(page):
    """
    The file's own crop marks: (cut rect, gaps) or None. gaps is (left, top,
    right, bottom), the distance in points from the cut line to where the
    marks on that side start. Marks are short straight lines running in from
    the page edge (0.4" or less), lined up with the cut. A cut line only counts
    if marks for it sit on both opposite edges, so lines in the artwork aren't
    mistaken for marks.
    """
    cache = getattr(page.parent, "_prestige_marks", None)
    if cache is None:
        cache = {}
        try:
            page.parent._prestige_marks = cache
        except AttributeError:
            pass
    if page.number in cache:
        return cache[page.number]
    r = page.rect
    edge, longest = 2.0, 0.4 * PT
    # (position along the edge, inner end) of the marks on each edge
    top, bottom, left, right = [], [], [], []
    for d in page.get_drawings():
        for it in d.get("items", ()):
            if it[0] != "l":
                continue
            a, b = it[1], it[2]
            if abs(a - b) > longest or abs(a - b) < 2:
                continue
            if abs(a.x - b.x) < 0.3:                    # vertical
                if min(a.y, b.y) <= r.y0 + edge:
                    top.append((a.x, max(a.y, b.y)))
                elif max(a.y, b.y) >= r.y1 - edge:
                    bottom.append((a.x, min(a.y, b.y)))
            elif abs(a.y - b.y) < 0.3:                  # horizontal
                if min(a.x, b.x) <= r.x0 + edge:
                    left.append((a.y, max(a.x, b.x)))
                elif max(a.x, b.x) >= r.x1 - edge:
                    right.append((a.y, min(a.x, b.x)))

    def both(one, other):
        return sorted(v for v in _merge([m[0] for m in one], 0.6)
                      if any(abs(v - w[0]) < 0.6 for w in other))

    def gap(marks, cuts, dist):
        ds = [dist(inner) for pos, inner in marks if any(abs(pos - c) < 0.6 for c in cuts)]
        return max(0.0, min(ds)) if ds else 0.0

    result = None
    xs, ys = both(top, bottom), both(left, right)
    if len(xs) >= 2 and len(ys) >= 2:
        t = fitz.Rect(xs[0], ys[0], xs[-1], ys[-1])
        if t.width >= r.width * 0.3 and t.height >= r.height * 0.3 and _inset(t, r):
            gaps = (gap(left, ys, lambda v: t.x0 - v), gap(top, xs, lambda v: t.y0 - v),
                    gap(right, ys, lambda v: v - t.x1), gap(bottom, xs, lambda v: v - t.y1))
            result = (t, gaps)
    cache[page.number] = result
    return result


def find_crop_marks(page):
    """The cut line from the file's own crop marks, or None."""
    found = _scan_marks(page)
    return fitz.Rect(found[0]) if found else None


def own_mark_gaps(page):
    """(left, top, right, bottom) points from the cut line to the file's own
    crop marks, or None if the file has no marks of its own."""
    found = _scan_marks(page)
    return found[1] if found else None


def trim_rect(page):
    """Where this page is cut: its TrimBox, else its own crop marks, else the page edge."""
    doc = page.parent
    cache = getattr(doc, "_prestige_trim", None)
    if cache is None:
        cache = {}
        try:
            doc._prestige_trim = cache
        except AttributeError:
            pass
    key = page.number
    if key not in cache:
        t = _declared_trim(page)
        if not _inset(t, page.rect):
            t = find_crop_marks(page) or fitz.Rect(page.rect)
        cache[key] = t
    return fitz.Rect(cache[key])


def has_bleed(page):
    """True if the page has a cut line inside it (TrimBox or its own crop marks)."""
    return _inset(trim_rect(page), page.rect)


def bleed_sides(page):
    """(left, top, right, bottom) points between the cut line and the page edge."""
    t, r = trim_rect(page), page.rect
    return (t.x0 - r.x0, t.y0 - r.y0, r.x1 - t.x1, r.y1 - t.y1)


def _spare_sides(page):
    """
    Per side (left, top, right, bottom), how much of the page past the cut
    line can be given up: everything beyond the file's own crop marks plus
    MARK_SHOW_IN of them. If the file has no marks of its own, the whole bleed.
    """
    bl, bt, br, bb = bleed_sides(page)
    gaps = own_mark_gaps(page)
    if not gaps:
        return (bl, bt, br, bb)
    show = MARK_SHOW_IN * PT
    return tuple(max(0.0, b - (g + show)) for b, g in zip((bl, bt, br, bb), gaps))


def pull_in_gutters(src, s):
    """
    The gutters (inches) that pull the pieces in as far as the shop does: until
    only MARK_SHOW_IN of the file's own crop marks still shows between them
    (so they can be cut by), or, for a file without its own marks, until the
    cut lines meet. None if the file has no cut line inside the page.
    """
    page = src[0]
    if s.finish == "trim":
        return (0.0, 0.0) if has_bleed(page) else None
    if not has_bleed(page):
        return None
    k = s.scale_pct / 100 if s.scaling == "custom" else 1.0
    sl, st, sr, sb = _spare_sides(page)
    gx, gy = -(sl + sr) * k / PT, -(st + sb) * k / PT
    if s.rotate % 180:
        gx, gy = gy, gx
    return round(gx, 4), round(gy, 4)


def keeps_own_marks(src):
    """True if pulling in stops at the file's own crop marks (not the cut lines)."""
    return bool(own_mark_gaps(src[0])) and has_bleed(src[0])


def outer_spare(src, s):
    """
    (x, y) points, both sides together, by which the outside pieces' pages may
    run past the sheet margin. A file with its own crop marks only needs the
    cut and a bit of the marks to show on the outside; other files keep their
    whole bleed. If the app draws crop marks, they need MARK_OFFSET_IN plus at
    least MARK_MIN_IN past the cut (they're shortened to fit). Can be negative.
    """
    k = s.scale_pct / 100 if s.scaling == "custom" else 1.0
    mark_need = (MARK_OFFSET_IN + MARK_MIN_IN) * PT if s.marks else 0.0
    if s.finish == "crop" and has_bleed(src[0]):
        slug = bleed_sides(src[0])
        if s.adds_bleed:
            keep = [min(b, BLEED_IN * PT) for b in slug]
        elif keeps_own_marks(src):
            show = MARK_SHOW_IN * PT
            keep = [min(b, g + show) for b, g in zip(slug, own_mark_gaps(src[0]))]
        else:
            keep = list(slug)
        sl, st, sr, sb = (b * k - max(kp * k, mark_need) for b, kp in zip(slug, keep))
    else:
        sl = st = sr = sb = -mark_need
    x, y = sl + sr, st + sb
    return (y, x) if s.rotate % 180 else (x, y)


def mark_space():
    return (MARK_OFFSET_IN + MARK_LENGTH_IN) * PT


def usable_area(s):
    """Sheet area left for the grid once the margin and crop marks are allowed for."""
    w, h = (v * PT for v in s.sheet_size())
    edge = SHEET_MARGIN_IN * PT + (mark_space() if s.marks else 0)
    return w - 2 * edge, h - 2 * edge


def most_that_fit(s, finish_w, finish_h, scale=1.0, spare=None):
    """
    (rows, cols) that fit on the sheet at this scale, gutter and piece rotation.
    spare: outer_spare() for the file; without it, whole pages plus full-length
    crop marks have to fit inside the margin.
    """
    if spare is None:
        aw, ah = usable_area(s)
    else:
        w, h = (v * PT for v in s.sheet_size())
        m = SHEET_MARGIN_IN * PT
        aw, ah = w - 2 * m + spare[0], h - 2 * m + spare[1]
    cw, ch = finish_w * scale, finish_h * scale
    if s.rotate % 180:
        cw, ch = ch, cw
    gx, gy = s.gutter_x * PT, s.gutter_y * PT
    cols = max(0, floor((aw + gx + 0.01) / (cw + gx))) if cw + gx > 0 else 0
    rows = max(0, floor((ah + gy + 0.01) / (ch + gy))) if ch + gy > 0 else 0
    return rows, cols


def fit_gutters(src, s):
    """The gutters Fit most uses: room for the bleed when crop marks are "with
    bleed", else pulled in (pull_in_gutters). None: keep the current ones."""
    if s.adds_bleed:
        return (2 * BLEED_IN, 2 * BLEED_IN)
    return pull_in_gutters(src, s)


def best_fit(src, s):
    """
    Fit most, done the way the shop does it: pull the pieces in as far as
    their crop marks allow (pull_in_gutters), then try the pieces both upright
    and turned 90 degrees and keep whichever fits more. Files with no cut line
    keep the gutters they have.
    Returns (rows, cols, rotate, gutter_x, gutter_y) or None if nothing fits.
    """
    fin = finish_rect(src[0], s.finish)
    k = s.scale_pct / 100 if s.scaling == "custom" else 1.0
    best = None
    for rot in ((s.rotate, 90 - s.rotate) if s.rotate in (0, 90) else (s.rotate,)):
        t = replace(s, rotate=rot)
        pull = fit_gutters(src, t)
        gx, gy = pull if pull else (t.gutter_x, t.gutter_y)
        t = replace(t, gutter_x=gx, gutter_y=gy)
        r, c = most_that_fit(t, fin.width, fin.height, k, outer_spare(src, t))
        if r and c and (best is None or r * c > best[0] * best[1]):
            best = (r, c, rot, gx, gy)
    return best


def _place(src, pno, slot, grid, s, scale, safe, angle=0):
    """
    Work out one page in one slot: what shows, from where, and where it's cut.
    `angle` turns the piece clockwise on the sheet (0, 90, 180, 270).
    """
    page = src[pno]
    fin = finish_rect(page, s.finish)
    k = scale
    sc = fitz.Point((slot.x0 + slot.x1) / 2, (slot.y0 + slot.y1) / 2)
    fc = fitz.Point((fin.x0 + fin.x1) / 2, (fin.y0 + fin.y1) / 2)
    # Source page -> sheet: centre the piece on the slot, scale, turn.
    m = (fitz.Matrix(1, 0, 0, 1, -fc.x, -fc.y) * fitz.Matrix(k, k) * fitz.Matrix(angle)
         * fitz.Matrix(1, 0, 0, 1, sc.x, sc.y))

    def to_sheet(r):
        q = fitz.Rect(r) * m
        q.normalize()
        return q

    # How far past its slot a piece may show on each side: all the way on the
    # outside of the layout, half the gutter where it meets a neighbour. A
    # negative half-gutter trims the piece back to the middle of the overlap.
    hx, hy = s.gutter_x * PT / 2, s.gutter_y * PT / 2
    on = lambda a, b: abs(a - b) < 0.01  # noqa: E731
    bound = fitz.Rect(slot.x0 - (INF if on(slot.x0, grid.x0) else hx),
                      slot.y0 - (INF if on(slot.y0, grid.y0) else hy),
                      slot.x1 + (INF if on(slot.x1, grid.x1) else hx),
                      slot.y1 + (INF if on(slot.y1, grid.y1) else hy))
    if s.adds_bleed and has_bleed(page):
        t, b = trim_rect(page), BLEED_IN * PT
        gl, gt, gr, gb = own_mark_gaps(page) or (b, b, b, b)
        bound &= to_sheet(fitz.Rect(t.x0 - min(b, gl), t.y0 - min(b, gt),
                                    t.x1 + min(b, gr), t.y1 + min(b, gb)))
    visible = to_sheet(page.rect) & bound & safe  # blank in the margin, like Fiery
    if visible.is_empty:
        return None
    clip = fitz.Rect(visible) * ~m
    clip.normalize()
    # The cut: the file's own cut line if it has one, else the edge of what shows.
    cut = to_sheet(trim_rect(page)) if has_bleed(page) else fitz.Rect(visible)
    return Placement(pno, visible, clip, cut, angle)


def _merge(values, tol=0.5):
    """Cut positions closer than tol points are one cut (a rounded gutter like
    -0.5833 leaves neighbours a hair apart)."""
    out = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def mark_lines(placements, safe):
    """
    Guillotine marks around the layout: one per cut line, starting
    MARK_OFFSET_IN out from the outermost cut (past the bleed) and running
    outward, cut short at the sheet margin (`safe`) so they always print. A
    side with less than 0.05" of room gets none. Gutter 0 means neighbours
    share a cut, so it gets one mark. Returns a list of (Point, Point).
    """
    if not placements:
        return []
    cut_box = fitz.Rect(placements[0].cut)
    for p in placements[1:]:
        cut_box |= p.cut
    off, length, least = MARK_OFFSET_IN * PT, MARK_LENGTH_IN * PT, MARK_MIN_IN * PT
    xs = _merge(v for p in placements for v in (p.cut.x0, p.cut.x1))
    ys = _merge(v for p in placements for v in (p.cut.y0, p.cut.y1))
    lines = []

    def add(a, b):
        if abs(a - b) >= least:
            lines.append((a, b))

    top, bottom = cut_box.y0 - off, cut_box.y1 + off
    left, right = cut_box.x0 - off, cut_box.x1 + off
    for x in xs:
        if top > safe.y0:
            add(fitz.Point(x, top), fitz.Point(x, max(top - length, safe.y0)))
        if bottom < safe.y1:
            add(fitz.Point(x, bottom), fitz.Point(x, min(bottom + length, safe.y1)))
    for y in ys:
        if left > safe.x0:
            add(fitz.Point(left, y), fitz.Point(max(left - length, safe.x0), y))
        if right < safe.x1:
            add(fitz.Point(right, y), fitz.Point(min(right + length, safe.x1), y))
    return lines


def sheet_marks(plan_, entries):
    """All the crop marks the settings ask for on one side of a sheet."""
    if not plan_.settings.marks or not entries:
        return []
    sw, sh = plan_.sheet
    m = SHEET_MARGIN_IN * PT
    return mark_lines(entries, fitz.Rect(m, m, sw - m, sh - m))


# ------------------------------------------------------------- making bleed

def _bleed_page(out, src, pno, how):
    """
    Add to `out` a copy of src page pno, BLEED_IN bigger all round, with a
    TrimBox at the original size. stretch: the outer BLEED_IN of the page is
    mirrored outward (vector, nothing in the design moves). enlarge: the whole
    page is scaled up evenly until it covers the bleed, centred.
    """
    page = src[pno]
    w, h, b = page.rect.width, page.rect.height, BLEED_IN * PT
    new = out.new_page(width=w + 2 * b, height=h + 2 * b)
    trim = fitz.Rect(b, b, b + w, b + h)
    if how == "enlarge":
        f = max((w + 2 * b) / w, (h + 2 * b) / h)
        c = trim.tl + (w / 2, h / 2)
        new.show_pdf_page(fitz.Rect(c.x - w * f / 2, c.y - h * f / 2,
                                    c.x + w * f / 2, c.y + h * f / 2), src, pno)
    else:
        new.show_pdf_page(trim, src, pno)
        xref = new.get_contents()[0]
        draw = out.xref_stream(xref)
        # PDF space (origin bottom-left); the page is symmetric, so the trim
        # is x b..b+w, y b..b+h there too. Each strip and corner draws the
        # page again, mirrored across the trim edge it touches, clipped.
        W, H = w + 2 * b, h + 2 * b
        xs = [(0, b, -1, 2 * b), (b, b + w, 1, 0), (b + w, W, -1, 2 * (b + w))]
        ys = [(0, b, -1, 2 * b), (b, b + h, 1, 0), (b + h, H, -1, 2 * (b + h))]
        parts = []
        for x0, x1, sx, tx in xs:
            for y0, y1, sy, ty in ys:
                parts.append(b"q %g %g %g %g re W n %d 0 0 %d %g %g cm\n" % (
                    x0, y0, x1 - x0, y1 - y0, sx, sy, tx, ty) + draw + b"\nQ\n")
        out.update_stream(xref, b"".join(parts))
    new.set_trimbox(trim)


def with_bleed(src, s):
    """
    The document to impose from. With crop marks that add bleed, pages
    without bleed get it made (kept on src, so it's done once per mode);
    otherwise src itself.
    """
    if not s.adds_bleed or all(has_bleed(p) for p in src):
        return src
    cache = getattr(src, "_prestige_bleed", None)
    if cache is None:
        cache = {}
        try:
            src._prestige_bleed = cache
        except AttributeError:
            pass
    if s.crop_marks not in cache:
        out = fitz.open()
        for page in src:
            if has_bleed(page):
                out.insert_pdf(src, from_page=page.number, to_page=page.number)
            else:
                _bleed_page(out, src, page.number, s.crop_marks)
        cache[s.crop_marks] = fitz.open("pdf", out.tobytes())
    return cache[s.crop_marks]


# ---------------------------------------------------------------------- plan

def plan(src, s):
    """Work out the layout for an open fitz.Document. Draws nothing."""
    s = replace(s)
    errors, warnings = [], []
    if s.layout == "normal":   # one page per sheet
        s.rows = s.cols = 1
        s.gutter_x = s.gutter_y = 0.0
    made_bleed = s.adds_bleed and not all(has_bleed(p) for p in src)
    src = with_bleed(src, s)
    if s.adds_bleed:
        s.finish = "trim"   # slots are the cut size; the bleed sits in the gutters
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
    each = [(round(r.width / PT, 2), round(r.height / PT, 2)) for r in finishes]
    if len(set(each)) > 1:
        common = max(set(each), key=each.count)
        odd = [i + 1 for i, wh in enumerate(each) if wh != common]
        which = ", ".join(map(str, odd[:8])) + ("..." if len(odd) > 8 else "")
        warnings.append(f"Page{'s' if len(odd) > 1 else ''} {which} "
                        f"{'are' if len(odd) > 1 else 'is'}n't the size of the rest "
                        f'({common[0]:g}" x {common[1]:g}"). Each slot is sized for the '
                        "largest page and smaller ones are centred in it.")

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
    if s.rotate % 180:
        cw, ch = ch, cw
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
    # Same both sides: asked for, or duplex on a one-page file (a blank back
    # would just be single-sided).
    same = s.duplex and (s.back_same or n_pages == 1)
    if same:
        if not s.back_same:
            warnings.append("One-page file with duplex on: the same page prints on both "
                            "sides.")
        if s.layout == "gangup" and s.gang == "repeat":
            sides = [([(r, p) for r in slots], [(mirror(r), p) for r in slots])
                     for p in range(n_pages)]
        else:
            for start in range(0, n_pages, per):
                front = [(slots[j], p) for j, p in
                         enumerate(range(start, min(start + per, n_pages)))]
                sides.append((front, [(mirror(r), p) for r, p in front]))
    elif s.layout == "gangup" and s.gang == "repeat":
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

    pair = s.duplex and not same
    if s.layout == "gangup" and s.gang == "repeat" and n_pages > (2 if pair else 1):
        warnings.append(f"Repeat with a {n_pages}-page file makes {len(sides)} different "
                        "sheets, one per " + ("front/back pair." if pair else "page."))
    if s.layout != "gangup" or s.gang != "repeat":
        filled = sum(len(f) for f, _ in sides)
        empty = len(sides) * per - filled
        if empty:
            warnings.append(f"{empty} slot(s) on the last sheet are empty.")

    # Resolve each (slot, page) into what actually prints.
    s_eff = replace(s, gutter_x=gx / PT, gutter_y=gy / PT)
    mgrid = mirror(grid)

    row_pitch = ch + gy

    col_pitch = cw + gx
    turned_90 = bool(s.rotate % 180)

    def angle_for(slot, mirrored, surface):
        """mirrored: the slot is the mirror image of its front (gangup backs)."""
        a = s.rotate % 360
        if pairs_turn(s):
            front = mirror(slot) if mirrored else slot
            if turned_90:   # tops point sideways: pairs of columns
                n = round((front.x0 - x0) / col_pitch) if col_pitch else 0
            else:
                n = round((front.y0 - y0) / row_pitch) if row_pitch else 0
            # Upright, head to head turns rows 1, 3, 5 (counting from 1) so each
            # pair's tops meet; turned 90, tops point right, so it's columns 2, 4.
            turn_first = (s.layout_style == "head") != turned_90
            if (n % 2 == 0) == turn_first:
                a = (a + 180) % 360
        if s.slot_180 in (surface, "both"):
            a = (a + 180) % 360
        # Flipping the sheet left/right reverses a quarter turn, on every
        # back (a normal document's too, or its backs come out upside down).
        return (-a) % 360 if surface == "back" else a

    def resolve(entries, back=False, surface="front"):
        if entries is None:
            return None
        g = mgrid if back else grid
        out = []
        for slot, pno in entries:
            pl = _place(src, pno, slot, g, s_eff, scale, safe, angle_for(slot, back, surface))
            if pl:
                out.append(pl)
        return out

    resolved = [(resolve(f), resolve(b, back=same or s.layout != "normal", surface="back"))
                for f, b in sides]

    # The size each piece really ends up after cutting: its cut line, unless
    # neighbours were pulled in past it (then the spacing decides).
    finished = (0.0, 0.0)
    if resolved and resolved[0][0]:
        c0 = resolved[0][0][0].cut
        fw_cut = min(c0.width, cw + gx) if s.cols > 1 else c0.width
        fh_cut = min(c0.height, ch + gy) if s.rows > 1 else c0.height
        finished = (fw_cut, fh_cut)

    if s.adds_bleed:
        if made_bleed:
            how = ("mirroring the outer edge outward" if s.crop_marks == "stretch" else
                   "enlarging the artwork, so a little of its edge is cut off")
            warnings.append(f'This file has no bleed, so {BLEED_IN}" was made by {how}. '
                            "Pieces still cut to the file's size.")
        need = 2 * BLEED_IN - 0.001
        if (s.cols > 1 and s.gutter_x < need) or (s.rows > 1 and s.gutter_y < need):
            warnings.append(f'Crop marks with bleed: gutters under {2 * BLEED_IN}" cut the '
                            f'bleed short where pieces meet. Fit most sets them to '
                            f'{2 * BLEED_IN}".')

    # Bigger than the sheet is allowed (sometimes on purpose); just say so.
    # What has to print is the cuts, crop marks and bleed (see outer_spare);
    # slug beyond a file's own marks may fall in the margin.
    spx, spy = outer_spare(src, s)
    if s.marks or keeps_own_marks(src):
        needed = grid + (spx / 2, spy / 2, -spx / 2, -spy / 2)
        if not (safe + (-0.01, -0.01, 0.01, 0.01)).contains(needed):
            warnings.append(
                f'The layout needs {needed.width / PT:.3f}" x {needed.height / PT:.3f}" '
                f'with its crop marks, more than fits inside the {SHEET_MARGIN_IN}" margin of '
                f'the {sheet_w / PT:g}" x {sheet_h / PT:g}" sheet. Whatever falls past the '
                'margin is left blank.')
    elif not sheet_rect.contains(grid):
        warnings.append(
            f'The layout is {grid_w / PT:.3f}" x {grid_h / PT:.3f}", bigger than the '
            f'{sheet_w / PT:g}" x {sheet_h / PT:g}" sheet. Whatever falls past the '
            f'{SHEET_MARGIN_IN}" margin is left blank.')

    return Plan(settings=s, sheet=(sheet_w, sheet_h), finish=(fw, fh), scale=scale,
                cell=(cw, ch), grid=grid, slots=slots, sides=resolved,
                finished=finished, source=src, errors=errors, warnings=warnings)


# -------------------------------------------------------------------- render

def render(src, plan_, sheets=None):
    """
    Build the imposed PDF as a new fitz.Document. `sheets` limits it to some
    sheet indexes (the preview only needs one).
    """
    out = fitz.open()
    src = plan_.source or src
    sw, sh = plan_.sheet
    indexes = range(plan_.sheet_count) if sheets is None else sheets
    for i in indexes:
        for entries in plan_.sides[i]:
            if entries is None:
                continue
            page = out.new_page(width=sw, height=sh)
            for pl in entries:
                # show_pdf_page turns counter-clockwise; our angles are clockwise.
                page.show_pdf_page(pl.visible, src, pl.pno, clip=pl.clip,
                                   rotate=(-pl.angle) % 360, keep_proportion=False)
            lines = sheet_marks(plan_, entries)
            if lines:
                shape = page.new_shape()
                for a, b in lines:
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


def pairs_turn(s):
    """Head to head / foot to foot only mean something with at least two rows
    (or two columns, when the pieces are turned 90)."""
    if s.layout_style not in ("head", "foot"):
        return False
    return (s.cols if s.rotate % 180 else s.rows) >= 2


def describe(plan_, n_pages):
    """One-paragraph summary for the screen and the command line."""
    s = plan_.settings
    fw, fh = (v / PT for v in plan_.finish)
    sw, sh = (v / PT for v in plan_.sheet)
    mode = "Normal" if s.layout == "normal" else f"Gangup, {s.gang}"
    dup = ("duplex, same both sides" if s.duplex and (s.back_same or n_pages == 1)
           else "duplex" if s.duplex else "single-sided")
    turned = []
    if s.rotate % 360:
        turned.append("pieces turned 90\u00b0")
    if pairs_turn(s):
        turned.append("head to head" if s.layout_style == "head" else "foot to foot")
    if s.slot_180 != "none":
        turned.append({"front": "front", "back": "back", "both": "front and back"}[s.slot_180]
                      + " turned 180\u00b0")
    turned = f" ({', '.join(turned)})" if turned else ""
    pw, ph = (v / PT for v in plan_.finished)
    finished = f' Pieces finish at {pw:.3f}" x {ph:.3f}".' if pw and ph else ""
    layout = ("one page per sheet" if s.layout == "normal"
              else f"{s.rows} x {s.cols} = {plan_.per_sheet} up")
    return (f'{n_pages} page(s), {fw:.3f}" x {fh:.3f}" each. {mode}, {layout} '
            f'on {sw:g}" x {sh:g}" {s.orientation}{turned}, {dup}. '
            f"{plan_.sheet_count} sheet(s) to print.{finished}")


# ------------------------------------------------------------------- preview

PREVIEW_CACHE_MAX_PX = 8_000_000   # a page bigger than this at preview zoom isn't cached

def render_preview(src, plan_, sheet_index, zoom, cache, views=None):
    """
    Fast on-screen picture of one sheet (front, and back if duplex), as
    Pixmaps. Same layout as render(), but the saved PDF always comes from
    render(), never from this.

    `zoom` is screen pixels per point. `views` (one IRect per side, in that
    side's pixels) limits drawing to what's on screen, so a zoomed-in preview
    costs no more than a fitted one; a side with nothing visible comes back
    as None. Each source page is drawn once at this zoom and kept in `cache`
    (a dict the caller owns and clears), unless that would be huge (a flyer
    zoomed right in): then only its visible part is drawn, each time.
    """
    src = plan_.source or src
    sw, sh = plan_.sheet
    k = plan_.scale
    zk = zoom * k
    full = fitz.IRect(0, 0, round(sw * zoom), round(sh * zoom))
    out = []
    sides = [e for e in plan_.sides[sheet_index] if e is not None]
    for i, entries in enumerate(sides):
        view = full if views is None else fitz.IRect(views[i]) & full
        if view.is_empty:
            out.append(None)
            continue
        sheet = fitz.Pixmap(fitz.csRGB, view, False)   # origin = view's top-left
        sheet.clear_with(255)
        for pl in entries:
            target = fitz.IRect(round(pl.visible.x0 * zoom), round(pl.visible.y0 * zoom),
                                round(pl.visible.x1 * zoom), round(pl.visible.y1 * zoom)) & view
            if target.is_empty:
                continue
            page = src[pl.pno]
            pr = page.rect
            # Page -> sheet for this placement (same mapping _place used):
            # the visible area came from `clip`, turned by `angle`.
            m = (fitz.Matrix(1, 0, 0, 1, -pl.clip.x0, -pl.clip.y0) * fitz.Matrix(k, k)
                 * fitz.Matrix(pl.angle))
            turned_clip = fitz.Rect(pl.clip) * m
            m = m * fitz.Matrix(1, 0, 0, 1, pl.visible.x0 - turned_clip.x0,
                                pl.visible.y0 - turned_clip.y0)
            on_sheet = fitz.Rect(pr) * m                   # whole page on the sheet
            on_sheet.normalize()
            mz = fitz.Matrix(zk, zk).prerotate(pl.angle)   # page -> pixmap space
            bbox = (fitz.Rect(pr) * mz).irect
            off_x, off_y = round(on_sheet.x0 * zoom), round(on_sheet.y0 * zoom)
            if pr.width * zk * pr.height * zk <= PREVIEW_CACHE_MAX_PX:
                key = (id(src), pl.pno, round(zk, 5), pl.angle)
                pix = cache.get(key)
                if pix is None:
                    pix = page.get_pixmap(matrix=mz, alpha=False)
                    cache[key] = pix
                # A cached picture is reused across slots: place it from
                # scratch each time (its own top-left is the page's top-left).
                pix.set_origin(off_x, off_y)
            else:
                part = fitz.Rect(target.x0 / zoom, target.y0 / zoom,
                                 target.x1 / zoom, target.y1 / zoom) * ~m
                part.normalize()
                part = (part + (-1, -1, 1, 1)) & pr
                pix = page.get_pixmap(matrix=mz, clip=part, alpha=False)
                pix.set_origin(off_x + pix.x - bbox.x0, off_y + pix.y - bbox.y0)
            sheet.copy(pix, target)
        # Crop marks: the same lines as the saved PDF, at least a pixel wide.
        w = max(1, round(MARK_WIDTH_PT * zoom))
        for a, b in sheet_marks(plan_, entries):
            x0, y0 = min(a.x, b.x) * zoom, min(a.y, b.y) * zoom
            x1, y1 = max(a.x, b.x) * zoom, max(a.y, b.y) * zoom
            if x1 - x0 < y1 - y0:   # vertical
                x0 = round(x0 - w / 2)
                box = fitz.IRect(x0, round(y0), x0 + w, round(y1))
            else:
                y0 = round(y0 - w / 2)
                box = fitz.IRect(round(x0), y0, round(x1), y0 + w)
            box &= view
            if not box.is_empty:
                sheet.set_rect(box, (0, 0, 0))
        out.append(sheet)
    return out
