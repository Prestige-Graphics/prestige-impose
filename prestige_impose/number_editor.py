"""
The number editor: the front of the ticket, large, where number boxes are
drawn. Drag on the ticket to add a box (one on the ticket, one on the stub...),
drag a box to move it, drag a corner to make the number bigger or smaller.
Every box shows the same number. The format (start, how many, leading zeros,
text before, font, colour) is shared; size, alignment, direction, background
and border are per box.

A box always wraps what's in it: the longest number in the run, plus padding
and border. So it shows exactly the room every number needs, and it grows or
shrinks as the size, padding, text before or how many change, keeping its
aligned end in place. A box past the edge of the ticket shows orange.

Shortcuts: Ctrl+C / Ctrl+X / Ctrl+V copy, cut and paste boxes (paste lands
under the mouse), Ctrl+D duplicates, Alt+drag drags out a copy, Ctrl+Z undoes,
Ctrl+Y (or Ctrl+Shift+Z) redoes, arrows nudge (Shift: further), Delete removes.
Cmd instead of Ctrl on a Mac.
"""

import copy
import tkinter as tk
from dataclasses import replace
from tkinter import messagebox, ttk

import pymupdf as fitz

from . import numbering
from .paths import IS_MAC

ALIGN_NAMES = {"Left": "left", "Centre": "center", "Right": "right"}
DIRECTIONS = {"Across": 0, "Up (bottom to top)": 90, "Down (top to bottom)": 270}
COLOUR_CHOICES = list(numbering.COLOURS) + ["Custom CMYK"]
BG_CHOICES = ["None"] + list(numbering.BOX_COLOURS) + ["Custom CMYK"]
BORDER_CHOICES = ["None", "Black", "Red", "White", "Custom CMYK"]
FIT_NAMES = {"Hugs each number": "number", "Widest number, all the same": "widest"}
SHOW = ("First number", "Last number")
HANDLE = 5          # resize handles, pixels from the middle
MIN_BOX = 8         # smallest box drawn, pixels
OUTSIDE = "#e8710a"     # a box past the ticket's edge
GUIDE = "#e0177d"       # snap guides
SNAP_PX = 6             # how close (screen pixels) a box edge or centre snaps
CURSORS = {"tl": "size_nw_se", "br": "size_nw_se", "tr": "size_ne_sw", "bl": "size_ne_sw"}
OPPOSITE = {"tl": "br", "br": "tl", "tr": "bl", "bl": "tr"}

_clipboard = []      # copied boxes, kept while the app is open (between editor windows too)


def cmyk_text(c):
    return " ".join(f"{v * 100:g}" for v in c)


def parse_cmyk(text):
    """'0 100 100 0' (percentages) -> (0, 1, 1, 0); None if it isn't four of 0-100."""
    try:
        c = [float(x) / 100 for x in text.replace(",", " ").replace("%", " ").split()]
    except ValueError:
        return None
    return tuple(c) if len(c) == 4 and all(0 <= v <= 1 for v in c) else None


def _inside(a, b, slack=0.05):
    return (a.x0 >= b.x0 - slack and a.y0 >= b.y0 - slack
            and a.x1 <= b.x1 + slack and a.y1 <= b.y1 + slack)


def colour_name(c, names):
    if c is None:
        return "None"
    return next((n for n, v in names.items() if tuple(v) == tuple(c)), "Custom CMYK")


