"""
Engine tests. Run before every release build (pytest). Only generated PDFs:
no client artwork in this repository, ever.
"""

import hashlib

import pymupdf as fitz
import pytest

from prestige_impose import engine
from prestige_impose.engine import PT, Settings, describe, plan, render, render_preview


def make_pdf(n_pages=2, w_in=3.5, h_in=2.0, bleed_in=0.0, image=False):
    """A test card file. With bleed, the page is bigger and a TrimBox marks the card."""
    doc = fitz.open()
    b = bleed_in * PT
    for i in range(n_pages):
        page = doc.new_page(width=w_in * PT + 2 * b, height=h_in * PT + 2 * b)
        page.draw_rect(page.rect, fill=(0.2, 0.2, 0.2), color=None)  # ink to the edge
        page.insert_text((b + 20, b + 60), f"p{i + 1}", fontsize=30, color=(1, 1, 1))
        if image:
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 30), False)
            pix.clear_with(90 + i)
            page.insert_image(fitz.Rect(b + 150, b + 20, b + 230, b + 70), pixmap=pix)
        if b:
            page.set_trimbox(fitz.Rect(b, b, b + w_in * PT, b + h_in * PT))
    return fitz.open(stream=doc.tobytes(), filetype="pdf")


def words(page):
    """[(x, y, text)] of the page labels, rounded, reading order."""
    return sorted((round(w[0]), round(w[1]), w[4]) for w in page.get_text("words")
                  if w[4].startswith("p"))


LETTER_2x2 = dict(sheet_w=8.5, sheet_h=11, rows=2, cols=2)


def test_repeat_duplex_one_sheet_per_pair():
    src = make_pdf(2)
    p = plan(src, Settings(duplex=True, rows=7, cols=3))
    assert p.sheet_count == 1 and not p.errors
    out = render(src, p)
    assert len(out) == 2
    assert {t for _, _, t in words(out[0])} == {"p1"} and len(words(out[0])) == 21
    assert {t for _, _, t in words(out[1])} == {"p2"} and len(words(out[1])) == 21


def test_unique_duplex_back_sits_behind_front():
    src = make_pdf(8)
    out = render(src, plan(src, Settings(layout="gangup", gang="unique", duplex=True, **LETTER_2x2)))
    front, back = words(out[0]), words(out[1])
    # Card 1 (p1) top-left on the front -> its back (p2) top-right on the back.
    p1 = next(w for w in front if w[2] == "p1")
    p2 = next(w for w in back if w[2] == "p2")
    assert abs(p1[1] - p2[1]) < 2            # same row
    assert p2[0] > out[1].rect.width / 2     # mirrored to the right half


def test_normal_is_one_page_per_sheet_in_order():
    src = make_pdf(8)
    # Rows, columns and gutters left over from a gangup layout don't apply.
    p = plan(src, Settings(layout="normal", duplex=True, gutter_x=-0.5, **LETTER_2x2))
    assert p.per_sheet == 1 and p.sheet_count == 4 and not p.errors
    out = render(src, p)
    assert [[w[2] for w in words(pg)] for pg in out[:4]] == [["p1"], ["p2"], ["p3"], ["p4"]]
    assert "one page per sheet" in describe(p, 8)


def test_normal_turned_90_backs_line_up_with_fronts():
    """Bug A: a turned document's backs came out upside down."""
    front, back = plan(make_pdf(2), Settings(layout="normal", duplex=True, rotate=90)).sides[0]
    assert [pl.angle for pl in front] == [90] and [pl.angle for pl in back] == [270]


def test_head_to_head_needs_two_rows():
    """Bug B: with one row there's nothing to pair, so nothing turns."""
    front, _ = plan(make_pdf(1), Settings(rows=1, cols=3, layout_style="head")).sides[0]
    assert {pl.angle for pl in front} == {0}
    front, _ = plan(make_pdf(1), Settings(rows=3, cols=1, rotate=90,
                                          layout_style="foot")).sides[0]
    assert {pl.angle for pl in front} == {90}


