"""
Page drawing in a helper process, so a heavy file (an Illustrator page with tens
of thousands of shapes, say) never freezes the window.

The window asks for a page at a zoom; until the helper has drawn it, it gets the
nearest picture already drawn, stretched to fit (a little soft for a moment), or
None. The helper draws the newest requests first and drops ones the window has
moved past (zooming through five steps only draws the last). Each page is read
once into a display list, so redrawing it at another zoom skips re-reading the
file.

PyMuPDF must not be used from two threads at once, hence a process, not a
thread: the helper opens its own copy of the PDF.

If the helper can't start, `Renderer.ok` is False and the window draws as
before, in the window's own process.
"""

import itertools
import multiprocessing as mp
import queue

import pymupdf as fitz

KEEP_DOCS = 4          # PDFs the helper keeps open (current file, its bleed copy...)
CACHE_MAX_PX = 120_000_000    # pictures the window keeps, in pixels (~360 MB RGB)


def _worker(requests, results):
    docs, order = {}, []          # token -> (Document, {pno: DisplayList})
    parent = mp.parent_process()
    while True:
        try:
            batch = [requests.get(timeout=2)]
        except queue.Empty:
            if parent is not None and not parent.is_alive():
                return            # the window was force-closed: don't linger
            continue
        while True:
            try:
                batch.append(requests.get_nowait())
            except queue.Empty:
                break
        jobs, newest = [], {}
        for msg in batch:
            if msg[0] == "stop":
                return
            if msg[0] == "doc":
                _, token, data = msg
                docs[token] = (fitz.open("pdf", data), {})
                order.append(token)
                while len(order) > KEEP_DOCS:
                    docs.pop(order.pop(0), None)
            elif msg[0] == "draw":
                jobs.append(msg)
                newest[msg[1]] = max(newest.get(msg[1], 0), msg[2])
        done = set()
        for _, channel, gen, key, token, pno, zoom, angle, clip in reversed(jobs):
            if gen != newest[channel] or key in done:
                continue      # the window has moved on since asking
            done.add(key)
            try:
                doc, lists = docs[token]
                dl = lists.get(pno)
                if dl is None:
                    dl = lists[pno] = doc[pno].get_displaylist()
                pix = dl.get_pixmap(matrix=fitz.Matrix(zoom, zoom).prerotate(angle),
                                    clip=fitz.Rect(clip) if clip else None, alpha=False)
                results.put(("pix", key, pix.x, pix.y, pix.width, pix.height, pix.samples))
            except Exception as e:   # noqa: BLE001 - reported to the window, which draws it itself
                results.put(("fail", key, f"{type(e).__name__}: {e}"))


