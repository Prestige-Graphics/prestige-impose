"""
Engine tests. Run before every release build (pytest). Only generated PDFs:
no client artwork in this repository, ever.
"""

import hashlib

import pymupdf as fitz
import pytest

from prestige_impose import engine
from prestige_impose.engine import PT, Settings, plan, render, render_preview


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


def test_normal_duplex_reading_order():
    src = make_pdf(8)
    out = render(src, plan(src, Settings(layout="normal", duplex=True, **LETTER_2x2)))
    assert [w[2] for w in sorted(words(out[0]), key=lambda w: (w[1], w[0]))] == ["p1", "p2", "p3", "p4"]
    assert [w[2] for w in sorted(words(out[1]), key=lambda w: (w[1], w[0]))] == ["p5", "p6", "p7", "p8"]


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