def test_negative_gutter_trims_overlap_no_bleed_file():
    src = make_pdf(2)
    p = plan(src, Settings(gutter_x=-0.25, gutter_y=0.25, **LETTER_2x2))
    widths = [round(pl.visible.width / PT, 3) for pl in p.sides[0][0]]
    assert widths == [3.375] * 4   # each piece loses half the overlap, none overlaps


def test_negative_gutter_closes_illustrator_bleed():
    # Illustrator-style page: 3.5 x 2 card inside a 4.083 x 2.583 page.
    src = make_pdf(2, bleed_in=0.29167)
    p = plan(src, Settings(rows=7, cols=3, gutter_x=-0.58333, gutter_y=-0.58333))
    cuts = render(src, p)[0].trimbox
    assert round(cuts.width / PT, 2) == 10.5 and round(cuts.height / PT, 2) == 14.0
    # Neighbouring visible areas never overlap.
    vis = [pl.visible for pl in p.sides[0][0]]
    for i, a in enumerate(vis):
        for b in vis[i + 1:]:
            inter = a & b
            assert inter.is_empty or inter.width < 0.01 or inter.height < 0.01


def test_margin_is_blank_and_oversize_still_saves():
    src = make_pdf(2, bleed_in=0.29167)
    p = plan(src, Settings(duplex=True, rows=7, cols=3, gutter_x=-0.1, gutter_y=-0.21))
    assert not p.errors                       # bigger than the sheet is allowed...
    assert any("bigger than" in w for w in p.warnings)  # ...with a heads-up
    for page in render(src, p):
        pix = page.get_pixmap(dpi=100, colorspace=fitz.csGRAY)
        w, h, s = pix.width, pix.height, pix.samples
        edge = 9  # just inside 0.1" at 100 dpi
        strip = [s[y * w + x] for y in range(h) for x in list(range(edge)) + list(range(w - edge, w))]
        assert min(strip) >= 250, "ink inside the 0.1 inch margin"


def test_image_pixels_unchanged():
    src = make_pdf(2, image=True)
    out = fitz.open(stream=render(src, plan(src, Settings(rows=4, cols=2))).tobytes(
        garbage=4, deflate=True), filetype="pdf")

    def images(doc):
        return {hashlib.md5(doc.xref_stream(x)).hexdigest() for x in range(1, doc.xref_length())
                if doc.xref_get_key(x, "Subtype")[1] == "/Image"}
    assert images(src) and images(src) == images(out)


def test_preview_matches_layout_size():
    src = make_pdf(2)
    p = plan(src, Settings(duplex=True, rows=7, cols=3))
    pix = render_preview(src, p, 0, 0.5, {})
    assert len(pix) == 2 and pix[0].width == round(12 * PT * 0.5)


def test_bad_input_is_an_error_not_a_crash():
    src = make_pdf(1)
    assert plan(src, Settings(rows=0)).errors
    assert plan(src, Settings(rows=2, cols=2, gutter_x=-10, gutter_y=-10)).errors


def test_presets_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "PRESETS_FILE", tmp_path / "p.json")
    engine.save_preset("Cards", Settings(rows=7, cols=3, gutter_x=-0.6, gutter_y=-0.6, duplex=True))
    got = engine.load_presets()["Cards"]
    assert (got.rows, got.cols, got.gutter_x, got.duplex) == (7, 3, -0.6, True)
    engine.delete_preset("Cards")
    assert engine.load_presets() == {}


def test_shipped_presets_load():
    presets = engine.load_presets()
    assert presets, "presets/shared_presets.json is missing or empty"
    for name, s in presets.items():
        assert s.rows >= 1 and s.cols >= 1, name


