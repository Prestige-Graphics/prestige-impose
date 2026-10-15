"""Numbered tickets: numbers in order, on the front only, turning with the ticket."""

import time

import pymupdf as fitz
import pytest

from prestige_impose import numbering
from prestige_impose.engine import PT, Settings, describe, plan, render, render_preview

B = 0.125 * PT


def make_ticket():
    """A 5.5 x 2 raffle ticket with 0.125" bleed, a stub on the left, a back."""
    doc = fitz.open()
    for side in ("FRONT", "BACK"):
        pg = doc.new_page(width=5.5 * PT + 2 * B, height=2 * PT + 2 * B)
        pg.insert_text((B + 1.7 * PT, B + 40), f"RAFFLE {side}", fontsize=16)
        pg.set_trimbox(fitz.Rect(B, B, B + 5.5 * PT, B + 2 * PT))
    return fitz.open("pdf", doc.tobytes())


BOXES = ({"rect": [B + 3.9 * PT, B + 1.4 * PT, B + 5.4 * PT, B + 1.9 * PT], "size": 14,
          "align": "right", "rotate": 0},
         {"rect": [B + 0.1 * PT, B + 0.2 * PT, B + 0.6 * PT, B + 1.8 * PT], "size": 12,
          "align": "center", "rotate": 90})


def ticket_settings(**kw):
    base = dict(rows=7, cols=2, duplex=True, gutter_x=0.25, gutter_y=0.25, numbering=True,
                num_start=1, num_count=25, num_prefix="No. ", num_boxes=BOXES)
    return Settings(**{**base, **kw})


def numbers_on(page):
    return sorted(int(w[4]) for w in page.get_text("words") if w[4].isdigit())


def test_numbers_run_in_order_twice_per_ticket_front_only():
    src = make_ticket()
    p = plan(src, ticket_settings())
    assert not p.errors and p.sheet_count == 2 and p.per_sheet == 14
    out = render(src, p)
    assert len(out) == 4
    assert numbers_on(out[0]) == sorted(list(range(1, 15)) * 2)    # ticket and stub
    assert numbers_on(out[1]) == []                                # backs: no numbers
    assert numbers_on(out[2]) == sorted(list(range(15, 26)) * 2)
    assert any("3 slot(s) on the last sheet are empty" in w for w in p.warnings)
    assert "Numbered tickets No. 1 to No. 25 (25 tickets)" in describe(p, 2)


def test_leading_zeros_match_the_biggest_number():
    s = ticket_settings(num_start=1, num_count=500, num_zeros=True)
    assert numbering.number_text(7, s) == "No. 007"
    assert numbering.number_text(7, ticket_settings(num_zeros=False)) == "No. 7"


@pytest.mark.parametrize("stub_turn", [90, 270])
@pytest.mark.parametrize("turn,style,s180", [(0, "standard", "none"), (90, "standard", "none"),
                                             (0, "head", "none"), (90, "head", "front")])
