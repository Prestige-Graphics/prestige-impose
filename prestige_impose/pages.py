"""
The page list: which pages of the opened file go into the job, in what order,
plus any blank pages added. Edited from the Pages panel (copy, cut, paste,
delete, insert blank, duplicate), like the page thumbnails in Fiery Command
WorkStation or Preview.

The original file is never changed. A page list is a list of tokens:
    ("src", i)                  page i of the original
    ("ext", key, i)             page i of another PDF inserted (extras[key])
    ("blank", w, h, trim)       a blank page, w x h points, trim box or None
and build() turns one into the document that's imposed.

Every operation here is pure: it takes a list (and the selected positions)
and returns a new list and what to select afterwards, so the panel can keep
the old one for Undo.
"""

import pymupdf as fitz


def original(n_pages):
    return [("src", i) for i in range(n_pages)]


def page_of(token, original, extras_docs):
    """The fitz page a src/ext token stands for (None for a blank)."""
    if token[0] == "src":
        return original[token[1]]
    if token[0] == "ext":
        return extras_docs[token[1]][token[2]]
    return None


def size_of(token, original, extras_docs):
    """(w, h) points of the page a token stands for."""
    if token[0] == "blank":
        return token[1], token[2]
    r = page_of(token, original, extras_docs).rect
    return r.width, r.height


def blank_like(doc, token, extras_docs=None):
    """A blank page the size of the page `token` stands for (same cut line, so
    it lays out like its neighbours)."""
    from .engine import has_bleed, trim_rect

    if token[0] == "blank":
        return token
    page = page_of(token, doc, extras_docs or {})
    r = page.rect
    trim = tuple(trim_rect(page)) if has_bleed(page) else None
    return ("blank", r.width, r.height, trim)


def build(original_bytes, tokens, extras=None):
    """The document for a page list, made from the original file's bytes (and
    extras: {key: bytes} of PDFs inserted)."""
    doc = fitz.open("pdf", original_bytes)
    start = {}
    for key in sorted({t[1] for t in tokens if t[0] == "ext"}):
        start[key] = doc.page_count
        doc.insert_pdf(fitz.open("pdf", extras[key]))
    order = []
    for t in tokens:
        if t[0] == "src":
            order.append(t[1])
        elif t[0] == "ext":
            order.append(start[t[1]] + t[2])
        else:
            _, w, h, trim = t
            page = doc.new_page(-1, width=w, height=h)
            if trim:
                page.set_trimbox(fitz.Rect(trim))
            order.append(doc.page_count - 1)
    doc.select(order)   # may repeat a page (duplicates)
    return doc


def _sorted(sel, n):
    return sorted({i for i in sel if 0 <= i < n})


def copy(tokens, sel):
    return [tokens[i] for i in _sorted(sel, len(tokens))]


def delete(tokens, sel):
    """Returns (tokens, selection). Never leaves the list empty (ValueError)."""
    gone = set(_sorted(sel, len(tokens)))
    if len(gone) >= len(tokens):
        raise ValueError("A job needs at least one page.")
    out = [t for i, t in enumerate(tokens) if i not in gone]
    first = min(gone) if gone else 0
    return out, [min(first, len(out) - 1)]


def insert(tokens, at, items):
    """Put items in at position `at` (0 = before the first page)."""
    at = max(0, min(at, len(tokens)))
    out = tokens[:at] + list(items) + tokens[at:]
    return out, list(range(at, at + len(items)))


def duplicate(tokens, sel):
    """A copy of the selected pages straight after the last selected one."""
    picked = _sorted(sel, len(tokens))
    if not picked:
        return list(tokens), []
    return insert(tokens, picked[-1] + 1, [tokens[i] for i in picked])


def move(tokens, sel, to):
    """Move the selected pages, in order, so they start at position `to` of the
    list as it is now (0 = start, len = end)."""
    picked = _sorted(sel, len(tokens))
    if not picked:
        return list(tokens), []
    moving = [tokens[i] for i in picked]
    to -= sum(1 for i in picked if i < to)        # positions shift as they leave
    rest = [t for i, t in enumerate(tokens) if i not in set(picked)]
    return insert(rest, to, moving)


def reverse(tokens, sel):
    """Reverse the selected pages (two or more), or the whole list."""
    picked = _sorted(sel, len(tokens))
    if len(picked) < 2:
        return list(reversed(tokens)), list(sel)
    out = list(tokens)
    for i, t in zip(picked, reversed([tokens[i] for i in picked])):
        out[i] = t
    return out, picked


def blank_after_each(tokens, blank_for):
    """A blank page after every page (one-sided pages becoming duplex)."""
    out = []
    for t in tokens:
        out += [t, blank_for(t)]
    return out, []


def odd_sizes(sizes, tol=0.72):
    """Positions whose size isn't the most common one (within 0.01")."""
    if not sizes:
        return []
    key = lambda wh: (round(wh[0] / tol), round(wh[1] / tol))  # noqa: E731
    counts = {}
    for wh in sizes:
        counts[key(wh)] = counts.get(key(wh), 0) + 1
    common = max(counts, key=counts.get)
    return [i for i, wh in enumerate(sizes) if key(wh) != common]


def is_original(tokens, n_pages):
    return tokens == original(n_pages)