@pytest.mark.parametrize("tag,newer", [("v1.0.1", True), ("v1.0.0", False), ("v0.9.9", False), ("v1.10.0", True)])
def test_version_compare(tag, newer):
    from prestige_impose import updater
    assert (updater._parse(tag) > updater._parse("1.0.0")) is newer


def test_preview_view_matches_full_render():
    """Drawing only the on-screen part gives the same pixels as drawing it all."""
    src = make_pdf(2, bleed_in=0.29167, image=True)
    p = plan(src, Settings(duplex=True, rows=7, cols=3, gutter_x=-0.6, gutter_y=-0.6))
    z = 1.5
    full = render_preview(src, p, 0, z, {})
    view = fitz.IRect(300, 400, 700, 900)
    part = render_preview(src, p, 0, z, {}, [view, view])
    for f, q in zip(full, part):
        assert (q.x, q.y, q.width, q.height) == (300, 400, 400, 500)
        crop = fitz.Pixmap(fitz.csRGB, view, False)
        crop.copy(f, view)
        assert crop.samples == q.samples


def test_preview_big_page_zoomed_in_draws_only_visible(monkeypatch):
    """A flyer at high zoom isn't cached whole; the visible part still matches."""
    src = make_pdf(1, w_in=8.5, h_in=11, image=True)
    p = plan(src, Settings(rows=1, cols=1))
    z = 6.0  # ~600% on a typical screen
    cache = {}
    view = fitz.IRect(1000, 1500, 1800, 2100)
    part = render_preview(src, p, 0, z, cache, [view])[0]
    assert not cache  # too big to cache whole
    monkeypatch.setattr(engine, "PREVIEW_CACHE_MAX_PX", 10 ** 12)
    whole = render_preview(src, p, 0, z, {}, [view])[0]
    diff = sum(abs(a - b) for a, b in zip(part.samples, whole.samples)) / len(part.samples)
    assert diff < 2  # same picture (edge anti-aliasing aside)


# ---------------------------------------------------------------- 1.2 features

def page_pixels(page, zoom):
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)


@pytest.mark.parametrize("rotate,style,s180", [(0, "standard", "none"), (90, "standard", "none"),
                                               (0, "head", "back"), (90, "foot", "both")])
def test_preview_matches_saved_pdf_turned(rotate, style, s180):
    """The on-screen preview and the saved PDF agree, for every turn and both sides."""
    src = make_pdf(2, bleed_in=0.125, image=True)
    p = plan(src, Settings(duplex=True, rows=4, cols=3, finish="trim", rotate=rotate,
                           layout_style=style, slot_180=s180))
    assert not p.errors
    z = 0.5
    saved = render(src, p)
    for prev, page in zip(render_preview(src, p, 0, z, {}), saved):
        real = page_pixels(page, z)
        assert (prev.width, prev.height) == (real.width, real.height)
        diff = sum(abs(a - b) for a, b in zip(prev.samples, real.samples)) / len(real.samples)
        assert diff < 3, f"preview differs from saved PDF by {diff:.1f}"


def test_rotate_90_turns_the_slots():
    src = make_pdf(1)
    p = plan(src, Settings(rows=1, cols=1, rotate=90))
    pl = p.sides[0][0][0]
    assert round(pl.visible.width / PT, 2) == 2.0 and round(pl.visible.height / PT, 2) == 3.5
    assert pl.angle == 90


def angles_by_row(entries):
    rows = sorted({round(pl.visible.y0) for pl in entries})
    by = {round(pl.visible.y0): pl.angle for pl in entries}
    return [by[r] for r in rows]


def test_head_to_head_and_foot_to_foot_and_backs_follow():
    src = make_pdf(2)
    # Head to head: row 1 upside down, row 2 upright, so their tops meet.
    front, back = plan(src, Settings(duplex=True, rows=4, cols=2, layout_style="head")).sides[0]
    assert angles_by_row(front) == [180, 0, 180, 0]
    assert angles_by_row(back) == angles_by_row(front)
    # Foot to foot: row 2 upside down, so the bottoms of rows 1 and 2 meet.
    front, _ = plan(src, Settings(duplex=True, rows=4, cols=2, layout_style="foot")).sides[0]
    assert angles_by_row(front) == [0, 180, 0, 180]