class Renderer:
    def __init__(self):
        self.ok = False
        self._ids = itertools.count(1)
        self.cache = {}           # key -> Pixmap (in page * zoom * turn space, like get_pixmap)
        self.origin = {}          # key -> its (x, y) in that space
        self.pending = set()
        self.failed = set()
        self.gen = {}
        try:
            ctx = mp.get_context("spawn")
            self.requests, self.results = ctx.Queue(), ctx.Queue()
            self.proc = ctx.Process(target=_worker, args=(self.requests, self.results),
                                    daemon=True, name="Prestige Impose drawing")
            self.proc.start()
            self.ok = True
        except Exception:   # noqa: BLE001 - fall back to drawing in the window's process
            self.ok = False

    def token(self, doc):
        """The helper's name for this PDF; sends it a copy the first time."""
        t = getattr(doc, "_pi_token", None)
        if t is None:
            t = next(self._ids)
            doc._pi_token = t
            self.requests.put(("doc", t, doc.tobytes()))
        return t

    def new_round(self, channel):
        """A fresh redraw of `channel` ("preview", "pages"): older requests on it are stale."""
        self.gen[channel] = self.gen.get(channel, 0) + 1
        self.pending = {k for k in self.pending if k[0] != channel}

    def get(self, channel, doc, pno, zoom, angle=0, clip=None):
        """
        The page drawn at this zoom and turn (clip: only that part, in page
        points), as get_pixmap would give it. If the helper hasn't drawn it yet,
        it's asked to, and the best stand-in comes back instead (or None).
        Returns (pixmap or None, exact).
        """
        t = self.token(doc)
        clip_key = tuple(round(v, 1) for v in clip) if clip else None
        key = (channel, t, pno, round(zoom, 5), angle % 360, clip_key)
        pix = self.cache.get(key)
        if pix is not None:
            pix.set_origin(*self.origin[key])   # callers move it to where it goes
            return pix, True
        if key in self.failed:
            return None, True
        if key not in self.pending:
            self.pending.add(key)
            self.requests.put(("draw", channel, self.gen.get(channel, 0), key, t, pno, zoom,
                               angle % 360, tuple(clip) if clip else None))
        return self._stand_in(t, pno, zoom, angle % 360, clip), False

    def _stand_in(self, t, pno, zoom, angle, clip):
        """The nearest whole-page picture already drawn, stretched to this zoom."""
        best = None
        for k, pix in self.cache.items():
            _, tk, pn, z, a, c = k
            if tk == t and pn == pno and a == angle and c is None:
                if best is None or abs(z - zoom) < abs(best[0] - zoom):
                    best = (z, pix)
                    pix.set_origin(*self.origin[k])
        if best is None:
            return None
        z, src = best
        f = zoom / z
        want = (fitz.Rect(src.irect) * fitz.Matrix(f, f)).irect     # the whole page at this zoom
        if clip:   # just the part asked for, cut from the stand-in first
            m = fitz.Matrix(zoom, zoom).prerotate(angle)
            part = (fitz.Rect(clip) * m).irect & want
            if part.is_empty:
                return None
            from_src = (fitz.Rect(part) * fitz.Matrix(1 / f, 1 / f)).irect & src.irect
            if from_src.is_empty:
                return None
            piece = fitz.Pixmap(fitz.csRGB, from_src, False)
            piece.copy(src, from_src)
            out = fitz.Pixmap(piece, max(1, part.width), max(1, part.height), None)
            out.set_origin(part.x0, part.y0)
            return out
        if want.width * want.height > 40_000_000:
            return None
        out = fitz.Pixmap(src, max(1, want.width), max(1, want.height), None)
        out.set_origin(want.x0, want.y0)
        return out

    def poll(self):
        """Take in what the helper has drawn. Returns the channels that got something."""
        got = set()
        while True:
            try:
                msg = self.results.get_nowait()
            except (queue.Empty, OSError, EOFError):
                break
            key = msg[1]
            self.pending.discard(key)
            if msg[0] == "pix":
                _, _, x, y, w, h, samples = msg
                pix = fitz.Pixmap(fitz.csRGB, w, h, samples, False)
                pix.set_origin(x, y)
                self.cache[key] = pix
                self.origin[key] = (x, y)
            else:
                self.failed.add(key)
            got.add(key[0])
        self._trim()
        return got

    def _trim(self):
        total = sum(p.width * p.height for p in self.cache.values())
        for k in list(self.cache):
            if total <= CACHE_MAX_PX:
                break
            total -= self.cache[k].width * self.cache[k].height
            del self.cache[k]
            self.origin.pop(k, None)

    def busy(self):
        return bool(self.pending)

    def stop(self):
        """End the helper now (it has nothing to save). Closing never waits on
        it, even mid-drawing or mid-way through receiving a big file."""
        if self.ok:
            self.ok = False
            try:
                for q in (self.requests, self.results):
                    q.cancel_join_thread()   # don't hold up the app's exit flushing these
                self.proc.terminate()
                self.proc.join(timeout=0.5)
            except Exception:   # noqa: BLE001
                pass