class NumberEditor(tk.Toplevel):
    def __init__(self, app, src, settings, on_done):
        super().__init__(app)
        self.app, self.src, self.on_done = app, src, on_done
        self.s = replace(settings)
        self.boxes = [dict(b) for b in settings.num_boxes]
        self.sel = 0 if self.boxes else None
        self._drag = None
        self._guides = []        # snap lines showing while a box is dragged: ("x" or "y", where)
        self._img = None
        self._loading = False
        self.undo_stack, self.redo_stack = [], []
        self._last_edit = None    # coalesces typing in one field into one undo step
        self._pastes = 0
        self.title("Place numbers")
        self.transient(app)
        self.geometry("1100x700")
        self.minsize(900, 480)

        right = ttk.Frame(self, width=350)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        self.canvas = tk.Canvas(self, bg="#c8c8c8", highlightthickness=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda e: self.redraw())
        self.canvas.bind("<ButtonPress-1>", self.press)
        for alt in ("Alt", "Option") if IS_MAC else ("Alt",):
            try:
                self.canvas.bind(f"<{alt}-ButtonPress-1>", lambda e: self.press(e, copy_it=True))
            except tk.TclError:
                pass
        self.canvas.bind("<B1-Motion>", self.motion)
        self.canvas.bind("<ButtonRelease-1>", self.release)
        self.canvas.bind("<Motion>", self.hover)

        self._build_panel(right)
        self._bind_keys()
        self.load_box()
        self.after(50, self.redraw)

    # ------------------------------------------------------------- panel

    def _build_panel(self, outer):
        btns = ttk.Frame(outer, padding=(12, 8))
        btns.pack(side="bottom", fill="x")
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(btns, text="OK", command=self.ok).pack(side="right", padx=(0, 6))

        # The settings scroll if the screen is short.
        holder = ttk.Frame(outer)
        holder.pack(fill="both", expand=True)
        sc = tk.Canvas(holder, highlightthickness=0, borderwidth=0,
                       bg=ttk.Style().lookup("TFrame", "background") or "#f0f0f0")
        bar = ttk.Scrollbar(holder, orient="vertical", command=sc.yview)
        p = ttk.Frame(sc, padding=(12, 12, 8, 4))
        win = sc.create_window(0, 0, window=p, anchor="nw")
        sc.configure(yscrollcommand=bar.set)
        sc.pack(side="left", fill="both", expand=True)

        def resized(_=None):
            sc.configure(scrollregion=(0, 0, p.winfo_reqwidth(), p.winfo_reqheight()))
            sc.itemconfigure(win, width=sc.winfo_width())
            if p.winfo_reqheight() > sc.winfo_height() + 1:
                bar.pack(side="right", fill="y", before=sc)
            else:
                bar.pack_forget()
                sc.yview_moveto(0)
        p.bind("<Configure>", resized)
        sc.bind("<Configure>", resized)

        def wheel(e):
            if bar.winfo_ismapped():
                sc.yview_scroll(int(-e.delta / (1 if IS_MAC else 120)) or (-1 if e.delta > 0 else 1),
                                "units")
        holder.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", wheel))
        holder.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))
        self.panel = p

        s = self.s
        mod = "Cmd" if IS_MAC else "Ctrl"
        ttk.Label(p, text="Drag on the ticket to add a number box. Drag a box to move it, a "
                          "corner to make the number bigger or smaller. Every box gets the "
                          "same number.",
                  wraplength=310, style="Small.TLabel").pack(anchor="w")
        ttk.Label(p, text=f"Alt+drag a box: copy it.  {mod}+D: duplicate.  {mod}+C / X / V: "
                          f"copy, cut, paste.  {mod}+Z: undo.  Arrows: nudge.  Boxes snap to the "
                          f"ticket's centre and edges and to each other; hold Shift to "
                          f"move freely.",
                  wraplength=310, style="Small.TLabel", foreground="#555").pack(
            anchor="w", pady=(4, 10))

        ttk.Label(p, text="Number", style="Head.TLabel").pack(anchor="w")
        self.v = {
            "start": tk.StringVar(value=str(s.num_start)),
            "count": tk.StringVar(value=str(s.num_count)),
            "zeros": tk.BooleanVar(value=s.num_zeros),
            "prefix": tk.StringVar(value=s.num_prefix),
            "font": tk.StringVar(value=s.num_font if s.num_font in numbering.FONTS
                                 else "Helvetica"),
            "colour": tk.StringVar(value=colour_name(s.num_colour, numbering.COLOURS)),
            "cmyk": tk.StringVar(value=cmyk_text(s.num_colour)),
            "show": tk.StringVar(value=SHOW[0]),
            "size": tk.StringVar(), "align": tk.StringVar(), "dir": tk.StringVar(),
            "bg": tk.StringVar(), "bg_cmyk": tk.StringVar(), "fit": tk.StringVar(),
            "border": tk.StringVar(), "border_cmyk": tk.StringVar(),
            "border_w": tk.StringVar(), "pad": tk.StringVar(),
        }
        v = self.v

        def row(parent, label, widget, pack=True):
            f = ttk.Frame(parent)
            if pack:
                f.pack(fill="x", pady=3)
            ttk.Label(f, text=label, width=14).pack(side="left")
            widget(f).pack(side="left", fill="x", expand=True)
            return f

        def spin(var, lo, hi, inc=1.0):
            return lambda f: ttk.Spinbox(f, from_=lo, to=hi, increment=inc, textvariable=var,
                                         width=8)

        def combo(var, values):
            return lambda f: ttk.Combobox(f, textvariable=var, state="readonly", values=values)

        row(p, "First number:", spin(v["start"], 0, 999999))
        row(p, "How many:", spin(v["count"], 1, numbering.MAX_TICKETS))
        ttk.Checkbutton(p, text="Leading zeros (001, 002...)", variable=v["zeros"]).pack(
            anchor="w", pady=3)
        row(p, "Text before:", lambda f: ttk.Entry(f, textvariable=v["prefix"], width=12))
        row(p, "Font:", combo(v["font"], list(numbering.FONTS)))
        row(p, "Colour:", combo(v["colour"], COLOUR_CHOICES))
        self.cmyk_row = row(p, "  CMYK %:", lambda f: ttk.Entry(f, textvariable=v["cmyk"]))
        self.sample = ttk.Label(p, text="", style="Small.TLabel", foreground="#555")
        self.sample.pack(anchor="w", pady=(4, 0))
        row(p, "Preview shows:", combo(v["show"], SHOW))

        ttk.Separator(p).pack(fill="x", pady=10)
        ttk.Label(p, text="Selected box", style="Head.TLabel").pack(anchor="w")
        box_area = ttk.Frame(p)   # the box's settings, or "no box selected"
        box_area.pack(fill="x")
        bf = self.box_frame = ttk.Frame(box_area)
        row(bf, "Size (pt):", spin(v["size"], 4, 200))
        row(bf, "Align:", combo(v["align"], list(ALIGN_NAMES)))
        row(bf, "Direction:", combo(v["dir"], list(DIRECTIONS)))
        row(bf, "Background:", combo(v["bg"], BG_CHOICES))
        self.bg_cmyk_row = row(bf, "  CMYK %:", lambda f: ttk.Entry(f, textvariable=v["bg_cmyk"]),
                               pack=False)
        self.border_anchor = row(bf, "Border:", combo(v["border"], BORDER_CHOICES))
        self.border_cmyk_row = row(bf, "  CMYK %:",
                                   lambda f: ttk.Entry(f, textvariable=v["border_cmyk"]), pack=False)
        self.border_w_row = row(bf, "  Thickness (pt):", spin(v["border_w"], 0.25, 10, 0.25),
                                pack=False)
        self.frame_anchor = ttk.Frame(bf)
        self.frame_anchor.pack(fill="x")
        self.pad_row = row(bf, "Padding (pt):", spin(v["pad"], 0, 50, 0.5), pack=False)
        self.fit_row = row(bf, "Box width:", combo(v["fit"], list(FIT_NAMES)), pack=False)
        self.fit_note = ttk.Label(bf, text="", style="Small.TLabel", wraplength=310)
        self.fit_note.pack(anchor="w", pady=(6, 0))
        acts = ttk.Frame(bf)
        acts.pack(fill="x", pady=(8, 0))
        ttk.Button(acts, text="Duplicate", command=self.duplicate).pack(side="left")
        ttk.Button(acts, text="Delete box", command=self.delete_box).pack(side="left", padx=6)
        self.no_box = ttk.Label(box_area, text="No box selected. Drag on the ticket to add one, "
                                               "or click one to select it.",
                                style="Small.TLabel", foreground="#555", wraplength=310)
        undo = ttk.Frame(p)
        undo.pack(fill="x", pady=(12, 0))
        self.undo_btn = ttk.Button(undo, text="Undo", command=self.undo)
        self.undo_btn.pack(side="left")
        self.redo_btn = ttk.Button(undo, text="Redo", command=self.redo)
        self.redo_btn.pack(side="left", padx=6)

        for key in ("start", "count", "zeros", "prefix", "font", "colour", "cmyk", "show"):
            v[key].trace_add("write", lambda *_: self.redraw())
        for key in ("size", "align", "dir", "bg", "bg_cmyk", "fit", "border", "border_cmyk",
                    "border_w", "pad"):
            v[key].trace_add("write", lambda *_, k=key: self.store_box(k))

    def _bind_keys(self):
        mods = ("Control", "Command") if IS_MAC else ("Control",)
        acts = {"c": self.copy, "x": self.cut, "v": self.paste, "d": self.duplicate,
                "z": self.undo, "y": self.redo, "Z": self.redo}
        for m in mods:
            for k, fn in acts.items():
                try:
                    self.bind(f"<{m}-{k}>", lambda e, fn=fn: self._key(e, fn))
                    if k in "cxvdy":
                        self.bind(f"<{m}-{k.upper()}>", lambda e, fn=fn: self._key(e, fn))
                except tk.TclError:
                    pass
        for key in ("Delete", "BackSpace"):
            self.bind(f"<{key}>", lambda e: self._key(e, self.delete_box))
        for key, (dx, dy) in {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1),
                              "Down": (0, 1)}.items():
            self.bind(f"<{key}>", lambda e, d=(dx, dy): self._key(e, lambda: self.nudge(*d, 1)))
            self.bind(f"<Shift-{key}>", lambda e, d=(dx, dy): self._key(e, lambda: self.nudge(*d, 9)))
        self.bind("<Escape>", lambda e: self.destroy())

    def _key(self, e, fn):
        """Shortcuts work on the boxes, except while typing in a field."""
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Spinbox, ttk.Combobox)):
            return None
        fn()
        return "break"

    def settings(self, quiet=True):
        """The editor's numbering settings; bad input is kept as it was (quiet)
        or raises ValueError (on OK)."""
        v, s = self.v, replace(self.s)

        def whole(key, label, low):
            try:
                n = int(v[key].get().strip())
                if n < low:
                    raise ValueError
                return n
            except ValueError:
                if quiet:
                    return getattr(s, "num_" + key)
                raise ValueError(f"{label} must be a whole number of {low} or more.")

        s.num_start = whole("start", "First number", 0)
        s.num_count = whole("count", "How many", 1)
        s.num_zeros = v["zeros"].get()
        s.num_prefix = v["prefix"].get()
        s.num_font = v["font"].get()
        if v["colour"].get() in numbering.COLOURS:
            s.num_colour = numbering.COLOURS[v["colour"].get()]
        else:
            cmyk = parse_cmyk(v["cmyk"].get())
            if cmyk:
                s.num_colour = cmyk
            elif not quiet:
                raise ValueError("CMYK needs four percentages, e.g. 0 100 100 0.")
        font = numbering._font(s)
        self.boxes = [numbering.fit_box(b, s, font) for b in self.boxes]
        s.num_boxes = tuple(dict(b) for b in self.boxes)
        return s

    # ------------------------------------------------------- selected box

    def load_box(self):
        """Show the selected box's settings in the panel."""
        self._sync_buttons()
        if self.sel is None:
            self.box_frame.pack_forget()
            self.no_box.pack(anchor="w")
            return
        self.no_box.pack_forget()
        self.box_frame.pack(fill="x")
        b, v = self.boxes[self.sel], self.v
        self._loading = True
        try:
            v["size"].set(f"{b.get('size', 14):g}")
            v["align"].set(next(n for n, a in ALIGN_NAMES.items() if a == b.get("align", "center")))
            v["dir"].set(next(n for n, d in DIRECTIONS.items() if d == b.get("rotate", 0)))
            v["bg"].set(colour_name(b.get("bg"), numbering.BOX_COLOURS))
            if b.get("bg"):
                v["bg_cmyk"].set(cmyk_text(b["bg"]))
            border_names = {n: numbering.BOX_COLOURS[n] for n in BORDER_CHOICES
                            if n in numbering.BOX_COLOURS}
            v["border"].set(colour_name(b.get("border"), border_names))
            if b.get("border"):
                v["border_cmyk"].set(cmyk_text(b["border"]))
            v["border_w"].set(f"{b.get('border_w', 0.5):g}")
            v["pad"].set(f"{b.get('pad', 2):g}")
            v["fit"].set(next(n for n, f in FIT_NAMES.items() if f == b.get("bg_fit", "number")))
        finally:
            self._loading = False
        self._sync_rows()

    def _sync_rows(self):
        """Show the CMYK / thickness / padding rows only when they apply."""
        v = self.v
        show = {self.bg_cmyk_row: v["bg"].get() == "Custom CMYK",
                self.border_cmyk_row: v["border"].get() == "Custom CMYK",
                self.border_w_row: v["border"].get() != "None",
                self.pad_row: v["bg"].get() != "None" or v["border"].get() != "None",
                self.fit_row: v["bg"].get() != "None" or v["border"].get() != "None"}
        order = [(self.bg_cmyk_row, self.border_anchor, "before"),
                 (self.border_cmyk_row, self.frame_anchor, "before"),
                 (self.border_w_row, self.frame_anchor, "before"),
                 (self.pad_row, self.fit_note, "before"),
                 (self.fit_row, self.fit_note, "before")]
        for w, anchor, where in order:
            if show[w] and not w.winfo_ismapped():
                w.pack(fill="x", pady=3, **{where: anchor})
            elif not show[w]:
                w.pack_forget()

    def store_box(self, key=None):
        if self.sel is None or self._loading:
            return
        b, v = self.boxes[self.sel], self.v
        before = copy.deepcopy(b)
        try:
            b["size"] = max(1.0, float(v["size"].get()))
        except ValueError:
            pass
        b["align"] = ALIGN_NAMES.get(v["align"].get(), "center")
        b["rotate"] = DIRECTIONS.get(v["dir"].get(), 0)
        name = v["bg"].get()
        if name == "None":
            b.pop("bg", None)
        elif name in numbering.BOX_COLOURS:
            b["bg"] = list(numbering.BOX_COLOURS[name])
        elif parse_cmyk(v["bg_cmyk"].get()):
            b["bg"] = list(parse_cmyk(v["bg_cmyk"].get()))
        elif key == "bg":
            v["bg_cmyk"].set(cmyk_text(b.get("bg") or (0, 0, 0, 0.1)))
            return
        name = v["border"].get()
        if name == "None":
            b.pop("border", None)
        elif name in numbering.BOX_COLOURS:
            b["border"] = list(numbering.BOX_COLOURS[name])
        elif parse_cmyk(v["border_cmyk"].get()):
            b["border"] = list(parse_cmyk(v["border_cmyk"].get()))
        elif key == "border":
            v["border_cmyk"].set(cmyk_text(b.get("border") or (0, 0, 0, 1)))
            return
        for k in ("border_w", "pad"):
            try:
                b[k] = max(0.0, float(v[k].get()))
            except ValueError:
                pass
        b["bg_fit"] = FIT_NAMES.get(v["fit"].get(), "number")
        if b != before:
            # One undo step per field being edited, not per keystroke.
            after, self.boxes[self.sel] = b, before
            self._checkpoint(("field", self.sel, key))
            self.boxes[self.sel] = after
        self._sync_rows()
        self.redraw()

    # ------------------------------------------------------- undo / redo

    def _snapshot(self):
        return copy.deepcopy(self.boxes), self.sel

    def _checkpoint(self, kind=None):
        """Remember the boxes as they are now, before a change."""
        if kind is not None and kind == self._last_edit:
            return
        self._last_edit = kind
        self.undo_stack.append(self._snapshot())
        del self.undo_stack[:-200]
        self.redo_stack.clear()
        self._sync_buttons()

    def _restore(self, state):
        self.boxes, self.sel = copy.deepcopy(state[0]), state[1]
        self._last_edit = None
        self.load_box()
        self.redraw()

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._snapshot())
            self._restore(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._snapshot())
            self._restore(self.redo_stack.pop())

    def _sync_buttons(self):
        if hasattr(self, "undo_btn"):
            self.undo_btn.configure(state="normal" if self.undo_stack else "disabled")
            self.redo_btn.configure(state="normal" if self.redo_stack else "disabled")

    # ---------------------------------------------- copy, paste, duplicate

    def _select(self, i):
        self.sel = i
        self.load_box()
        self.redraw()

    def _add(self, boxes):
        """Add boxes (already placed) and select the last one."""
        self.boxes.extend(boxes)
        self._select(len(self.boxes) - 1)

    def _free_spot(self, r):
        """Where a copy of rect r goes: beside it (below, right, above, left) where
        it's on the ticket and clear of other boxes; else a little down and right."""
        page = self.src[0].rect
        gap = 6
        for dx, dy in ((0, r.height + gap), (r.width + gap, 0), (0, -r.height - gap),
                       (-r.width - gap, 0)):
            cand = r + (dx, dy, dx, dy)
            if page.contains(cand) and not any(cand.intersects(fitz.Rect(b["rect"]))
                                               for b in self.boxes):
                return cand
        return r + (12, 12, 12, 12)

    def duplicate(self):
        if self.sel is None:
            return
        self._checkpoint()
        b = copy.deepcopy(self.boxes[self.sel])
        b["rect"] = [round(x, 2) for x in self._free_spot(fitz.Rect(b["rect"]))]
        self._add([b])

    def copy(self):
        if self.sel is not None:
            _clipboard[:] = [copy.deepcopy(self.boxes[self.sel])]
            self._pastes = 0

    def cut(self):
        if self.sel is not None:
            self.copy()
            self.delete_box()

    def paste(self):
        """Paste the copied box under the mouse (if it's over the ticket), otherwise
        beside where it was copied from."""
        if not _clipboard:
            return
        self._checkpoint()
        b = copy.deepcopy(_clipboard[0])
        r = fitz.Rect(b["rect"])
        px, py = (self.canvas.winfo_pointerx() - self.canvas.winfo_rootx(),
                  self.canvas.winfo_pointery() - self.canvas.winfo_rooty())
        x, y = self._to_page(px, py)
        if (0 <= px < self.canvas.winfo_width() and 0 <= py < self.canvas.winfo_height()
                and self.src[0].rect.contains(fitz.Point(x, y))):
            r = r + (x - (r.x0 + r.x1) / 2, y - (r.y0 + r.y1) / 2) * 2
        else:
            self._pastes += 1
            r = self._free_spot(r) if self._pastes == 1 else r + (12 * self._pastes,) * 4
        b["rect"] = [round(v, 2) for v in r]
        self._add([b])

    def delete_box(self):
        if self.sel is not None:
            self._checkpoint()
            del self.boxes[self.sel]
            self.sel = (len(self.boxes) - 1) if self.boxes else None
            self.load_box()
            self.redraw()

    def nudge(self, dx, dy, step):
        if self.sel is None:
            return
        self._checkpoint(("nudge", self.sel))
        x0, y0, x1, y1 = self.boxes[self.sel]["rect"]
        dx, dy = dx * step, dy * step
        self.boxes[self.sel]["rect"] = [round(v, 2) for v in (x0 + dx, y0 + dy, x1 + dx, y1 + dy)]
        self.redraw()

    def ok(self):
        try:
            s = self.settings(quiet=False)
        except ValueError as e:
            messagebox.showerror("Check the numbering", str(e), parent=self)
            return
        if not s.num_boxes:
            if not messagebox.askyesno("No number boxes", "No number boxes are placed, so "
                                       "nothing will be numbered. Close anyway?", parent=self):
                return
        out = [i + 1 for i, b in enumerate(s.num_boxes) if not self._on_ticket(b)]
        if out and not messagebox.askyesno(
                "Past the edge",
                f"Box {', '.join(map(str, out))} (orange) goes past the edge of the ticket, so "
                f"part of the number will be cut off. Keep it like this?", parent=self):
            return
        self.on_done(s)
        self.destroy()

    # ------------------------------------------------------------ drawing

    def _fit(self):
        page = self.src[0]
        cw, ch = max(self.canvas.winfo_width(), 100), max(self.canvas.winfo_height(), 100)
        z = min((cw - 40) / page.rect.width, (ch - 40) / page.rect.height)
        ox = (cw - page.rect.width * z) / 2
        oy = (ch - page.rect.height * z) / 2
        return z, ox, oy

    def redraw(self):
        if not self.winfo_exists():
            return
        self.cmyk_row.pack_forget() if self.v["colour"].get() != "Custom CMYK" else \
            self.cmyk_row.pack(fill="x", pady=3, before=self.sample)
        s = self.settings()
        a, b = s.num_start, s.num_start + s.num_count - 1
        self.sample.configure(text=f"Numbers: {numbering.number_text(a, s)} to "
                                   f"{numbering.number_text(b, s)}  ({s.num_count:,} tickets)")
        c = self.canvas
        c.delete("all")
        z, ox, oy = self._fit()
        doc = numbering.sample_page(self.src, s, b if self.v["show"].get() == SHOW[1] else a)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        self._img = tk.PhotoImage(data=pix.tobytes("ppm"))
        c.create_rectangle(ox + 3, oy + 3, ox + pix.width + 3, oy + pix.height + 3,
                           fill="#9a9a9a", outline="")
        c.create_image(ox, oy, image=self._img, anchor="nw")
        from .engine import has_bleed, trim_rect
        if has_bleed(self.src[0]):   # where it's cut
            t = trim_rect(self.src[0])
            c.create_rectangle(ox + t.x0 * z, oy + t.y0 * z, ox + t.x1 * z, oy + t.y1 * z,
                               outline="#888", dash=(4, 3))
        for i, box in enumerate(self.boxes):
            x0, y0, x1, y1 = self._box_px(box)
            chosen = i == self.sel
            inside = self._on_ticket(box)
            colour = OUTSIDE if not inside else "#d93025" if chosen else "#3b78d8"
            c.create_rectangle(x0 - 1, y0 - 1, x1 + 1, y1 + 1, outline=colour,
                               width=2 if chosen else 1, dash=() if chosen else (4, 2))
            if chosen:
                for hx, hy in self._handles(box).values():
                    c.create_rectangle(hx - HANDLE, hy - HANDLE, hx + HANDLE, hy + HANDLE,
                                       fill=colour, outline="white")
                self._show_fit(inside, s)
        page = self.src[0].rect
        for axis, v in self._guides:
            if axis == "x":
                c.create_line(ox + v * z, oy - 12, ox + v * z, oy + page.height * z + 12,
                              fill=GUIDE)
            else:
                c.create_line(ox - 12, oy + v * z, ox + page.width * z + 12, oy + v * z,
                              fill=GUIDE)
        drag = self._drag
        if drag and drag["mode"] == "new" and drag.get("now"):
            (x0, y0), (x1, y1) = drag["start"], drag["now"]
            c.create_rectangle(x0, y0, x1, y1, outline="#d93025", dash=(4, 2))

    def _on_ticket(self, box):
        """Is the box inside the cut edge of the ticket?"""
        from .engine import trim_rect
        return _inside(fitz.Rect(box["rect"]), trim_rect(self.src[0]))

    def _show_fit(self, inside, s):
        last = numbering.number_text(s.num_start + s.num_count - 1, s)
        self.fit_note.configure(
            foreground="#555" if inside else OUTSIDE,
            text=(f"The box is sized for the longest number ({last}), so every number fits."
                  if inside else "This box goes past the edge of the ticket: part of the "
                                 "number would be cut off."))

    # ------------------------------------------------------------ mouse

    def _to_page(self, x, y):
        z, ox, oy = self._fit()
        return (x - ox) / z, (y - oy) / z

    def _box_px(self, box):
        z, ox, oy = self._fit()
        r = fitz.Rect(box["rect"])
        return ox + r.x0 * z, oy + r.y0 * z, ox + r.x1 * z, oy + r.y1 * z

    def _handles(self, box):
        """The corner handles (drag one to scale the number) and where they are."""
        x0, y0, x1, y1 = self._box_px(box)
        return {"tl": (x0, y0), "tr": (x1, y0), "bl": (x0, y1), "br": (x1, y1)}

    def _hit(self, x, y):
        """What's under the mouse: ("handle", edges) on the selected box,
        ("box", index), or None."""
        if self.sel is not None:
            for edges, (hx, hy) in self._handles(self.boxes[self.sel]).items():
                if abs(x - hx) <= HANDLE + 2 and abs(y - hy) <= HANDLE + 2:
                    return "handle", edges
        for i in reversed(range(len(self.boxes))):
            x0, y0, x1, y1 = self._box_px(self.boxes[i])
            if x0 <= x <= x1 and y0 <= y <= y1:
                return "box", i
        return None

    def hover(self, e):
        hit = self._hit(e.x, e.y)
        cursor = "" if not hit else CURSORS.get(hit[1], "") if hit[0] == "handle" else "fleur"
        try:
            self.canvas.configure(cursor=cursor)
        except tk.TclError:
            self.canvas.configure(cursor="")

    def press(self, e, copy_it=False):
        self.canvas.focus_set()
        self._last_edit = None
        hit = self._hit(e.x, e.y)
        if hit and hit[0] == "handle" and not copy_it:
            self._checkpoint()
            r = fitz.Rect(self.boxes[self.sel]["rect"])
            corner = {"tl": r.tl, "tr": r.tr, "bl": r.bl, "br": r.br}
            self._drag = {"mode": "scale", "corner": hit[1], "start": (e.x, e.y),
                          "rect": list(r), "size": float(self.boxes[self.sel].get("size", 14)),
                          "fixed": corner[OPPOSITE[hit[1]]], "from": corner[hit[1]]}
            return
        if hit:
            i = self.sel if hit[0] == "handle" else hit[1]
            self._checkpoint()
            if copy_it:   # Alt+drag: drag out a copy, the original stays put
                self.boxes.append(copy.deepcopy(self.boxes[i]))
                i = len(self.boxes) - 1
            self._select(i)
            self._drag = {"mode": "move", "start": (e.x, e.y),
                          "rect": list(self.boxes[i]["rect"]), "copied": copy_it}
            return
        self._drag = {"mode": "new", "start": (e.x, e.y), "now": None}

    def motion(self, e):
        d = self._drag
        if not d:
            return
        z, _, _ = self._fit()
        dx, dy = (e.x - d["start"][0]) / z, (e.y - d["start"][1]) / z
        if d["mode"] == "move":
            x0, y0, x1, y1 = d["rect"]
            r = fitz.Rect(x0 + dx, y0 + dy, x1 + dx, y1 + dy)
            self._guides = []
            if not e.state & 0x0001:   # Shift held: move freely
                r = self._snap(r, z)
            self.boxes[self.sel]["rect"] = list(r)
        elif d["mode"] == "scale":
            self._scale(d, fitz.Point(self._to_page(e.x, e.y)))
        else:
            d["now"] = (e.x, e.y)
        self.redraw()

    def release(self, e):
        d, self._drag = self._drag, None
        self._guides = []
        if not d:
            return
        if d["mode"] in ("move", "scale"):
            box = self.boxes[self.sel]
            box["rect"] = [round(v, 2) for v in box["rect"]]
            if box["rect"] == [round(v, 2) for v in d["rect"]] and not d.get("copied"):
                self.undo_stack.pop()     # a click, nothing changed
                self._sync_buttons()
        elif d["mode"] == "new":
            (sx, sy), now = d["start"], d.get("now")
            if now and abs(now[0] - sx) >= MIN_BOX and abs(now[1] - sy) >= MIN_BOX:
                self._new_box(sx, sy, *now)
            elif self.sel is not None:   # a click on the ticket: nothing selected
                self.sel = None
                self.load_box()
        self.redraw()

    def _snap(self, r, z):
        """
        Snap a box being dragged so its left, centre or right (and top, middle or
        bottom) lines up with the ticket's centre or cut edges, or with another
        box. Shows a guide line for each match.
        """
        from .engine import trim_rect
        t = trim_rect(self.src[0])
        xs = [t.x0, (t.x0 + t.x1) / 2, t.x1]
        ys = [t.y0, (t.y0 + t.y1) / 2, t.y1]
        for i, b in enumerate(self.boxes):
            if i != self.sel:
                o = fitz.Rect(b["rect"])
                xs += [o.x0, (o.x0 + o.x1) / 2, o.x1]
                ys += [o.y0, (o.y0 + o.y1) / 2, o.y1]
        tol = SNAP_PX / z

        def best(mine, targets):
            hits = [(abs(tg - m), tg - m) for m in mine for tg in targets if abs(tg - m) <= tol]
            return min(hits)[1] if hits else 0.0

        dx = best([r.x0, (r.x0 + r.x1) / 2, r.x1], xs)
        dy = best([r.y0, (r.y0 + r.y1) / 2, r.y1], ys)
        r = r + (dx, dy, dx, dy)
        on = lambda v, targets: any(abs(v - tg) < 0.01 for tg in targets)
        self._guides = ([("x", v) for v in (r.x0, (r.x0 + r.x1) / 2, r.x1) if on(v, xs)]
                        + [("y", v) for v in (r.y0, (r.y0 + r.y1) / 2, r.y1) if on(v, ys)])
        return r

    def _scale(self, d, mouse):
        """Corner drag: the number grows or shrinks with the box, the opposite
        corner stays put."""
        fixed, start = d["fixed"], d["from"]
        diag, pull = start - fixed, mouse - fixed
        k = (pull.x * diag.x + pull.y * diag.y) / max(diag.x ** 2 + diag.y ** 2, 1e-6)
        s = self.settings()     # (refits self.boxes: take the box after this)
        b = self.boxes[self.sel]
        b["size"] = round(max(4.0, min(200.0, d["size"] * k)), 1)
        b.update(numbering.fit_box(b, s))
        r = fitz.Rect(b["rect"])
        now = {"tl": r.br, "tr": r.bl, "bl": r.tr, "br": r.tl}[d["corner"]]   # its fixed corner
        shift = fixed - now
        b["rect"] = [round(v, 2) for v in (r.x0 + shift.x, r.y0 + shift.y,
                                           r.x1 + shift.x, r.y1 + shift.y)]
        self._loading = True
        try:
            self.v["size"].set(f"{b['size']:g}")
        finally:
            self._loading = False

    def _new_box(self, sx, sy, ex, ey):
        """A box drawn by dragging. It takes the look (background, border, font
        size, alignment) of the box selected before, so a set of boxes match."""
        a = self._to_page(min(sx, ex), min(sy, ey))
        b = self._to_page(max(sx, ex), max(sy, ey))
        w, h = b[0] - a[0], b[1] - a[1]
        tall = h > w * 1.5      # a narrow upright box: the number reads upward
        like = self.boxes[self.sel] if self.sel is not None else (
            self.boxes[-1] if self.boxes else None)
        if like:
            new = {k: copy.deepcopy(v) for k, v in like.items() if k != "rect"}
            if tall != (like.get("rotate", 0) != 0):
                new["rotate"] = 90 if tall else 0
        else:
            new = {"size": 14, "align": "center", "rotate": 90 if tall else 0}
        new["rect"] = [round(v, 2) for v in (*a, *b)]
        # The number is as big as fits the drawn box's thickness; the box then wraps it.
        s = self.settings()
        edge = numbering.box_size({**new, "size": 0}, s)[1]          # padding + border alone
        per_pt = numbering.box_size({**new, "size": 1}, s)[1] - edge
        new["size"] = round(max(4.0, min(200.0, ((w if tall else h) - edge) / per_pt)), 1)
        self._checkpoint()
        self._add([numbering.fit_box(new, s)])