def test_head_to_head_turned_90_pairs_columns():
    src = make_pdf(1)
    front, _ = plan(src, Settings(rows=1, cols=4, rotate=90, layout_style="head")).sides[0]
    by_col = [pl.angle for pl in sorted(front, key=lambda pl: pl.visible.x0)]
    assert by_col == [90, 270, 90, 270]   # tops of columns 1 and 2 meet in the middle


def test_old_head_to_head_preset_keeps_its_look():
    assert Settings.from_dict({"head_to_head": True}).layout_style == "foot"
    assert Settings.from_dict({"head_to_head": False}).layout_style == "standard"


@pytest.mark.parametrize("surface,front_turned,back_turned",
                         [("none", False, False), ("front", True, False),
                          ("back", False, True), ("both", True, True)])
def test_180_slot_rotation(surface, front_turned, back_turned):
    src = make_pdf(2)
    front, back = plan(src, Settings(duplex=True, rows=2, cols=2, slot_180=surface)).sides[0]
    assert {pl.angle for pl in front} == {180 if front_turned else 0}
    assert {pl.angle for pl in back} == {180 if back_turned else 0}
    # Normal layout too (its backs aren't mirrored).
    _, back = plan(make_pdf(8), Settings(layout="normal", duplex=True, slot_180=surface,
                                         **LETTER_2x2)).sides[0]
    assert {pl.angle for pl in back} == {180 if back_turned else 0}


def test_turned_backs_turn_the_other_way():
    src = make_pdf(2)
    front, back = plan(src, Settings(duplex=True, rows=2, cols=2, rotate=90)).sides[0]
    assert {pl.angle for pl in front} == {90} and {pl.angle for pl in back} == {270}


def make_marked_pdf(slug_in=0.2917, w_in=3.5, h_in=2.0, art_lines=True):
    """Illustrator-style: no TrimBox, crop marks running in from the page edge."""
    doc = fitz.open()
    b = slug_in * PT
    page = doc.new_page(width=w_in * PT + 2 * b, height=h_in * PT + 2 * b)
    t = fitz.Rect(b, b, b + w_in * PT, b + h_in * PT)
    r = page.rect
    mark = b - 0.083 * PT
    for x in (t.x0, t.x1):
        page.draw_line((x, 0), (x, mark))
        page.draw_line((x, r.y1), (x, r.y1 - mark))
    for y in (t.y0, t.y1):
        page.draw_line((0, y), (mark, y))
        page.draw_line((r.x1, y), (r.x1 - mark, y))
    if art_lines:  # short lines in the design that must not be taken for marks
        page.draw_line((t.x0 + 30, t.y0 + 20), (t.x0 + 30, t.y0 + 40))
        page.draw_line((t.x0 + 50, r.y1 - 1), (t.x0 + 50, r.y1 - 20))  # only at the bottom
    return fitz.open(stream=doc.tobytes(), filetype="pdf")


def test_finds_cut_line_from_crop_marks():
    src = make_marked_pdf()
    t = engine.trim_rect(src[0])
    assert [round(v / PT, 3) for v in t] == [0.292, 0.292, 3.792, 2.292]


def test_no_marks_means_no_cut_line():
    src = make_pdf(1)
    assert not engine.has_bleed(src[0])
    assert engine.pull_in_gutters(src, Settings()) is None


