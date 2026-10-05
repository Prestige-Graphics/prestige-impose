"""The Pages panel: copy, cut, paste, delete, insert blank, duplicate."""

import pytest

from prestige_impose import pages
from prestige_impose.engine import Settings, plan, trim_rect
from tests.test_engine import make_pdf, words


def labels(doc):
    return [(words(p)[0][2] if words(p) else "blank") for p in doc]


@pytest.fixture
def src():
    doc = make_pdf(4, bleed_in=0.125)
    return doc, doc.tobytes()


def test_build_reorders_repeats_and_adds_blanks(src):
    doc, raw = src
    toks = [("src", 2), ("src", 0), ("src", 0), pages.blank_like(doc, ("src", 1))]
    out = pages.build(raw, toks)
    assert labels(out) == ["p3", "p1", "p1", "blank"]
    # The blank page is cut like its neighbours, so it lays out with them.
    assert tuple(trim_rect(out[3])) == tuple(trim_rect(doc[1]))
    assert not plan(out, Settings(layout="gangup", gang="unique", rows=2, cols=2)).errors


def test_delete_keeps_at_least_one_page():
    toks = pages.original(3)
    out, sel = pages.delete(toks, [0, 2])
    assert out == [("src", 1)] and sel == [0]
    with pytest.raises(ValueError):
        pages.delete(out, [0])


def test_cut_and_paste_moves_pages():
    toks = pages.original(4)
    clip = pages.copy(toks, [0])
    toks, _ = pages.delete(toks, [0])
    toks, sel = pages.insert(toks, 3, clip)        # paste after the last page
    assert toks == [("src", 1), ("src", 2), ("src", 3), ("src", 0)] and sel == [3]


def test_duplicate_goes_after_the_selection():
    toks, sel = pages.duplicate(pages.original(3), [0, 1])
    assert toks == [("src", 0), ("src", 1), ("src", 0), ("src", 1), ("src", 2)]
    assert sel == [2, 3]


def test_original_order_is_recognised():
    assert pages.is_original(pages.original(2), 2)
    assert not pages.is_original([("src", 1), ("src", 0)], 2)


def test_move_to_start_end_and_drag_position():
    toks = pages.original(5)
    assert pages.move(toks, [3], 0) == ([("src", 3), ("src", 0), ("src", 1), ("src", 2),
                                         ("src", 4)], [0])
    assert pages.move(toks, [0, 1], 5)[0][-2:] == [("src", 0), ("src", 1)]
    # Dragging page 1 to just before page 4 (position 3).
    assert [t[1] for t in pages.move(toks, [0], 3)[0]] == [1, 2, 0, 3, 4]


def test_reverse_all_or_selection():
    assert [t[1] for t in pages.reverse(pages.original(4), [])[0]] == [3, 2, 1, 0]
    assert [t[1] for t in pages.reverse(pages.original(4), [1, 3])[0]] == [0, 3, 2, 1]


def test_blank_after_each_page(src):
    doc, raw = src
    toks, _ = pages.blank_after_each(pages.original(2), lambda t: pages.blank_like(doc, t))
    assert labels(pages.build(raw, toks)) == ["p1", "blank", "p2", "blank"]


def test_insert_pages_from_another_pdf(src):
    doc, raw = src
    other = make_pdf(2, w_in=4, h_in=6).tobytes()
    toks, sel = pages.insert(pages.original(2), 1, [("ext", 1, 0), ("ext", 1, 1)])
    out = pages.build(raw, toks, {1: other})
    assert out.page_count == 4 and sel == [1, 2]
    assert round(out[1].rect.width / 72, 2) == 4.0


def test_odd_sizes_flags_the_ones_that_differ():
    letter, card = (612, 792), (252, 144)
    assert pages.odd_sizes([letter, letter, card, letter]) == [2]
    assert pages.odd_sizes([letter, letter]) == []
