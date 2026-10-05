"""
Prestige Impose: the window. Laid out like Fiery Impose's Gangup screen:
preview on the left, settings on the right.

The original PDF is only ever read (into memory), never changed. "Save imposed
PDF" writes next to the original and reveals it in File Explorer / Finder.
Every file opened starts from the default settings; pick a preset after.
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import pymupdf as fitz

from . import __version__, fiery, mypresets, pages, updater
from .engine import (BLEED_IN, PT, SHEET_MARGIN_IN, SHEETS, Settings, delete_preset,
                     describe, finish_rect, has_bleed, load_presets, plan, presets_for_file,
                     pull_in_gutters, render, render_preview, save_preset, settings_for_file,
                     trim_rect)
from .paths import ICON_ICO, IS_MAC, IS_WINDOWS

CUSTOM = "Custom"
LAYOUTS = {"Gangup": "gangup", "Normal": "normal"}
GANGS = {"Repeat": "repeat", "Unique": "unique"}
DUPLEX = {"Off": (False, False), "On": (True, False), "Same both sides": (True, True)}
SCALING = {"Do not scale": "none", "Scale to fit": "fit", "Custom": "custom"}
LAYOUT_STYLES = {"Standard": "standard", "Head to head": "head", "Foot to foot": "foot"}
SLOT_180 = {"None": "none", "Front surface": "front", "Back surface": "back",
            "Front and back surface": "both"}
CROP_MARKS = {"None": "none", "Outside only": "outside",
              "With bleed (stretch edges)": "stretch", "With bleed (enlarge)": "enlarge"}

try:  # drag and drop (optional: the app works without it)
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _BaseTk = TkinterDnD.Tk
except Exception:  # pragma: no cover - missing library or tkdnd failed to load
    DND_FILES, _BaseTk = None, tk.Tk

APP_ID = "PrestigeGraphics.Impose"   # must match the installer and the dev shortcut
UI_FONT = "Segoe UI" if IS_WINDOWS else "Helvetica Neue" if IS_MAC else "TkDefaultFont"

GUTTER_STEP = 0.02   # inches per arrow click

ZOOM_STEP = 1.25     # each zoom in/out click or key press
ZOOM_MIN_PCT = 10    # % of actual size
ZOOM_MAX_PCT = 800
PREVIEW_GAP, PREVIEW_PAD, PREVIEW_LABEL_H = 40, 24, 26
SHEET_GAP = 56       # between sheets in the all-sheets view
PAGES_W = 168        # the Pages panel
THUMB_W, THUMB_H = 112, 132   # largest page thumbnail
THUMB_GAP = 30       # thumbnail + its page number
THUMB_COL_GAP = 22   # between columns of thumbnails
FLAG = "#e07b00"     # a page that isn't the size of the rest
PREVIEW_MIN_W = 520  # the preview keeps at least this when the Pages panel widens

BG = "#c8c8c8"       # preview backdrop, like Fiery's grey
PANEL_W = 430


class App(_BaseTk):
    def __init__(self, path=None):
        try:
            super().__init__()
        except Exception:  # tkdnd couldn't load: carry on without drag and drop
            tk.Tk.__init__(self)
            self.dnd_ok = False
        else:
            self.dnd_ok = DND_FILES is not None and _BaseTk is not tk.Tk
        self.title(f"Prestige Impose {__version__}")
        if IS_WINDOWS and ICON_ICO.is_file():
            self.iconbitmap(default=str(ICON_ICO))
        self.geometry("1280x820")
        self.minsize(1100, 640)

        self.src = None          # the document being imposed (the page list, built)
        self.original = None     # the file as opened (never changed)
        self.original_bytes = None
        self.page_tokens = []    # the page list (see pages.py)
        self.page_sel = []       # selected positions in it
        self.page_undo = []      # earlier page lists, for Undo
        self.page_clip = []      # copied / cut pages
        self._thumbs = {}        # token -> PhotoImage
        self.extras = {}         # key -> bytes of PDFs inserted ("Insert pages from PDF")
        self.extra_docs = {}     # key -> fitz.Document of those
        self._page_drag = None   # drag-to-move in progress
        self.src_path = None     # original path the person picked
        self.update_info = None
        self.plan = None
        self.sheet_index = 0
        self._after = None
        self._images = []        # keep PhotoImages alive
        self._preview_cache = {}  # source pages drawn at preview size
        self.zoom_factor = 1.0    # 1.0 = fit the window; bigger = zoomed in
        self._layout = None       # where the sheets sit on the canvas, for zoom/pan
        self._draw_after = None
        self._applying = False    # settings being set from a preset, not typed
        mypresets.activate()      # this computer's own presets
        self._ui = queue.SimpleQueue()   # work from background threads, run on the window's
        self._sending = 0                # sends to Fiery still going

        self._build()
        self.bind("<Configure>", lambda e: self._schedule(150) if e.widget is self else None)
        self._bind_zoom_keys()
        self._bind_shortcuts()
        if self.dnd_ok:
            try:
                self.drop_target_register(DND_FILES)
                self.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                self.dnd_ok = False
        self.protocol("WM_DELETE_WINDOW", self.ask_close)
        if IS_MAC:  # Finder "Open With" and drag-onto-dock arrive as Apple events
            self.createcommand("::tk::mac::OpenDocument",
                               lambda *paths: paths and self.open_pdf(paths[0]))
            self.createcommand("::tk::mac::Quit", self.ask_close)
        self._poll_ui()
        if updater.should_check():
            threading.Thread(target=self._check_updates, daemon=True).start()
        if path:
            self.after(100, lambda: self.open_pdf(path))
        else:
            self._refresh()

    # ------------------------------------------------------------------ UI

    def _build(self):
        style = ttk.Style(self)
        if IS_WINDOWS and "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Head.TLabel", font=(UI_FONT, 10, "bold"))
        style.configure("Small.TLabel", font=(UI_FONT, 9))
        style.configure("Update.TButton", font=(UI_FONT, 9, "bold"), foreground="#0a5")

        top = ttk.Frame(self, padding=(8, 6))
        top.pack(side="top", fill="x")
        ttk.Button(top, text="Open PDF...", command=self.choose_pdf).pack(side="left")
        self.file_label = ttk.Label(top, text="No file open", style="Small.TLabel")
        self.file_label.pack(side="left", padx=10)
        self.save_btn = ttk.Button(top, text="Save imposed PDF", command=self.save)
        self.save_btn.pack(side="right")
        self.send_btn = ttk.Button(top, text="Send to Fiery...", command=self.send_to_fiery)
        self.send_btn.pack(side="right", padx=(0, 6))
        # Shown only when a newer version is out.
        self.update_btn = ttk.Button(top, text="", style="Update.TButton",
                                     command=self.show_update)

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)

        # Settings panel (right)
        panel = ttk.Frame(body, padding=10, width=PANEL_W)
        panel.pack(side="right", fill="y")
        panel.pack_propagate(False)
        self._build_settings(panel)

        # Pages | preview, with a divider to drag (a wider Pages panel shows
        # its thumbnails in 2, 3... columns).
        split = self.split = ttk.Panedwindow(body, orient="horizontal")
        split.pack(side="left", fill="both", expand=True)
        split.add(self._build_pages(split), weight=0)

        # Preview (left)
        left = ttk.Frame(split)
        split.add(left, weight=1)
        # The divider can't squeeze either side too far.
        split.bind("<B1-Motion>", lambda e: self._clamp_split(), add="+")
        split.bind("<ButtonRelease-1>", lambda e: self._clamp_split(), add="+")
        self.bind("<Configure>", lambda e: self._clamp_split() if e.widget is self else None,
                  add="+")
        view = ttk.Frame(left)
        view.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(view, bg=BG, highlightthickness=0)
        xbar = ttk.Scrollbar(view, orient="horizontal", command=self._xview)
        ybar = ttk.Scrollbar(view, orient="vertical", command=self._yview)
        self.canvas.configure(xscrollcommand=xbar.set, yscrollcommand=ybar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ybar.grid(row=0, column=1, sticky="ns")
        xbar.grid(row=1, column=0, sticky="ew")
        view.rowconfigure(0, weight=1)
        view.columnconfigure(0, weight=1)
        # Drag to pan; wheel scrolls (Shift = sideways); Ctrl/Cmd + wheel zooms at the pointer.
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<MouseWheel>", lambda e: self._wheel(e, "y"))
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self._wheel(e, "x"))
        for mod in ("Control", "Command") if IS_MAC else ("Control",):
            self.canvas.bind(f"<{mod}-MouseWheel>",
                             lambda e: self.zoom(ZOOM_STEP if e.delta > 0 else 1 / ZOOM_STEP,
                                                 at=(e.x, e.y)))
        self.canvas.bind("<Configure>", lambda e: self._schedule_draw(60))

        nav = ttk.Frame(left, padding=4)
        nav.pack(fill="x")
        ttk.Button(nav, text="Fit", width=5, command=self.zoom_fit).pack(side="right")
        ttk.Button(nav, text="+", width=3, command=lambda: self.zoom(ZOOM_STEP)).pack(side="right")
        self.zoom_label = ttk.Label(nav, text="", width=6, anchor="center")
        self.zoom_label.pack(side="right", padx=2)
        ttk.Button(nav, text="\u2212", width=3, command=lambda: self.zoom(1 / ZOOM_STEP)).pack(
            side="right")
        self.prev_btn = ttk.Button(nav, text="< Prev", width=8, command=lambda: self._step(-1))
        self.prev_btn.pack(side="left")
        self.sheet_label = ttk.Label(nav, text="", width=18, anchor="center")
        self.sheet_label.pack(side="left", padx=6)
        self.next_btn = ttk.Button(nav, text="Next >", width=8, command=lambda: self._step(1))
        self.next_btn.pack(side="left")

    def _build_pages(self, parent):
        """Pages panel: every page of the job as a thumbnail. Drag to move; cut,
        copy, paste, duplicate, delete, blanks, other PDFs and more from the
        right-click / Edit menu. Returns the panel's frame."""
        box = ttk.Frame(parent, width=PAGES_W)
        box.pack_propagate(False)
        head = ttk.Frame(box, padding=(8, 6, 4, 4))
        head.pack(fill="x")
        self.pages_label = ttk.Label(head, text="Pages", style="Head.TLabel")
        self.pages_label.pack(side="left")
        self.page_menu = tk.Menu(self, tearoff=False, postcommand=self._page_menu_state)
        ttk.Menubutton(head, text="Edit", menu=self.page_menu, width=5).pack(side="right")
        mod = "Cmd" if IS_MAC else "Ctrl"
        for label, cmd, key in (("Cut", self.page_cut, f"{mod}+X"),
                                ("Copy", self.page_copy, f"{mod}+C"),
                                ("Paste after", lambda: self.page_paste(after=True), f"{mod}+V"),
                                ("Paste before", lambda: self.page_paste(after=False), ""),
                                ("Duplicate", self.page_duplicate, f"{mod}+D"),
                                ("Delete", self.page_delete, "Del"),
                                (None, None, None),
                                ("Move to start", lambda: self.page_move(0), ""),
                                ("Move to end", lambda: self.page_move(None), ""),
                                ("Reverse order", self.page_reverse, ""),
                                (None, None, None),
                                ("Insert blank page after", lambda: self.page_blank(True), ""),
                                ("Insert blank page before", lambda: self.page_blank(False), ""),
                                ("Blank page after every page", self.page_blank_each, ""),
                                ("Insert pages from PDF...", self.page_insert_pdf, ""),
                                (None, None, None),
                                ("Save selected pages as PDF...", self.page_save_pdf, ""),
                                (None, None, None),
                                ("Select all", self.page_select_all, f"{mod}+A"),
                                ("Undo", self.page_undo_last, f"{mod}+Z"),
                                ("Back to the original pages", self.page_reset, "")):
            if label is None:
                self.page_menu.add_separator()
            else:
                self.page_menu.add_command(label=label, command=cmd, accelerator=key)

        wrap = ttk.Frame(box)
        wrap.pack(fill="both", expand=True)
        self.pages_canvas = tk.Canvas(wrap, bg="#e4e4e4", highlightthickness=0, width=PAGES_W - 16)
        bar = ttk.Scrollbar(wrap, orient="vertical", command=self._pages_yview)
        self.pages_canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.pages_canvas.pack(side="left", fill="both", expand=True)
        c = self.pages_canvas
        c.bind("<Configure>", lambda e: self._draw_pages())
        c.bind("<MouseWheel>", lambda e: self._pages_wheel(e))
        c.bind("<ButtonPress-1>", lambda e: self._page_press(e, "one"))
        c.bind("<Control-ButtonPress-1>", lambda e: self._page_press(e, "toggle"))
        c.bind("<Shift-ButtonPress-1>", lambda e: self._page_press(e, "range"))
        c.bind("<B1-Motion>", self._page_motion)
        c.bind("<ButtonRelease-1>", self._page_release)
        if IS_MAC:
            c.bind("<Command-ButtonPress-1>", lambda e: self._page_press(e, "toggle"))
            c.bind("<Button-2>", self._page_context)
            c.bind("<Control-ButtonPress-1>", self._page_context)
        else:
            c.bind("<Button-3>", self._page_context)
        # Keys work when the Pages panel has focus (click in it first), so
        # Ctrl+C in a text box still copies text.
        for m in ("Command",) if IS_MAC else ("Control",):
            for key, fn in (("x", self.page_cut), ("c", self.page_copy),
                            ("v", lambda: self.page_paste(True)), ("d", self.page_duplicate),
                            ("a", self.page_select_all), ("z", self.page_undo_last)):
                c.bind(f"<{m}-{key}>", lambda e, f=fn: (f(), "break")[1])
                c.bind(f"<{m}-{key.upper()}>", lambda e, f=fn: (f(), "break")[1])
        for key in ("Delete", "BackSpace"):
            c.bind(f"<{key}>", lambda e: (self.page_delete(), "break")[1])
        c.bind("<Up>", lambda e: (self._page_arrow(-self._page_cols()), "break")[1])
        c.bind("<Down>", lambda e: (self._page_arrow(self._page_cols()), "break")[1])
        c.bind("<Left>", lambda e: (self._page_arrow(-1), "break")[1])
        c.bind("<Right>", lambda e: (self._page_arrow(1), "break")[1])
        return box

    def _clamp_split(self):
        """Keep the Pages panel at least one column wide and the preview wide
        enough for its buttons."""
        total = self.split.winfo_width()
        if total < 50:
            return
        pos = self.split.sashpos(0)
        good = max(PAGES_W - 20, min(pos, total - PREVIEW_MIN_W))
        if good != pos:
            self.split.sashpos(0, good)

    def _row(self, parent, label, widget_fn, pady=3):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=pady)
        ttk.Label(row, text=label, width=15).pack(side="left")
        w = widget_fn(row)
        w.pack(side="left", fill="x", expand=True)
        return row, w

    def _combo(self, var, values):
        return lambda parent: ttk.Combobox(parent, textvariable=var, values=list(values),
                                           state="readonly", width=22)

    def _build_settings(self, p):
        v = self.vars = {
            "layout": tk.StringVar(value="Normal"),
            "gang": tk.StringVar(value="Repeat"),
            "sheet": tk.StringVar(value="12 x 18"),
            "custom_w": tk.StringVar(value="12"),
            "custom_h": tk.StringVar(value="18"),
            "orientation": tk.StringVar(value="Portrait"),
            "duplex": tk.StringVar(value="Off"),
            "rows": tk.StringVar(value="1"),
            "cols": tk.StringVar(value="1"),
            "gutter_x": tk.StringVar(value="0"),
            "gutter_y": tk.StringVar(value="0"),
            "scaling": tk.StringVar(value="Do not scale"),
            "scale_pct": tk.StringVar(value="100"),
            "turn90": tk.BooleanVar(value=False),
            "layout_style": tk.StringVar(value="Standard"),
            "slot_180": tk.StringVar(value="None"),
            "crop_marks": tk.StringVar(value="None"),
        }

        ttk.Label(p, text="Preset", style="Head.TLabel").pack(anchor="w")
        pr = ttk.Frame(p)
        pr.pack(fill="x", pady=(3, 0))
        self.preset_var = tk.StringVar(value="")
        self.preset_box = ttk.Combobox(pr, textvariable=self.preset_var, state="readonly",
                                       width=24)
        self.preset_box.pack(side="left", fill="x", expand=True)
        self.preset_box.bind("<<ComboboxSelected>>", lambda e: self.apply_preset())
        self.preset_save_btn = ttk.Button(pr, text="Save...", width=7, command=self.save_preset)
        self.preset_save_btn.pack(side="left", padx=(6, 0))
        self.preset_del_btn = ttk.Button(pr, text="Delete", width=7, command=self.delete_preset)
        self.preset_del_btn.pack(side="left", padx=(4, 0))
        self._load_presets()
        # "Suggested: <preset> [Use]" when the opened file matches a preset's file size.
        self.suggest_row = ttk.Frame(p)
        self.suggest_label = ttk.Label(self.suggest_row, text="", style="Small.TLabel",
                                       foreground="#0a5")
        self.suggest_label.pack(side="left")
        self.suggest_btn = ttk.Button(self.suggest_row, text="Use", width=5,
                                      command=self.use_suggestion)
        self.suggest_btn.pack(side="left", padx=(6, 0))
        self.suggest_anchor = ttk.Frame(p)
        self.suggest_anchor.pack(fill="x")
        self._suggested = None

        ttk.Separator(p).pack(fill="x", pady=8)
        ttk.Label(p, text="Settings", style="Head.TLabel").pack(anchor="w", pady=(0, 6))
        self.layout_row, _ = self._row(p, "Layout:", self._combo(v["layout"], LAYOUTS))
        # Gangup-only rows are hidden for Normal, like Fiery (see _sync_widgets).
        self.gang_row, _ = self._row(p, "Gangup type:", self._combo(v["gang"], GANGS))
        self._row(p, "Sheet:", self._combo(v["sheet"], list(SHEETS) + [CUSTOM]))

        self.custom_row = ttk.Frame(p)
        ttk.Label(self.custom_row, text="Custom (in):", width=15).pack(side="left")
        ttk.Entry(self.custom_row, textvariable=v["custom_w"], width=6).pack(side="left")
        ttk.Label(self.custom_row, text=" x ").pack(side="left")
        ttk.Entry(self.custom_row, textvariable=v["custom_h"], width=6).pack(side="left")
        self.custom_anchor = ttk.Frame(p)  # keeps the custom row in place when shown
        self.custom_anchor.pack(fill="x")

        self._row(p, "Duplex:", self._combo(v["duplex"], DUPLEX))
        self._row(p, "Crop marks:", self._combo(v["crop_marks"], CROP_MARKS))

        ttk.Separator(p).pack(fill="x", pady=8)
        ttk.Label(p, text="Layout", style="Head.TLabel").pack(anchor="w")
        oc = ttk.Frame(p)
        oc.pack(fill="x", pady=3)
        ttk.Label(oc, text="Orientation:", width=15).pack(side="left")
        ttk.Combobox(oc, textvariable=v["orientation"], values=["Portrait", "Landscape"],
                     state="readonly", width=13).pack(side="left")
        ttk.Checkbutton(oc, text="Turn 90\u00b0", variable=v["turn90"]).pack(
            side="left", padx=(10, 0))
        self.slot180_row, _ = self._row(p, "180 slot rotation:",
                                        self._combo(v["slot_180"], SLOT_180))

        self.gang_box = ttk.Frame(p)   # gangup only
        self.gang_box.pack(fill="x")
        self._row(self.gang_box, "Layout style:", self._combo(v["layout_style"], LAYOUT_STYLES))
        rc = ttk.Frame(self.gang_box)
        rc.pack(fill="x", pady=3)
        ttk.Label(rc, text="Rows x Columns:", width=15).pack(side="left")
        ttk.Spinbox(rc, from_=1, to=40, textvariable=v["rows"], width=4).pack(side="left")
        ttk.Label(rc, text=" x ").pack(side="left")
        ttk.Spinbox(rc, from_=1, to=40, textvariable=v["cols"], width=4).pack(side="left")

        # Gutters: two spinboxes, a Link toggle spanning both (like Illustrator's
        # chain between width and height), then Apply All / Reset.
        g = ttk.Frame(self.gang_box)
        g.pack(fill="x", pady=3)
        self.gutter_link = tk.BooleanVar(value=False)
        self._gutter_last = {"gutter_x": 0.0, "gutter_y": 0.0}
        self._gutter_quiet = False
        for row, (key, label) in enumerate((("gutter_x", "Gutter, columns:"),
                                            ("gutter_y", "Gutter, rows:"))):
            ttk.Label(g, text=label, width=15).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Spinbox(g, from_=-5, to=5, increment=GUTTER_STEP, textvariable=v[key],
                        width=7).grid(row=row, column=1, sticky="w")
            ttk.Label(g, text=" in").grid(row=row, column=2, sticky="w")
            v[key].trace_add("write", lambda *_, k=key: self._on_gutter(k))
        ttk.Checkbutton(g, text="Link", style="Toolbutton", variable=self.gutter_link,
                        width=4).grid(row=0, column=3, rowspan=2, sticky="ns", padx=(6, 0))
        ttk.Button(g, text="Apply All", width=9, command=self.apply_all_gutters).grid(
            row=0, column=4, padx=(6, 0))
        ttk.Button(g, text="Reset", width=9, command=self.reset_gutters).grid(
            row=1, column=4, padx=(6, 0))

        ttk.Separator(p).pack(fill="x", pady=6)
        sc = ttk.Frame(p)
        sc.pack(fill="x", pady=3)
        ttk.Label(sc, text="Scaling:", width=15).pack(side="left")
        ttk.Combobox(sc, textvariable=v["scaling"], values=list(SCALING), state="readonly",
                     width=13).pack(side="left")
        self.pct_box = ttk.Spinbox(sc, from_=1, to=400, increment=1,
                                   textvariable=v["scale_pct"], width=5)
        self.pct_box.pack(side="left", padx=(8, 0))
        ttk.Label(sc, text=" %").pack(side="left")

        ttk.Separator(p).pack(fill="x", pady=8)
        self.notes = tk.Text(p, height=5, wrap="word", relief="flat", bg=self.cget("bg"),
                             font=(UI_FONT, 9), cursor="arrow")
        self.notes.pack(fill="both", expand=True)
        self.notes.tag_configure("err", foreground="#b00020")
        self.notes.tag_configure("warn", foreground="#8a5a00")
        self.notes.tag_configure("ok", foreground="#1b6e20")

        for var in v.values():
            var.trace_add("write", lambda *_: self._schedule())
        v["crop_marks"].trace_add("write", lambda *_: self._bleed_gutters())
        for key in ("custom_w", "custom_h"):
            v[key].trace_add("write", lambda *_: self._custom_orientation())

    # ------------------------------------------------------------- settings

    def settings(self):
        """Read the panel. Raises ValueError with a readable message on bad input."""
        v = self.vars

        def num(key, label, cast=float):
            try:
                return cast(v[key].get().strip())
            except ValueError:
                raise ValueError(f"{label} must be a number.")

        if v["sheet"].get() == CUSTOM:
            w, h = num("custom_w", "Custom sheet width"), num("custom_h", "Custom sheet height")
            if w <= 0 or h <= 0:
                raise ValueError("Custom sheet size must be more than 0.")
        else:
            w, h = SHEETS[v["sheet"].get()]
        return Settings(
            layout=LAYOUTS[v["layout"].get()],
            gang=GANGS[v["gang"].get()],
            sheet_w=w, sheet_h=h,
            orientation=v["orientation"].get().lower(),
            duplex=DUPLEX[v["duplex"].get()][0],
            back_same=DUPLEX[v["duplex"].get()][1],
            rows=num("rows", "Rows", int), cols=num("cols", "Columns", int),
            gutter_x=num("gutter_x", "Column gutter"), gutter_y=num("gutter_y", "Row gutter"),
            scaling=SCALING[v["scaling"].get()],
            scale_pct=num("scale_pct", "Scale factor"),
            rotate=90 if v["turn90"].get() else 0,
            layout_style=LAYOUT_STYLES[v["layout_style"].get()],
            slot_180=SLOT_180[v["slot_180"].get()],
            crop_marks=CROP_MARKS[v["crop_marks"].get()],
        )

    def _sync_widgets(self):
        v = self.vars
        gangup = v["layout"].get() == "Gangup"
        if gangup and not self.gang_row.winfo_ismapped():
            self.gang_row.pack(fill="x", pady=3, after=self.layout_row)
            self.gang_box.pack(fill="x", after=self.slot180_row)
        elif not gangup:
            self.gang_row.pack_forget()
            self.gang_box.pack_forget()
        self.pct_box.configure(state="normal" if v["scaling"].get() == "Custom" else "disabled")
        if v["sheet"].get() == CUSTOM:
            self.custom_row.pack(in_=self.custom_anchor, fill="x", pady=3)
            self.custom_row.lift(self.custom_anchor)   # in front of its placeholder
        else:
            self.custom_row.pack_forget()

    # --------------------------------------------------------------- presets

    def _load_presets(self, select=None):
        self.presets = load_presets()
        self.preset_box.configure(values=list(self.presets))
        self.preset_var.set(select if select in self.presets else "")

    def apply_preset(self):
        s = self.presets.get(self.preset_var.get())
        if s is not None:
            if self.src:
                s = settings_for_file(self.src, s)
            self._apply_settings(s)
            if hasattr(self, "suggest_row"):
                self.suggest_row.pack_forget()

    def reset_settings(self):
        """Every new file starts from the defaults (Normal), with no preset selected."""
        self.preset_var.set("")
        self._apply_settings(Settings(layout="normal"))

    def _apply_settings(self, s):
        self._applying = True
        try:
            self._apply(s)
        finally:
            self._applying = False

    def _apply(self, s):
        v = self.vars
        sheet = next((n for n, (w, h) in SHEETS.items()
                      if sorted((w, h)) == sorted((s.sheet_w, s.sheet_h))), CUSTOM)
        pick = lambda table, val: next(k for k, x in table.items() if x == val)  # noqa: E731
        v["layout"].set(pick(LAYOUTS, s.layout))
        v["gang"].set(pick(GANGS, s.gang))
        v["sheet"].set(sheet)
        v["custom_w"].set(f"{s.sheet_w:g}")
        v["custom_h"].set(f"{s.sheet_h:g}")
        v["orientation"].set(s.orientation.capitalize())
        v["duplex"].set(pick(DUPLEX, (bool(s.duplex), bool(s.duplex and s.back_same))))
        v["rows"].set(str(s.rows))
        v["cols"].set(str(s.cols))
        self._set_gutter("gutter_x", s.gutter_x)
        self._set_gutter("gutter_y", s.gutter_y)
        v["scaling"].set(pick(SCALING, s.scaling))
        v["scale_pct"].set(f"{s.scale_pct:g}")
        v["turn90"].set(bool(s.rotate % 180))
        v["layout_style"].set(pick(LAYOUT_STYLES, s.layout_style if s.layout_style in
                                   LAYOUT_STYLES.values() else "standard"))
        v["slot_180"].set(pick(SLOT_180, s.slot_180 if s.slot_180 in SLOT_180.values()
                               else "none"))
        v["crop_marks"].set(pick(CROP_MARKS, s.crop_marks if s.crop_marks in CROP_MARKS.values()
                                 else "none"))

    def save_preset(self):
        try:
            s = self.settings()
        except ValueError as e:
            messagebox.showerror("Check the settings", str(e))
            return
        name = simpledialog.askstring("Save preset", "Name this preset "
                                      "(e.g. Illustrator business cards):",
                                      initialvalue=self.preset_var.get(), parent=self)
        name = (name or "").strip()
        if not name:
            return
        if name in self.presets and not messagebox.askyesno(
                "Replace preset?", f"A preset called '{name}' already exists. Replace it?"):
            return
        # Gutters that are the file's pull-in gutters are saved as "pull in", so
        # the preset works for cards with more or less slug around them.
        if self.src:
            g = pull_in_gutters(self.src, s)
            s.pull_in = bool(g) and abs(g[0] - s.gutter_x) < 0.005 and abs(g[1] - s.gutter_y) < 0.005
        try:
            save_preset(name, s, match_size=self._file_size(), match_cut=self._cut_size())
        except OSError as e:
            messagebox.showerror("Couldn't save the preset", str(e), parent=self)
            return
        self._load_presets(select=name)

    def delete_preset(self):
        name = self.preset_var.get()
        if not name:
            return
        if messagebox.askyesno("Delete preset?", f"Delete the preset '{name}'?", parent=self):
            try:
                delete_preset(name)
            except OSError as e:
                messagebox.showerror("Couldn't delete the preset", str(e), parent=self)
            self._load_presets()

    def _file_size(self):
        """(w, h) inches of the open file's first page, or None."""
        if not self.src:
            return None
        r = self.src[0].rect
        return (r.width / PT, r.height / PT)

    def _cut_size(self):
        """(w, h) inches of where the open file's first page is cut, or None."""
        if not self.src:
            return None
        t = trim_rect(self.src[0])
        return (t.width / PT, t.height / PT)

    def _update_suggestion(self):
        names = presets_for_file(self.src) if self.src else []
        names = [n for n in names if n in self.presets]
        self._suggested = names[0] if names else None
        if self._suggested and self.preset_var.get() != self._suggested:
            self.suggest_label.configure(text=f"Suggested for this file: {self._suggested}")
            self.suggest_row.pack(in_=self.suggest_anchor, fill="x", pady=(4, 0))
            self.suggest_row.lift(self.suggest_anchor)
        else:
            self.suggest_row.pack_forget()

    def use_suggestion(self):
        if self._suggested:
            self.preset_var.set(self._suggested)
            self.apply_preset()
            self.suggest_row.pack_forget()

    def _bind_shortcuts(self):
        mods = ("Control", "Command") if IS_MAC else ("Control",)
        for mod in mods:
            # On the main window only (not bind_all): in the Send window,
            # Ctrl+S mustn't save again behind it.
            self.bind(f"<{mod}-o>", lambda e: (self.choose_pdf(), "break")[1])
            self.bind(f"<{mod}-O>", lambda e: (self.choose_pdf(), "break")[1])
            self.bind(f"<{mod}-s>", lambda e: (self.save(), "break")[1])
            self.bind(f"<{mod}-S>", lambda e: (self.save(), "break")[1])
        self.bind("<Prior>", lambda e: self._step(-1))   # Page Up
        self.bind("<Next>", lambda e: self._step(1))     # Page Down

    def _on_drop(self, event):
        paths = [Path(p) for p in self.tk.splitlist(event.data)]
        pdfs = [p for p in paths if p.suffix.lower() == ".pdf"]
        if pdfs:
            self.open_pdf(pdfs[0])
        elif paths:
            messagebox.showinfo("Not a PDF", "Drop a PDF file to impose it.")
        return getattr(event, "action", "copy")

    def apply_all_gutters(self):
        try:
            self._set_gutter("gutter_y", float(self.vars["gutter_x"].get()))
        except ValueError:
            pass

    def reset_gutters(self):
        self._set_gutter("gutter_x", 0.0)
        self._set_gutter("gutter_y", 0.0)

    def _set_gutter(self, key, value):
        """Set a gutter from code (preset, Apply All, Reset) without the link moving the other."""
        self._gutter_quiet = True
        try:
            self.vars[key].set(f"{round(value, 4):g}")
            self._gutter_last[key] = round(value, 4)
        finally:
            self._gutter_quiet = False

    def _on_gutter(self, key):
        """
        A gutter changed. Tidy arrow-click rounding noise, and if Link is on,
        move the other gutter by the same amount (so equal gutters stay equal,
        and different ones keep their difference).
        """
        if self._gutter_quiet:
            return
        try:
            value = float(self.vars[key].get())
        except ValueError:
            return  # mid-typing, e.g. just "-"
        text = self.vars[key].get()
        if "." in text and len(text.split(".")[1]) > 4:  # 0.06000000000000001
            self._set_gutter(key, value)
        delta = value - self._gutter_last[key]
        self._gutter_last[key] = round(value, 4)
        if self.gutter_link.get() and abs(delta) > 1e-9:
            other = "gutter_y" if key == "gutter_x" else "gutter_x"
            try:
                current = float(self.vars[other].get())
            except ValueError:
                current = self._gutter_last[other]
            self._set_gutter(other, current + delta)

    # ----------------------------------------------------------------- files

    def choose_pdf(self):
        path = filedialog.askopenfilename(title="Open a PDF to impose",
                                          filetypes=[("PDF files", "*.pdf")])
        if path:
            self.open_pdf(path)

    def open_pdf(self, path):
        path = Path(path)
        try:
            # Read the whole file into memory: the original is never written to
            # or held open (so OneDrive can keep syncing it).
            raw = path.read_bytes()
            doc = fitz.open(stream=raw, filetype="pdf")
            if doc.page_count == 0:
                raise ValueError("The PDF has no pages.")
        except Exception as e:  # show it, don't crash the window
            messagebox.showerror("Couldn't open", f"{path.name}\n\n{e}")
            return
        if self.src is not None and self.src is not self.original:
            self.src.close()
        if self.original is not None:
            self.original.close()
        self.original, self.original_bytes = doc, raw
        self.src, self.src_path = doc, path
        self.page_tokens = pages.original(doc.page_count)
        self.page_sel, self.page_undo, self.page_clip = [], [], []
        self._thumbs = {}
        self.extras, self.extra_docs = {}, {}
        self.pages_canvas.yview_moveto(0)
        self._preview_cache = {}
        self.sheet_index = 0
        self.zoom_factor = 1.0
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)
        self.reset_settings()

        self._file_note()
        self._update_suggestion()
        self._draw_pages()
        self._refresh()

    def _file_note(self):
        doc, path = self.src, self.src_path
        fin = finish_rect(doc[0], "crop")
        note = f'{path.name}  |  {doc.page_count} page(s), {fin.width / PT:.3f}" x {fin.height / PT:.3f}"'
        if has_bleed(doc[0]):
            trim = finish_rect(doc[0], "trim")
            note += f'  |  cuts to {trim.width / PT:.3f}" x {trim.height / PT:.3f}" (bleed built in)'
        if not pages.is_original(self.page_tokens, self.original.page_count):
            note += "  |  pages edited (the original file is unchanged)"
        self.file_label.configure(text=note)

    # ---------------------------------------------------------------- pages

    def _set_pages(self, tokens, sel):
        """A new page list: keep the old one for Undo, rebuild what's imposed."""
        self.page_undo.append((self.page_tokens, self.page_sel))
        del self.page_undo[:-50]
        self._use_pages(tokens, sel)

    def _use_pages(self, tokens, sel):
        old = self.src
        self.page_tokens, self.page_sel = list(tokens), list(sel)
        if pages.is_original(self.page_tokens, self.original.page_count):
            self.src = self.original
        else:
            self.src = pages.build(self.original_bytes, self.page_tokens, self.extras)
        if old is not None and old is not self.original and old is not self.src:
            old.close()
        self._preview_cache = {}
        self._file_note()
        self._draw_pages()
        self._refresh()

    def _page_menu_state(self):
        has_file = bool(self.src)
        sel = bool(self.page_sel) and has_file
        states = {"Cut": sel, "Copy": sel, "Paste after": bool(self.page_clip) and has_file,
                  "Paste before": bool(self.page_clip) and has_file, "Duplicate": sel,
                  "Insert blank page after": has_file, "Insert blank page before": has_file,
                  "Delete": sel, "Select all": has_file, "Undo": bool(self.page_undo),
                  "Move to start": sel, "Move to end": sel, "Reverse order": has_file,
                  "Blank page after every page": has_file,
                  "Insert pages from PDF...": has_file,
                  "Save selected pages as PDF...": has_file,
                  "Back to the original pages": has_file and not pages.is_original(
                      self.page_tokens, self.original.page_count)}
        for label, on in states.items():
            self.page_menu.entryconfigure(label, state="normal" if on else "disabled")

    def _page_context(self, e):
        i = self._page_at(e.x, e.y)
        if i is not None and i not in self.page_sel:
            self.page_sel = [i]
            self._draw_pages()
        self.pages_canvas.focus_set()
        self._page_menu_state()
        self.page_menu.tk_popup(e.x_root, e.y_root)
        return "break"

    def page_copy(self):
        if self.src and self.page_sel:
            self.page_clip = pages.copy(self.page_tokens, self.page_sel)

    def page_cut(self):
        if self.src and self.page_sel:
            clip = pages.copy(self.page_tokens, self.page_sel)
            if self.page_delete():
                self.page_clip = clip

    def page_paste(self, after=True):
        if not self.src or not self.page_clip:
            return
        sel = sorted(self.page_sel)
        at = (sel[-1] + 1 if after else sel[0]) if sel else len(self.page_tokens)
        self._set_pages(*pages.insert(self.page_tokens, at, self.page_clip))

    def page_delete(self):
        if not self.src or not self.page_sel:
            return False
        try:
            self._set_pages(*pages.delete(self.page_tokens, self.page_sel))
        except ValueError as e:
            messagebox.showinfo("Can't delete", str(e), parent=self)
            return False
        return True

    def page_duplicate(self):
        if self.src and self.page_sel:
            self._set_pages(*pages.duplicate(self.page_tokens, self.page_sel))

    def page_blank(self, after=True):
        if not self.src:
            return
        sel = sorted(self.page_sel) or [len(self.page_tokens) - 1]
        ref = self.page_tokens[sel[-1] if after else sel[0]]
        at = sel[-1] + 1 if after else sel[0]
        self._set_pages(*pages.insert(self.page_tokens, at, [self._blank_for(ref)]))

    def _blank_for(self, token):
        return pages.blank_like(self.original, token, self.extra_docs)

    def page_move(self, to):
        """Move the selection to the start (0) or the end (None)."""
        if self.src and self.page_sel:
            to = len(self.page_tokens) if to is None else to
            self._set_pages(*pages.move(self.page_tokens, self.page_sel, to))

    def page_reverse(self):
        """Reverse the selected pages, or all of them if one or none is selected."""
        if self.src:
            self._set_pages(*pages.reverse(self.page_tokens, self.page_sel))

    def page_blank_each(self):
        """A blank page after every page: one-sided pages, printed duplex."""
        if self.src:
            self._set_pages(*pages.blank_after_each(self.page_tokens, self._blank_for))

    def page_insert_pdf(self):
        """Put the pages of another PDF in after the selection (or at the end)."""
        if not self.src:
            return
        path = filedialog.askopenfilename(parent=self, title="Insert pages from a PDF",
                                          initialdir=str(self.src_path.parent),
                                          filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        try:
            raw = Path(path).read_bytes()
            doc = fitz.open(stream=raw, filetype="pdf")
            if doc.page_count == 0:
                raise ValueError("The PDF has no pages.")
        except Exception as e:
            messagebox.showerror("Couldn't open", f"{Path(path).name}\n\n{e}", parent=self)
            return
        key = max(self.extras, default=0) + 1
        self.extras[key], self.extra_docs[key] = raw, doc
        sel = sorted(self.page_sel)
        at = sel[-1] + 1 if sel else len(self.page_tokens)
        self._set_pages(*pages.insert(self.page_tokens, at,
                                      [("ext", key, i) for i in range(doc.page_count)]))

    def page_save_pdf(self):
        """Save the selected pages (or all of them) as their own PDF."""
        if not self.src:
            return
        picked = sorted(self.page_sel) or list(range(len(self.page_tokens)))
        nums = (f"page {picked[0] + 1}" if len(picked) == 1
                else f"pages {picked[0] + 1}-{picked[-1] + 1}"
                if picked == list(range(picked[0], picked[-1] + 1)) else "pages")
        path = filedialog.asksaveasfilename(
            parent=self, title="Save pages as a PDF", defaultextension=".pdf",
            initialdir=str(self.src_path.parent),
            initialfile=f"{self.src_path.stem} - {nums}.pdf", filetypes=[("PDF files", "*.pdf")])
        if not path:
            return
        try:
            doc = pages.build(self.original_bytes, [self.page_tokens[i] for i in picked],
                              self.extras)
            doc.save(path, garbage=4, deflate=True)
            doc.close()
        except Exception as e:
            messagebox.showerror("Save failed", str(e), parent=self)
            return
        reveal(path)

    def page_select_all(self):
        if self.src:
            self.page_sel = list(range(len(self.page_tokens)))
            self._draw_pages()

    def page_undo_last(self):
        if self.src and self.page_undo:
            self._use_pages(*self.page_undo.pop())

    def page_reset(self):
        if self.src and not pages.is_original(self.page_tokens, self.original.page_count):
            self._set_pages(pages.original(self.original.page_count), [])

    # thumbnails

    def _page_cols(self):
        cw = max(self.pages_canvas.winfo_width(), 60)
        return max(1, int((cw - 12 + THUMB_COL_GAP) // (THUMB_W + THUMB_COL_GAP)))

    def _thumb_layout(self):
        """[(x0, y0, w, h)] of each page's thumbnail in the panel, and the total
        height. As many columns as fit; each row as tall as its tallest page."""
        cols = self._page_cols()
        cw = max(self.pages_canvas.winfo_width(), 60)
        left = (cw - (cols * THUMB_W + (cols - 1) * THUMB_COL_GAP)) / 2
        out, y = [], 10
        sizes = [pages.size_of(t, self.original, self.extra_docs) for t in self.page_tokens]
        for row in range(0, len(sizes), cols):
            row_h = 0
            for j, (pw, ph) in enumerate(sizes[row:row + cols]):
                k = min(THUMB_W / pw, THUMB_H / ph)
                w, h = pw * k, ph * k
                cx = left + j * (THUMB_W + THUMB_COL_GAP) + THUMB_W / 2
                out.append((cx - w / 2, y, w, h))
                row_h = max(row_h, h)
            y += row_h + THUMB_GAP
        return out, y

    def _thumb(self, token, w, h):
        key = (token, round(w))
        img = self._thumbs.get(key)
        if img is None and token[0] != "blank":
            page = pages.page_of(token, self.original, self.extra_docs)
            z = w / page.rect.width
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            img = tk.PhotoImage(data=pix.tobytes("ppm"))
            self._thumbs[key] = img
        return img

    def _draw_pages(self):
        c = self.pages_canvas
        c.delete("all")
        if not self.src:
            self.pages_label.configure(text="Pages")
            return
        boxes, total = self._thumb_layout()
        sizes = [pages.size_of(t, self.original, self.extra_docs) for t in self.page_tokens]
        odd = set(pages.odd_sizes(sizes))
        self.pages_label.configure(text=f"Pages ({len(self.page_tokens)})")
        c.configure(scrollregion=(0, 0, max(c.winfo_width(), 60), total))
        top, bottom = c.canvasy(0), c.canvasy(c.winfo_height())
        sel = set(self.page_sel)
        for i, (t, (x, y, w, h)) in enumerate(zip(self.page_tokens, boxes)):
            if i in sel:
                c.create_rectangle(x - 5, y - 5, x + w + 5, y + h + 20, fill="#cfe0f7",
                                   outline="#3b78d8", width=2)
            c.create_rectangle(x + 2, y + 2, x + w + 2, y + h + 2, fill="#a8a8a8", outline="")
            c.create_rectangle(x, y, x + w, y + h, fill="white", outline="#bbb")
            if y + h >= top and y <= bottom:   # only render what's on screen
                img = self._thumb(t, w, h)
                if img is not None:
                    c.create_image(x, y, image=img, anchor="nw")
            if i in odd:   # not the size of the rest
                c.create_rectangle(x - 1, y - 1, x + w + 1, y + h + 1, outline=FLAG, width=3)
                pw, ph = (v / PT for v in sizes[i])
                c.create_text(x + w / 2, y + h + 10, text=f'{i + 1}   {pw:g}" x {ph:g}"',
                              font=(UI_FONT, 9, "bold"), fill=FLAG)
            else:
                c.create_text(x + w / 2, y + h + 10, text=str(i + 1), font=(UI_FONT, 9))
        drag = self._page_drag
        if drag and drag.get("at") is not None:   # where a dragged page would land
            at = drag["at"]
            if at < len(boxes):
                x, y, w, h = boxes[at]
                lx = x - THUMB_COL_GAP / 2 + 2
            else:
                x, y, w, h = boxes[-1]
                lx = x + w + THUMB_COL_GAP / 2 - 2
            c.create_line(lx, y - 6, lx, y + h + 6, fill="#3b78d8", width=4)

    def _pages_yview(self, *args):
        self.pages_canvas.yview(*args)
        self._draw_pages()

    def _pages_wheel(self, e):
        self.pages_canvas.yview_scroll(-1 if e.delta > 0 else 1, "units")
        self._draw_pages()

    def _page_at(self, x, y):
        """The page under a point in the panel, or None."""
        cx, cy = self.pages_canvas.canvasx(x), self.pages_canvas.canvasy(y)
        boxes, _ = self._thumb_layout()
        for i, (bx, by, bw, bh) in enumerate(boxes):
            if bx - 8 <= cx <= bx + bw + 8 and by - 6 <= cy <= by + bh + THUMB_GAP - 6:
                return i
        return None

    def _drop_at(self, x, y):
        """Where a dragged page would go: the gap nearest the pointer (0..len)."""
        cx, cy = self.pages_canvas.canvasx(x), self.pages_canvas.canvasy(y)
        boxes, _ = self._thumb_layout()
        best, at = None, len(boxes)
        for i, (bx, by, bw, bh) in enumerate(boxes):
            if by - THUMB_GAP / 2 <= cy <= by + bh + THUMB_GAP / 2:
                for pos, gx in ((i, bx), (i + 1, bx + bw)):
                    d = abs(cx - gx)
                    if best is None or d < best:
                        best, at = d, pos
        return at

    def _page_press(self, e, how):
        self.pages_canvas.focus_set()
        if not self.src:
            return "break"
        i = self._page_at(e.x, e.y)
        self._page_drag = {"start": (e.x, e.y), "i": i, "how": how, "moved": False, "at": None}
        if i is None:
            self.page_sel = []
        elif how == "toggle":
            self.page_sel = sorted(set(self.page_sel) ^ {i})
        elif how == "range" and self.page_sel:
            a = self.page_sel[-1]
            self.page_sel = sorted(set(self.page_sel) | set(range(min(a, i), max(a, i) + 1)))
        elif i not in self.page_sel:
            self.page_sel = [i]
        self._draw_pages()
        return "break"

    def _page_motion(self, e):
        drag = self._page_drag
        if not drag or drag["i"] is None or drag["how"] != "one" or not self.page_sel:
            return
        sx, sy = drag["start"]
        if not drag["moved"] and abs(e.x - sx) < 6 and abs(e.y - sy) < 6:
            return
        drag["moved"] = True
        c = self.pages_canvas
        if e.y < 20:             # near the top or bottom edge: scroll
            c.yview_scroll(-1, "units")
        elif e.y > c.winfo_height() - 20:
            c.yview_scroll(1, "units")
        drag["at"] = self._drop_at(e.x, e.y)
        self._draw_pages()

    def _page_release(self, e):
        drag, self._page_drag = self._page_drag, None
        if not drag or not self.src:
            return
        if drag["moved"] and drag["at"] is not None:
            self._set_pages(*pages.move(self.page_tokens, self.page_sel, drag["at"]))
            return
        i = drag["i"]
        if i is not None and drag["how"] == "one":
            self.page_sel = [i]     # a plain click on one of several selected
            self._draw_pages()
            self._show_page(i)
        elif i is not None:
            self._show_page(i)

    def _page_arrow(self, d):
        if not self.src:
            return
        i = (self.page_sel[-1] + d) if self.page_sel else 0
        i = max(0, min(len(self.page_tokens) - 1, i))
        self.page_sel = [i]
        boxes, total = self._thumb_layout()
        y = boxes[i][1]
        c = self.pages_canvas
        if y < c.canvasy(0) or y + boxes[i][3] > c.canvasy(c.winfo_height()):
            c.yview_moveto(max(0.0, (y - 10) / total))
        self._draw_pages()
        self._show_page(i)

    def _show_page(self, i):
        """Scroll the preview to the sheet this page prints on."""
        if not self.plan:
            return
        for k, (front, back) in enumerate(self.plan.sides):
            if any(pl.pno == i for pl in (front or []) + (back or [])):
                self.show_sheet(k)
                return

    def save(self):
        """
        Save next to the file that was opened, then reveal it in File Explorer
        or Finder. Clicking Save is the go-ahead for this write (the folder may
        be OneDrive, which syncs).
        """
        if not self.src or not self.plan or self.plan.errors:
            return
        dest = self._write_imposed()
        if dest:
            reveal(dest)
            self._notes([("ok", f"Saved: {dest.name}\nin {dest.parent}")])

    def _imposed_path(self, name=None):
        """Next to the original: "<name> - imposed 12x18 7x3.pdf". The name is
        the job name when sending, else the original's."""
        s = self.plan.settings
        w, h = s.sheet_size()
        stem = "".join("-" if c in '\\/:*?"<>|' else c for c in (name or "")).strip(" .")
        stem = stem or self.src_path.stem
        return self.src_path.parent / f"{stem} - imposed {w:g}x{h:g} {s.rows}x{s.cols}.pdf"

    def _write_imposed(self, ask_replace=True, name=None, parent=None):
        """Write the imposed PDF next to the original. Returns its path, or None."""
        dest = self._imposed_path(name)
        name = dest.name
        if ask_replace and dest.exists() and not messagebox.askyesno(
                "Replace?", f"{name} already exists in\n{dest.parent}\n\nReplace it?",
                parent=parent or self):
            return None
        part = dest.with_name(dest.name + ".part")
        try:
            doc = render(self.src, self.plan)
            doc.save(part, garbage=4, deflate=True)
            doc.close()
            os.replace(part, dest)  # a half-written file never takes the real name
        except Exception as e:
            part.unlink(missing_ok=True)
            messagebox.showerror("Save failed", f"{name}\n\n{e}", parent=parent or self)
            return None
        return dest

    # ---------------------------------------------------------- send to Fiery

    def send_to_fiery(self):
        """
        Pick a press, paper, quantity, tray and colour; save the imposed PDF
        next to the original and send it to that press's Held queue. Clicking
        Send is the go-ahead (nothing prints: it waits in Held).
        """
        if not self.src or not self.plan or self.plan.errors:
            return
        plan_ = self.plan
        presses, papers = fiery.load_config()
        win = tk.Toplevel(self)
        win.title("Send to Fiery")
        win.transient(self)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=14)
        f.pack(fill="both", expand=True)

        press_var = tk.StringVar(value=presses[0].name)
        paper_var = tk.StringVar(value=papers[0].name)
        name_var = tk.StringVar(value=self.src_path.stem)
        qty_var = tk.StringVar(value=str(plan_.per_sheet if plan_.settings.gang == "repeat"
                                         and plan_.settings.layout == "gangup" else 1))
        tray_var = tk.StringVar(value="Auto")
        colour_var = tk.StringVar(value="Colour")
        repeat = plan_.settings.layout == "gangup" and plan_.settings.gang == "repeat"

        def row(r, label, widget):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=4, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="we", pady=4)

        row(0, "Press:", ttk.Combobox(f, textvariable=press_var, state="readonly", width=44,
                                      values=[p.name for p in presses]))
        paper_box = ttk.Combobox(f, textvariable=paper_var, state="readonly", width=44)
        row(1, "Paper:", paper_box)
        row(2, "Job name:", ttk.Entry(f, textvariable=name_var, width=46))
        qf = ttk.Frame(f)
        ttk.Entry(qf, textvariable=qty_var, width=8).pack(side="left")
        ttk.Label(qf, text=" pieces" if repeat else " sets").pack(side="left")
        row(3, "Quantity:", qf)
        sheets_lbl = ttk.Label(f, text="", style="Small.TLabel")
        sheets_lbl.grid(row=4, column=1, sticky="w")
        row(5, "Tray:", ttk.Combobox(f, textvariable=tray_var, state="readonly", width=12,
                                     values=list(fiery.TRAYS)))
        row(6, "Colour:", ttk.Combobox(f, textvariable=colour_var, state="readonly", width=12,
                                       values=list(fiery.COLOURS)))
        status = ttk.Label(f, text="", style="Small.TLabel", wraplength=420)
        status.grid(row=8, column=0, columnspan=2, sticky="w", pady=(6, 0))
        btns = ttk.Frame(f)
        btns.grid(row=9, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        send_btn = ttk.Button(btns, text="Send to Held")
        send_btn.pack(side="right", padx=(0, 6))

        def press():
            return next(p for p in presses if p.name == press_var.get())

        def refresh(*_):
            # Only papers set up on this press.
            names = [pp.name for pp in papers if pp.queue_for(press())]
            paper_box.configure(values=names)
            if paper_var.get() not in names:
                paper_var.set(names[0])
            try:
                _, label = fiery.copies_for(plan_, int(qty_var.get()))
                sheets_lbl.configure(text="= " + label, foreground="")
                send_btn.configure(state="normal")
            except ValueError:
                sheets_lbl.configure(text="Type a whole number.", foreground="#b00")
                send_btn.configure(state="disabled")

        for v in (press_var, qty_var):
            v.trace_add("write", refresh)
        refresh()

        def do_send():
            pr = press()
            paper = next(pp for pp in papers if pp.name == paper_var.get())
            copies, label = fiery.copies_for(plan_, int(qty_var.get()))
            job = name_var.get().strip() or self.src_path.stem
            dest = self._write_imposed(name=job, parent=win)
            if not dest:
                return
            send_btn.configure(state="disabled")
            status.configure(text=f"Sending to {pr.name}...", foreground="")
            self._sending += 1
            pdf = dest.read_bytes()
            args = dict(press=pr, queue=paper.queue_for(pr), pdf=pdf, job_name=job,
                        copies=copies, sides=fiery.sides_for(plan_), sheet_pt=plan_.sheet,
                        tray=fiery.TRAYS[tray_var.get()], colour=fiery.COLOURS[colour_var.get()])

            def work():
                try:
                    job_id = fiery.send(**args)
                    self._call_soon(lambda: done(pr, job, job_id, label, dest))
                except fiery.SendError as e:
                    msg = str(e)
                    self._call_soon(lambda: failed(msg))

            threading.Thread(target=work, daemon=True).start()

        def done(pr, job, job_id, label, dest):
            self._sending -= 1
            if win.winfo_exists():
                win.destroy()
            jid = f" as job {job_id}" if job_id else ""
            text = (f"Sent to {pr.name} Held queue{jid}: {job}, {label}.\n"
                    f"Saved: {dest.name} in {dest.parent}")
            self._notes([("ok", text)])
            messagebox.showinfo("Sent to Fiery", text, parent=self)

        def failed(msg):
            self._sending -= 1
            if win.winfo_exists():
                status.configure(text=msg, foreground="#b00")
                send_btn.configure(state="normal")

        send_btn.configure(command=do_send)
        win.bind("<Escape>", lambda e: win.destroy())
        self._centre(win)
        win.grab_set()

    # -------------------------------------------------------------- updates

    def _check_updates(self):
        info = updater.check()  # background thread: network only, no Tk calls
        if info:
            self._call_soon(lambda: self._offer_update(info))

    def _offer_update(self, info):
        self.update_info = info
        self.update_btn.configure(text=f"Update available ({info['version']})")
        self.update_btn.pack(side="right", padx=8)

    def show_update(self):
        info = self.update_info
        if not info:
            return
        win = tk.Toplevel(self)
        win.title("Update available")
        win.transient(self)
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"Prestige Impose {info['version']} is available",
                  style="Head.TLabel").pack(anchor="w")
        ttk.Label(frm, text=f"You have {__version__}.", style="Small.TLabel").pack(anchor="w")
        ttk.Label(frm, text="What's new", style="Head.TLabel").pack(anchor="w", pady=(12, 4))
        notes = tk.Text(frm, width=64, height=12, wrap="word", font=(UI_FONT, 10),
                        relief="solid", borderwidth=1, padx=8, pady=6)
        notes.insert("1.0", info["notes"])
        notes.configure(state="disabled")
        notes.pack(fill="both")
        status = ttk.Label(frm, text="", style="Small.TLabel")
        status.pack(anchor="w", pady=(8, 0))
        bar = ttk.Progressbar(frm, maximum=1.0, length=420)
        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(12, 0))
        later = ttk.Button(btns, text="Later", command=win.destroy)
        later.pack(side="right")
        now = ttk.Button(btns, text="Update now")
        now.pack(side="right", padx=(0, 8))

        def progress(f):
            self._call_soon(lambda: bar.configure(value=f) if bar.winfo_exists() else None)

        def work():
            try:
                path = updater.download(info, progress)
            except Exception as e:
                self._call_soon(lambda: failed(e))
                return
            self._call_soon(lambda: finish(path))

        def failed(e):
            status.configure(text=f"Couldn't update: {e}")
            now.configure(state="normal")
            later.configure(state="normal")

        def finish(path):
            status.configure(text="Installing. Prestige Impose will reopen in a moment.")
            try:
                updater.install_and_restart(path)
            except Exception as e:
                failed(e)
                return
            self.after(600, self.destroy)  # quit so the files can be replaced

        def start():
            now.configure(state="disabled")
            later.configure(state="disabled")
            status.configure(text="Downloading...")
            bar.pack(anchor="w", pady=(4, 0), before=btns)
            threading.Thread(target=work, daemon=True).start()

        now.configure(command=start)
        self._centre(win)
        win.grab_set()

    def _call_soon(self, fn):
        """From a background thread: run fn on the window's own thread (Tk
        mustn't be touched from other threads)."""
        self._ui.put(fn)

    def _poll_ui(self):
        while True:
            try:
                fn = self._ui.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except tk.TclError:   # its window was closed meanwhile
                pass
        self.after(80, self._poll_ui)

    def _centre(self, win):
        """Put a dialog in the middle of the app window (not the screen corner)."""
        win.withdraw()
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 3
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
        win.deiconify()

    def ask_close(self):
        """
        Closing with a file open asks first, with Send to Fiery as the obvious
        next step (closing out of habit before sending was easy to do).
        """
        if self._sending:
            messagebox.showinfo("Still sending", "A job is still on its way to the Fiery. "
                                "Close once it's sent (a message says so).", parent=self)
            return
        if not self.src:
            self.destroy()
            return
        win = tk.Toplevel(self)
        win.title("Close Prestige Impose?")
        win.transient(self)
        win.resizable(False, False)
        f = ttk.Frame(win, padding=16)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="Are you sure you would like to close this?",
                  style="Head.TLabel").pack(anchor="w")
        ttk.Label(f, text=self.src_path.name, style="Small.TLabel").pack(anchor="w", pady=(2, 0))
        btns = ttk.Frame(f)
        btns.pack(anchor="e", pady=(14, 0))

        def send():
            win.destroy()
            self.send_to_fiery()

        can_send = bool(self.plan and not self.plan.errors)
        ttk.Button(btns, text="Cancel", command=win.destroy).pack(side="right")
        ttk.Button(btns, text="Close", command=self.destroy).pack(side="right", padx=(0, 6))
        first = ttk.Button(btns, text="Send to Fiery...", command=send,
                           state="normal" if can_send else "disabled")
        first.pack(side="right", padx=(0, 6))
        win.bind("<Escape>", lambda e: win.destroy())
        self._centre(win)
        win.grab_set()
        (first if can_send else btns.winfo_children()[0]).focus_set()

    # ------------------------------------------------------------ actions

    def _custom_orientation(self):
        """A custom size typed wide (19 x 13) means landscape, tall means portrait."""
        if self._applying:
            return
        try:
            w, h = float(self.vars["custom_w"].get()), float(self.vars["custom_h"].get())
        except ValueError:
            return
        if w != h:
            self.vars["orientation"].set("Landscape" if w > h else "Portrait")

    def _bleed_gutters(self):
        """Crop marks with bleed need the pieces 0.25" apart; open them up to that."""
        if CROP_MARKS.get(self.vars["crop_marks"].get()) not in ("stretch", "enlarge"):
            return
        for key in ("gutter_x", "gutter_y"):
            try:
                g = float(self.vars[key].get())
            except ValueError:
                g = 0.0
            if g < 2 * BLEED_IN:
                self._set_gutter(key, 2 * BLEED_IN)

    def _step(self, d):
        if self.plan:
            self.show_sheet(self.sheet_index + d)

    def show_sheet(self, k):
        """Scroll so sheet k (front and back) is at the top of the preview."""
        lay = self._layout
        if not lay:
            return
        k = max(0, min(lay["count"] - 1, k))
        self.sheet_index = k
        ox, oy = self._unit_origin(k)
        rw, rh = lay["region"]
        self.canvas.xview_moveto(max(0.0, (ox - PREVIEW_PAD) / rw))
        self.canvas.yview_moveto(max(0.0, (oy - PREVIEW_PAD) / rh))
        self._draw_preview()

    # --------------------------------------------------------------- preview

    def _schedule(self, ms=40):  # short: arrow clicks feel live, rapid ones still merge
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(ms, self._refresh)

    def _notes(self, lines):
        self.notes.configure(state="normal")
        self.notes.delete("1.0", "end")
        for tag, text in lines:
            self.notes.insert("end", text + "\n\n", tag)
        self.notes.configure(state="disabled")

    def _refresh(self):
        self._after = None
        self._sync_widgets()
        self.canvas.delete("all")
        self._images.clear()
        cw, ch = max(self.canvas.winfo_width(), 200), max(self.canvas.winfo_height(), 200)

        if not self.src:
            self._layout = None
            self.zoom_label.configure(text="")
            self.canvas.configure(scrollregion=(0, 0, cw, ch))
            self.canvas.create_text(cw / 2, ch / 2, text="Open a PDF to start",
                                    font=(UI_FONT, 14), fill="#444")
            self._set_nav(0)
            self.save_btn.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            self._notes([])
            return

        try:
            s = self.settings()
        except ValueError as e:
            self._notes([("err", str(e))])
            self.save_btn.configure(state="disabled")
            self.send_btn.configure(state="disabled")
            return

        self.plan = p = plan(self.src, s)
        self.sheet_index = min(self.sheet_index, max(0, p.sheet_count - 1))

        lines = [("", describe(p, self.src.page_count))]
        lines += [("err", "ERROR: " + e) for e in p.errors]
        lines += [("warn", "Check: " + w) for w in p.warnings]
        if not p.errors and not p.warnings:
            lines.append(("ok", "Ready. Nothing to check."))
        self._notes(lines)
        self.save_btn.configure(state="disabled" if p.errors else "normal")
        self.send_btn.configure(state="disabled" if p.errors else "normal")
        self._set_nav(p.sheet_count)

        self._notes_lines = lines
        self._draw_preview()

    # ------------------------------------------------------------ zoom / pan

    def _bind_zoom_keys(self):
        """Ctrl + / Ctrl - zoom toward the mouse (Cmd on a Mac); Ctrl 0 fits."""
        mods = ("Control", "Command") if IS_MAC else ("Control",)
        for mod in mods:
            for key in ("plus", "equal", "KP_Add"):
                self.bind(f"<{mod}-{key}>", lambda e: self._zoom_key(ZOOM_STEP))
            for key in ("minus", "underscore", "KP_Subtract"):
                self.bind(f"<{mod}-{key}>", lambda e: self._zoom_key(1 / ZOOM_STEP))
            for key in ("0", "KP_0"):
                self.bind(f"<{mod}-{key}>", lambda e: self.zoom_fit())

    def _zoom_key(self, mult):
        # Zoom toward the mouse if it's over the preview, else the middle.
        px, py = self.winfo_pointerxy()
        x, y = px - self.canvas.winfo_rootx(), py - self.canvas.winfo_rooty()
        inside = 0 <= x < self.canvas.winfo_width() and 0 <= y < self.canvas.winfo_height()
        self.zoom(mult, at=(x, y) if inside else None)
        return "break"

    def _fit_zoom(self, n, sw, sh):
        cw, ch = max(self.canvas.winfo_width(), 200), max(self.canvas.winfo_height(), 200)
        g, pad, lab = PREVIEW_GAP, PREVIEW_PAD, PREVIEW_LABEL_H
        return max(min((cw - 2 * pad - g * (n - 1)) / (n * sw), (ch - 2 * pad - lab) / sh), 0.02)

    def _pct(self, zpx):
        """Screen pixels per point -> % of actual size."""
        return zpx * 72 / self.winfo_fpixels("1i") * 100

    def zoom(self, mult, at=None):
        lay = self._layout
        if not lay:
            return
        # Clamp to 10%..800% of actual size.
        fit = lay["fit"]
        lo = ZOOM_MIN_PCT / self._pct(fit)
        hi = ZOOM_MAX_PCT / self._pct(fit)
        new = min(max(self.zoom_factor * mult, lo), hi)
        if abs(new - self.zoom_factor) < 1e-9:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        mx, my = at if at else (cw / 2, ch / 2)
        # The sheet point under the pointer, so it stays under the pointer.
        self.zoom_factor = new
        self._draw_preview(anchor=(*self._point_at(mx, my), mx, my))

    def _point_at(self, mx, my):
        """(sheet, side, (x, y) points on that side) under a view point."""
        lay = self._layout
        cx, cy = self.canvas.canvasx(mx), self.canvas.canvasy(my)
        uw, uh = lay["unit"]
        col = min(max(int((cx - lay["x0"]) // (uw + SHEET_GAP)), 0), lay["cols"] - 1)
        row = max(int((cy - lay["y0"]) // (uh + SHEET_GAP)), 0)
        k = min(row * lay["cols"] + col, lay["count"] - 1)
        ox, oy = self._unit_origin(k)
        step = lay["w_px"] + PREVIEW_GAP
        i = min(max(int((cx - ox) // step), 0), lay["n"] - 1)
        z = lay["zpx"]
        return k, i, ((cx - ox - i * step) / z, (cy - oy) / z)

    def _unit_origin(self, k, lay=None):
        """Canvas top-left of sheet k (its front; the back sits to its right)."""
        lay = lay or self._layout
        uw, uh = lay["unit"]
        return (lay["x0"] + (k % lay["cols"]) * (uw + SHEET_GAP),
                lay["y0"] + (k // lay["cols"]) * (uh + SHEET_GAP))

    def zoom_fit(self):
        """One sheet (front and back) fills the view; the current one."""
        self.zoom_factor = 1.0
        self._draw_preview()
        self.show_sheet(self.sheet_index)
        return "break"

    def _xview(self, *args):
        self.canvas.xview(*args)
        self._schedule_draw()

    def _yview(self, *args):
        self.canvas.yview(*args)
        self._schedule_draw()

    def _wheel(self, e, axis):
        steps = -1 if e.delta > 0 else 1
        (self.canvas.xview_scroll if axis == "x" else self.canvas.yview_scroll)(steps * 3, "units")
        self._schedule_draw()

    def _drag(self, e):
        self.canvas.scan_dragto(e.x, e.y, gain=1)

    def _schedule_draw(self, ms=30):
        if self._draw_after:
            self.after_cancel(self._draw_after)
        self._draw_after = self.after(ms, self._draw_preview)

    def _draw_preview(self, anchor=None):
        """
        Draw every sheet (front and back side by side) in a grid that scrolls,
        like Fiery: at Fit one sheet fills the view, zoom out and more fit
        across. Only the sheets on screen are rendered, so a long job costs no
        more than a short one. `anchor` keeps a sheet point under the pointer
        while zooming.
        """
        self._draw_after = None
        p = self.plan
        if not self.src or not p or not p.sides:
            return
        self.canvas.delete("all")
        self._images.clear()
        cw, ch = max(self.canvas.winfo_width(), 200), max(self.canvas.winfo_height(), 200)
        count = p.sheet_count
        n = 2 if any(b is not None for _, b in p.sides) else 1
        labels = ["Front", "Back"][:n]
        sw, sh = p.sheet
        g, pad, lab = PREVIEW_GAP, PREVIEW_PAD, PREVIEW_LABEL_H
        fit = self._fit_zoom(n, sw, sh)
        zpx = fit * self.zoom_factor
        w_px, h_px = sw * zpx, sh * zpx
        uw, uh = n * w_px + (n - 1) * g, h_px + lab
        cols = max(1, min(count, int((cw - 2 * pad + SHEET_GAP) // (uw + SHEET_GAP))))
        rows = -(-count // cols)
        grid_w = cols * uw + (cols - 1) * SHEET_GAP
        grid_h = rows * uh + (rows - 1) * SHEET_GAP
        region_w, region_h = max(cw, grid_w + 2 * pad), max(ch, grid_h + 2 * pad)
        x0 = (region_w - grid_w) / 2
        y0 = (region_h - grid_h) / 2
        self.canvas.configure(scrollregion=(0, 0, region_w, region_h))
        lay = self._layout = {"fit": fit, "zpx": zpx, "w_px": w_px, "x0": x0, "y0": y0,
                              "n": n, "cols": cols, "count": count, "unit": (uw, uh),
                              "region": (region_w, region_h)}
        self.zoom_label.configure(text=f"{self._pct(zpx):.0f}%")

        if anchor:  # put the anchored sheet point back under the pointer
            k, i, (ux, uy), mx, my = anchor
            ox, oy = self._unit_origin(k, lay)
            ax = ox + i * (w_px + g) + ux * zpx
            ay = oy + uy * zpx
            self.canvas.xview_moveto(max(0.0, (ax - mx) / region_w))
            self.canvas.yview_moveto(max(0.0, (ay - my) / region_h))

        vx0, vy0 = self.canvas.canvasx(0), self.canvas.canvasy(0)
        if len(self._preview_cache) > 120:  # many zoom levels seen
            self._preview_cache.clear()
        mg = SHEET_MARGIN_IN * PT * zpx
        seen = []   # sheets on screen: (k, mostly in view)
        for k in range(count):
            ux0, uy0 = self._unit_origin(k, lay)
            on_screen = (ux0 < vx0 + cw and ux0 + uw > vx0 and uy0 < vy0 + ch
                         and uy0 + uh > vy0)
            sides = [e for e in p.sides[k] if e is not None]
            views = []
            for i in range(len(sides)):
                ox = ux0 + i * (w_px + g)
                views.append(fitz.IRect(int(vx0 - ox) - 2, int(vy0 - uy0) - 2,
                                        int(vx0 + cw - ox) + 3, int(vy0 + ch - uy0) + 3))
            pixmaps = [None] * len(sides)
            if on_screen:
                seen.append((k, uy0 + uh / 2 >= vy0))
                try:
                    pixmaps = render_preview(self.src, p, k, zpx, self._preview_cache, views)
                except Exception as e:  # show it in the panel, keep the window alive
                    self._notes(getattr(self, "_notes_lines", [])
                                + [("err", f"Preview failed: {e}")])
                    return
            for i, label in enumerate(labels[:len(sides)]):
                ox = ux0 + i * (w_px + g)
                self.canvas.create_rectangle(ox + 3, uy0 + 3, ox + w_px + 3, uy0 + h_px + 3,
                                             fill="#9a9a9a", outline="")
                self.canvas.create_rectangle(ox, uy0, ox + w_px, uy0 + h_px, fill="white",
                                             outline="")
                pix = pixmaps[i]
                if pix is not None:
                    img = tk.PhotoImage(data=pix.tobytes("ppm"))  # uncompressed: fastest into Tk
                    self._images.append(img)
                    self.canvas.create_image(ox + pix.x, uy0 + pix.y, image=img, anchor="nw")
                # The 0.1" margin Fiery leaves blank, as a faint dashed line.
                self.canvas.create_rectangle(ox + mg, uy0 + mg, ox + w_px - mg,
                                             uy0 + h_px - mg, outline="#9ab", dash=(3, 3))
                self.canvas.create_text(ox + w_px / 2, uy0 + h_px + 14,
                                        text=f"Sheet {k + 1} - {label}", font=(UI_FONT, 10))
        # "Sheet X of N": the first sheet that's mostly in view.
        if seen:
            self.sheet_index = next((k for k, mostly in seen if mostly), seen[0][0])
        self._set_nav(count)

    def _set_nav(self, count):
        if count:
            self.sheet_label.configure(text=f"Sheet {self.sheet_index + 1} of {count}")
        else:
            self.sheet_label.configure(text="")
        self.prev_btn.configure(state="normal" if count and self.sheet_index > 0 else "disabled")
        self.next_btn.configure(
            state="normal" if count and self.sheet_index < count - 1 else "disabled")


def reveal(path):
    """Show a file selected in File Explorer or Finder. Opening it is the person's call."""
    if IS_WINDOWS:
        subprocess.Popen(f'explorer /select,"{path}"')
    elif IS_MAC:
        subprocess.Popen(["open", "-R", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(Path(path).parent)])


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if IS_WINDOWS:
        # Its own app on the taskbar (not "Python"), grouped under the pin.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except (AttributeError, OSError):
            pass
    path = next((a for a in argv if not a.startswith("-")), None)
    App(path).mainloop()


if __name__ == "__main__":
    main()