def test_pull_in_keeps_crop_marks_showing():
    # Illustrator card: 0.4583" slug, marks start 0.083" out. Leo's preset is -0.63.
    ill = make_marked_pdf(slug_in=0.4583)
    assert engine.own_mark_gaps(ill[0]) == pytest.approx([0.083 * PT] * 4, abs=0.05)
    assert engine.pull_in_gutters(ill, Settings()) == pytest.approx((-0.63, -0.63), abs=2e-3)
    # InDesign-style card, 0.2917" slug: less to pull in.
    ind = make_marked_pdf()
    assert engine.pull_in_gutters(ind, Settings()) == pytest.approx((-0.2974, -0.2974), abs=2e-3)
    # No marks of its own (TrimBox and bleed only): the cut lines meet.
    src2 = make_pdf(1, bleed_in=0.125)
    assert engine.pull_in_gutters(src2, Settings()) == (-0.25, -0.25)
    assert engine.pull_in_gutters(src2, Settings(finish="trim")) == (0.0, 0.0)


def test_best_fit_matches_the_shops_7x3():
    # 12x18 business cards: the shop knows 7 x 3 is what fits with marks showing.
    for slug in (0.4583, 0.2917):
        rows, cols, rot, gx, gy = engine.best_fit(make_marked_pdf(slug_in=slug), Settings())
        assert (rows, cols, rot) == (7, 3, 0), slug
        p = plan(make_marked_pdf(slug_in=slug),
                 Settings(rows=rows, cols=cols, gutter_x=gx, gutter_y=gy))
        assert [round(v / PT, 2) for v in p.finished] == [3.5, 2.0]
        assert not any("bigger than" in w for w in p.warnings)
        # Turning on the app's own crop marks doesn't cost a column: they shorten to fit.
        with_marks = engine.best_fit(make_marked_pdf(slug_in=slug), Settings(crop_marks="outside"))
        assert with_marks[:3] == (7, 3, 0), slug
    # A card with no bleed can turn: 5 x 5 turned beats 8 x 3 upright.
    assert engine.best_fit(make_pdf(1), Settings())[:3] == (5, 5, 90)


def test_finished_size_shows_over_pulling():
    src = make_marked_pdf()
    exact = plan(src, Settings(rows=7, cols=3, gutter_x=-0.5833, gutter_y=-0.5833))
    assert [round(v / PT, 2) for v in exact.finished] == [3.5, 2.0]
    tight = plan(src, Settings(rows=7, cols=3, gutter_x=-0.63, gutter_y=-0.63))
    assert [round(v / PT, 3) for v in tight.finished] == [3.453, 1.953]
    assert "Pieces finish at 3.453" in describe(tight, 1)


def test_crop_marks_with_bleed_keep_an_eighth_around_each_piece():
    src = make_pdf(1, bleed_in=0.25)             # 3.5 x 2 card with 0.25" of bleed
    for mode in ("stretch", "enlarge"):          # the file has bleed: both just use it
        p = plan(src, Settings(rows=2, cols=2, gutter_x=0.25, gutter_y=0.25, crop_marks=mode))
        assert not p.warnings and p.source is src
        for pl in p.sides[0][0]:
            assert (round(pl.cut.width / PT, 3), round(pl.cut.height / PT, 3)) == (3.5, 2.0)
            assert (round(pl.visible.width / PT, 3), round(pl.visible.height / PT, 3)) ==                 (3.75, 2.25)
        # Cut to cut is the gutter: the slots are the cut size, not the page.
        xs = sorted({round(pl.cut.x0 / PT, 3) for pl in p.sides[0][0]})
        assert round(xs[1] - xs[0], 3) == 3.75


def bleed_is_inked(page, pl):
    """Sample the bleed just outside the cut, on all four sides, on the saved sheet."""
    c, d = pl.cut, 0.06 * PT
    for x, y in ((c.x0 - d, (c.y0 + c.y1) / 2), (c.x1 + d, (c.y0 + c.y1) / 2),
                 ((c.x0 + c.x1) / 2, c.y0 - d), ((c.x0 + c.x1) / 2, c.y1 + d),
                 (c.x0 - d, c.y0 - d)):
        pix = page.get_pixmap(clip=fitz.Rect(x - 1, y - 1, x + 1, y + 1), dpi=72,
                              colorspace=fitz.csGRAY, alpha=False)
        if max(pix.samples) > 120:
            return False
    return True


