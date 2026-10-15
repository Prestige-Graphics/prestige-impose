"""The drawing helper process: same pictures as drawing in the window, never blocks."""

import time

import pymupdf as fitz

from prestige_impose.engine import Settings, plan, render_preview
from prestige_impose.renderer import Renderer
from tests.test_engine import make_pdf


def wait_for(r, channel, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        r.poll()
        if not r.busy():
            return True
        time.sleep(0.02)
    return False


def test_helper_draws_the_same_preview_as_the_window():
    r = Renderer()
    assert r.ok
    try:
        src = make_pdf(2)
        for s in (Settings(rows=2, cols=3, duplex=True), Settings(rows=2, cols=2, rotate=90)):
            p = plan(src, s)
            for zoom in (0.4, 3.0):   # 3.0: pages too big to keep whole, drawn in parts
                views = None if zoom < 1 else [fitz.IRect(400, 1300, 1500, 2100)] * 2
                direct = render_preview(src, p, 0, zoom, {}, views)

                def raster(doc, pno, zk, angle, clip, ch="preview"):
                    return r.get(ch, doc, pno, zk, angle, clip)[0]
                r.new_round("preview")
                first = render_preview(src, p, 0, zoom, {}, views, raster=raster)
                assert wait_for(r, "preview")
                r.new_round("preview")
                done = render_preview(src, p, 0, zoom, {}, views, raster=raster)
                assert [d.samples for d in direct] == [d.samples for d in done]
                assert len(first) == len(direct)
    finally:
        r.stop()


def test_stand_in_until_drawn_then_sharp():
    r = Renderer()
    try:
        doc = make_pdf(1)
        pix, exact = r.get("preview", doc, 0, 0.5)
        assert pix is None and not exact          # nothing drawn yet
        assert wait_for(r, "preview")
        small, exact = r.get("preview", doc, 0, 0.5)
        assert exact
        big, exact = r.get("preview", doc, 0, 1.0)  # new zoom: the 0.5 picture, stretched
        assert not exact and big.width == round(small.width * 2)
        clip, _ = r.get("preview", doc, 0, 1.0, 0, (10, 10, 60, 40))
        assert clip is not None and (clip.x, clip.y) == (10, 10)
    finally:
        r.stop()


def test_a_page_too_big_to_keep_whole_is_drawn_in_parts():
    big = fitz.open()
    pg = big.new_page(width=20 * 72, height=20 * 72)
    pg.draw_circle((700, 700), 600, color=(1, 0, 0), fill=(0, 0, 1))
    big = fitz.open("pdf", big.tobytes())
    p = plan(big, Settings(layout="normal", sheet_w=24, sheet_h=24))
    views = [fitz.IRect(1000, 1000, 2200, 2000)]
    direct = render_preview(big, p, 0, 3.0, {}, views)
    r = Renderer()
    try:
        raster = lambda doc, pno, zk, angle, clip: r.get("preview", doc, pno, zk, angle, clip)[0]  # noqa: E731
        r.new_round("preview")
        render_preview(big, p, 0, 3.0, {}, views, raster=raster)
        assert r.busy() and wait_for(r, "preview")
        done = render_preview(big, p, 0, 3.0, {}, views, raster=raster)
        assert direct[0].samples == done[0].samples
    finally:
        r.stop()