def test_numbers_turn_with_the_ticket(turn, style, s180, stub_turn):
    """Each number reads the same way relative to the ticket's own text, at every turn."""
    src = make_ticket()
    boxes = (BOXES[0], {**BOXES[1], "rotate": stub_turn})
    p = plan(src, ticket_settings(rows=2, cols=2, rotate=turn, layout_style=style, slot_180=s180,
                                  num_start=12, num_count=4, num_boxes=boxes, duplex=False))
    page = render(src, p)[0]
    lines = [("".join(sp["text"] for sp in ln["spans"]), tuple(round(v) for v in ln["dir"]),
              fitz.Rect(ln["bbox"]))
             for blk in page.get_text("dict")["blocks"] for ln in blk.get("lines", [])]
    for pl in p.sides[0][0]:
        here = [ln for ln in lines if pl.visible.contains(ln[2].tl + (1, 1))]
        art = next(d for t, d, _ in here if "RAFFLE" in t)
        stub = art
        for _ in range(stub_turn // 90):          # turned counter-clockwise on the page
            stub = (stub[1], -stub[0])
        assert sorted(d for t, d, _ in here if "No" in t) == sorted([art, stub])


def test_no_boxes_is_an_error_and_ticket_without_back_goes_one_sided():
    src = make_ticket()
    empty = plan(src, ticket_settings(num_boxes=()))
    assert empty.errors and empty.sheet_count == 1   # not a run of identical blank sheets
    one = fitz.open()
    one.insert_pdf(src, to_page=0)
    p = plan(one, ticket_settings())
    assert not p.settings.duplex and any("no back" in w for w in p.warnings)


def test_preview_shows_the_numbers():
    src = make_ticket()
    p = plan(src, ticket_settings())
    pix = render_preview(src, p, 1, 0.5, {})
    assert len(pix) == 2 and pix[0].width == round(12 * PT * 0.5)


def test_numbering_saved_in_a_preset():
    s = Settings.from_dict({**ticket_settings().__dict__, "num_boxes": [dict(b) for b in BOXES],
                            "num_colour": [0, 1, 1, 0]})
    assert s.num_boxes == BOXES and s.num_colour == (0.0, 1.0, 1.0, 0.0)


def test_thousands_of_tickets_are_quick_and_small():
    src = make_ticket()
    p = plan(src, ticket_settings(num_count=3000))
    t = time.time()
    raw = render(src, p).tobytes(garbage=4, deflate=True)
    assert time.time() - t < 30 and len(raw) < 2_000_000


def test_send_to_fiery_sends_the_run_once():
    from prestige_impose import fiery
    p = plan(make_ticket(), ticket_settings(num_count=40))
    assert fiery.copies_for(p, 1) == (1, "1 set(s) of 3 sheet(s), tickets 1 to 40")


FRAMED = ({**BOXES[0], "bg": [0, 0, 1, 0], "border": [0, 0, 0, 1], "border_w": 1, "pad": 3},
          {**BOXES[1], "bg": [0, 0, 0, 0], "pad": 2})


@pytest.mark.parametrize("fit", ["number", "widest"])
@pytest.mark.parametrize("rotate", [0, 90, 270])
@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_box_wraps_the_longest_number_exactly(fit, rotate, align):
    box = {"rect": [100, 100, 200, 200], "size": 12, "align": align, "rotate": rotate,
           "bg": [0, 0, 0, 0.2], "border": [0, 0, 0, 1], "border_w": 1, "pad": 3, "bg_fit": fit}
    s = ticket_settings(num_count=5000, num_boxes=(box,))
    page = fitz.open().new_page(width=400, height=400)
    numbering.draw_numbers(page, s, 5000)
    drawn = page.get_drawings()[0]["rect"] + (-0.5, -0.5, 0.5, 0.5)    # + half the border
    fitted = numbering.fit_box(box, s)["rect"]
    assert all(abs(a - b) < 0.05 for a, b in zip(drawn, fitted))
    assert numbering.fit_box({**box, "rect": fitted}, s)["rect"] == fitted   # stays put


def test_box_grows_from_its_aligned_end():
    box = {"rect": [100, 100, 150, 120], "size": 12, "align": "left", "rotate": 0}
    s = ticket_settings(num_count=9, num_prefix="", num_boxes=(box,))
    small = numbering.fit_box(box, s)["rect"]
    big = numbering.fit_box(box, ticket_settings(num_count=5000, num_prefix="",
                                                 num_boxes=(box,)))["rect"]
    assert small[0] == big[0] == 100 and big[2] > small[2]          # grew to the right
    right = numbering.fit_box({**box, "align": "right", "size": 24}, s)["rect"]
    assert right[2] == 150 and right[3] - right[1] > small[3] - small[1]
    up = numbering.fit_box({**box, "rect": [100, 100, 120, 200], "rotate": 90}, s)["rect"]
    assert up[3] == 200        # reads upward: left-aligned starts at the bottom
    no_frame = numbering.box_size(box, s)
    framed = numbering.box_size({**box, "bg": [0, 0, 0, 0], "pad": 0}, s)
    assert framed == no_frame   # padding 0: the background is tight on the number


def test_background_hugs_the_number_or_fits_the_widest():
    s = ticket_settings(num_start=8, num_count=5, num_boxes=(FRAMED[0],))   # 8 to 12
    widths = {}
    for fit in ("number", "widest"):
        s.num_boxes = ({**FRAMED[0], "bg_fit": fit},)
        for n in (9, 10):
            page = fitz.open().new_page(width=8 * PT, height=3 * PT)
            numbering.draw_numbers(page, s, n)
            widths[fit, n] = round(page.get_drawings()[0]["rect"].width, 1)
    assert widths["number", 9] < widths["number", 10]
    assert widths["widest", 9] == widths["widest", 10] == widths["number", 10]


@pytest.mark.parametrize("turn", [0, 90])
def test_backgrounds_go_under_every_number_on_the_sheet(turn):
    src = make_ticket()
    rows, cols = (7, 2) if turn == 0 else (3, 4)
    p = plan(src, ticket_settings(rotate=turn, rows=rows, cols=cols, num_count=14,
                                  num_boxes=FRAMED, duplex=False))
    assert not any("bigger than" in w for w in p.warnings)
    page = render(src, p)[0]
    bgs = [d["rect"] for d in page.get_drawings() if d.get("fill") is not None]
    words = [(fitz.Rect(w[:4]), w[4]) for w in page.get_text("words") if w[4].isdigit()]
    assert len(words) == 2 * p.per_sheet and len(bgs) == 2 * p.per_sheet
    for r, _ in words:     # every number sits on a background
        mid = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        assert any(b.contains(mid) for b in bgs)
    # backgrounds are drawn before (under) the numbers
    raw = page.read_contents()
    assert raw.index(b" re") < raw.index(b"BT")


def test_framed_boxes_saved_in_a_preset():
    s = Settings.from_dict({**ticket_settings().__dict__, "num_boxes": [dict(b) for b in FRAMED]})
    assert s.num_boxes[0]["bg"] == [0, 0, 1, 0] and s.num_boxes[1]["pad"] == 2


def slot_numbers(page, p, k):
    """The number in each slot of sheet k, in slot order (read off the PDF)."""
    words = [w for w in page.get_text("words") if w[4].isdigit()]
    out = []
    for pl in p.sides[k][0]:
        inside = sorted({int(w[4]) for w in words if pl.visible.contains(fitz.Rect(w[:4]))})
        out.append(inside[0] if inside else None)
    return out


def test_cut_and_stack_each_slot_is_a_run_in_order():
    src = make_ticket()
    p = plan(src, ticket_settings(num_count=500, num_order="stack", duplex=False))
    assert p.sheet_count == 36 and p.per_sheet == 14
    out = render(src, p)
    assert slot_numbers(out[0], p, 0) == [1 + 36 * i for i in range(14)]
    assert slot_numbers(out[1], p, 1) == [2 + 36 * i for i in range(14)]
    # The last stack is 4 short: the last 4 sheets have a blank last spot.
    assert slot_numbers(out[31], p, 31)[-1] == 500
    assert len(p.sides[32][0]) == 13 and len(p.sides[35][0]) == 13
    every = sorted(pl.number for f, _ in p.sides for pl in f)
    assert every == list(range(1, 501))          # each number exactly once
    assert any("4 spot(s) are left blank" in w for w in p.warnings)
    assert "cut and stack: 14 stacks (1-36, 37-72, 73-108 ... 469-500)" in describe(p, 1)


def test_cut_and_stack_extras_fill_the_sheets():
    src = make_ticket()
    p = plan(src, ticket_settings(num_count=500, num_order="stack", num_extras="number",
                                  num_zeros=True))
    assert p.numbered == (1, 504) and all(len(f) == 14 for f, _ in p.sides)
    assert numbering.number_text(7, p.settings) == "No. 007"
    assert any("numbered 501 to 504" in w for w in p.warnings)
    from prestige_impose import fiery
    assert fiery.copies_for(p, 1)[1] == "1 set(s) of 36 sheet(s), tickets 1 to 504"


def test_cut_and_stack_saved_in_a_preset():
    s = Settings.from_dict({**ticket_settings(num_order="stack", num_extras="number").__dict__})
    assert (s.num_order, s.num_extras) == ("stack", "number")