@pytest.mark.parametrize("mode", ["stretch", "enlarge"])
def test_bleed_made_for_a_file_without_any(mode):
    src = make_pdf(1)                            # 3.5 x 2, dark to the edge, no bleed
    p = plan(src, Settings(rows=2, cols=2, gutter_x=0.25, gutter_y=0.25, crop_marks=mode))
    assert any("has no bleed" in w for w in p.warnings)
    pl = p.sides[0][0][0]
    assert (round(pl.cut.width / PT, 3), round(pl.cut.height / PT, 3)) == (3.5, 2.0)
    assert (round(pl.visible.width / PT, 3), round(pl.visible.height / PT, 3)) == (3.75, 2.25)
    out = render(src, p)
    assert bleed_is_inked(out[0], pl)
    assert out[0].get_drawings()                 # crop marks
    # The label "p1" sits 20pt in from the edge: stretch leaves it there, enlarge moves it.
    x = min(w[0] for w in out[0].get_text("words") if w[4] == "p1") - pl.cut.x0
    if mode == "stretch":
        assert abs(x - 20) < 1
    else:
        assert x < 19


def test_crop_marks_with_bleed_warns_on_tight_gutters():
    tight = plan(make_pdf(1, bleed_in=0.25), Settings(rows=2, cols=2, crop_marks="stretch"))
    assert any("cut the bleed short" in w for w in tight.warnings)


def test_old_crop_mark_choices():
    assert Settings.from_dict({"crop_marks": "between"}).crop_marks == "outside"


def test_crop_marks_drawn_only_when_asked():
    src = make_pdf(1)
    for mode, expect in (("none", 0), ("outside", 1), ("stretch", 1), ("enlarge", 1)):
        out = render(src, plan(src, Settings(rows=2, cols=2, gutter_x=0.25, gutter_y=0.25,
                                             crop_marks=mode)))
        n = sum(1 for d in out[0].get_drawings() for it in d["items"] if it[0] == "l")
        assert (n > 0) == bool(expect), mode


def test_presets_remember_file_size(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "PRESETS_FILE", tmp_path / "p.json")
    engine.save_preset("Cards", Settings(rows=7, cols=3), match_size=(4.0833, 2.5833))
    assert engine.presets_for_size(4.0833, 2.5833) == ["Cards"]
    assert engine.presets_for_size(2.5833, 4.0833) == ["Cards"]   # either way round
    assert engine.presets_for_size(3.5, 2.0) == []
    engine.save_preset("Cards", Settings(rows=8, cols=3))          # re-save keeps the size
    assert engine.presets_for_size(4.0833, 2.5833) == ["Cards"]


def test_preset_suggested_for_any_card_that_pulls_in_the_same(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "PRESETS_FILE", tmp_path / "p.json")
    engine.save_preset("Illustrator", Settings(rows=7, cols=3, gutter_x=-0.63, gutter_y=-0.63),
                       match_size=(4.4167, 2.9167), match_cut=(3.5, 2.0))
    assert engine.presets_for_file(make_marked_pdf(slug_in=0.4583)) == ["Illustrator"]
    # Same marks, a slightly different page (e.g. re-exported): still offered.
    assert engine.presets_for_file(make_marked_pdf(slug_in=0.46)) == ["Illustrator"]
    # InDesign-style card, same cut: -0.63 would hide its marks, so not offered.
    assert engine.presets_for_file(make_marked_pdf(slug_in=0.2917)) == []
    assert engine.presets_for_file(make_pdf(1)) == []


def test_pull_in_preset_fits_each_card(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "PRESETS_FILE", tmp_path / "p.json")
    s = Settings(rows=7, cols=3, duplex=True, gutter_x=-0.63, gutter_y=-0.63, pull_in=True)
    engine.save_preset("Cards", s, match_size=(4.4167, 2.9167), match_cut=(3.5, 2.0))
    narrow = make_marked_pdf(slug_in=0.2917)         # e.g. a 4.083 x 2.583 card
    assert engine.presets_for_file(narrow) == ["Cards"]
    got = engine.settings_for_file(narrow, engine.load_presets()["Cards"])
    assert (got.gutter_x, got.gutter_y) == pytest.approx((-0.2974, -0.2974), abs=2e-3)
    p = plan(narrow, got)
    assert [round(v / PT, 2) for v in p.finished] == [3.5, 2.0] and p.per_sheet == 21
    wide = make_marked_pdf(slug_in=0.4583)
    got = engine.settings_for_file(wide, engine.load_presets()["Cards"])
    assert (got.gutter_x, got.gutter_y) == pytest.approx((-0.63, -0.63), abs=2e-3)


def test_crop_marks_show_in_preview_and_stay_on_the_sheet():
    # Leo's preset on an Illustrator card fills the sheet nearly edge to edge.
    src = make_marked_pdf(slug_in=0.4583, art_lines=False)
    p = plan(src, Settings(rows=7, cols=3, gutter_x=-0.63, gutter_y=-0.63, crop_marks="outside"))
    lines = engine.sheet_marks(p, p.sides[0][0])
    assert len(lines) == 2 * 6 + 2 * 14       # 6 vertical cuts, 14 horizontal
    m = engine.SHEET_MARGIN_IN * PT
    safe = fitz.Rect(m, m, p.sheet[0] - m, p.sheet[1] - m) + (-0.01, -0.01, 0.01, 0.01)
    assert all(safe.contains(a) and safe.contains(b) for a, b in lines)
    # The preview draws them: the pixel under a mark is black.
    zoom = 1.0
    pix = render_preview(src, p, 0, zoom, {})[0]
    a, b = lines[0]
    x, y = round((a.x + b.x) / 2 * zoom), round((a.y + b.y) / 2 * zoom)
    assert pix.pixel(x, y) == (0, 0, 0)
    off = render_preview(src, plan(src, Settings(rows=7, cols=3, gutter_x=-0.63,
                                                 gutter_y=-0.63)), 0, zoom, {})[0]
    assert off.pixel(x, y) != (0, 0, 0)


def test_one_page_duplex_prints_same_both_sides():
    src = make_pdf(1)
    p = plan(src, Settings(duplex=True, rows=7, cols=3))
    assert p.sheet_count == 1 and not p.errors
    assert any("same page prints on both sides" in w for w in p.warnings)
    out = render(src, p)
    assert len(out) == 2
    assert {t for _, _, t in words(out[1])} == {"p1"} and len(words(out[1])) == 21
    assert "same both sides" in describe(p, 1)


def test_same_both_sides_unique_backs_behind_fronts():
    src = make_pdf(3)
    p = plan(src, Settings(layout="gangup", gang="unique", duplex=True, back_same=True,
                           **LETTER_2x2))
    assert not any("odd" in w for w in p.warnings)
    out = render(src, p)
    assert len(out) == 2
    front, back = words(out[0]), words(out[1])
    assert sorted(t for *_, t in front) == sorted(t for *_, t in back) == ["p1", "p2", "p3"]
    p1f = next(w for w in front if w[2] == "p1")
    p1b = next(w for w in back if w[2] == "p1")
    assert abs(p1f[1] - p1b[1]) < 2 and p1b[0] > out[1].rect.width / 2   # mirrored


def test_same_both_sides_repeat_multi_page():
    src = make_pdf(2)
    p = plan(src, Settings(duplex=True, back_same=True, rows=7, cols=3))
    assert p.sheet_count == 2
    out = render(src, p)
    assert [{t for *_, t in words(pg)} for pg in out] == [{"p1"}, {"p1"}, {"p2"}, {"p2"}]
