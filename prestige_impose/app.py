"""
Prestige Impose: the window. Laid out like Fiery Impose's Gangup screen:
preview on the left, settings on the right.

The original PDF is only ever read (into memory), never changed. "Save imposed
PDF" writes next to the original and reveals it in File Explorer / Finder.
Every file opened starts from the default settings; pick a preset after.
"""

import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import pymupdf as fitz

from . import __version__, updater
from .engine import (PT, SHEET_MARGIN_IN, SHEETS, Settings, delete_preset, describe,
                     finish_rect, has_bleed, load_presets, most_that_fit, plan, render,
                     render_preview, save_preset)
from .paths import CAN_EDIT_PRESETS, ICON_ICO, IS_MAC, IS_WINDOWS

CUSTOM = "Custom"
LAYOUTS = {"Gangup": "gangup", "Normal": "normal"}
GANGS = {"Repeat": "repeat", "Unique": "unique"}
FINISHES = {"Based on Crop Box": "crop", "Based on Trim Box": "trim"}
DUPLEX = {"Off": False, "On": True}
SCALING = {"Do not scale": "none", "Scale to fit": "fit", "Custom": "custom"}

APP_ID = "PrestigeGraphics.Impose"   # must match the installer and the dev shortcut
UI_FONT = "Segoe UI" if IS_WINDOWS else "Helvetica Neue" if IS_MAC else "TkDefaultFont"

GUTTER_STEP = 0.02   # inches per arrow click

BG = "#c8c8c8"       # preview backdrop, like Fiery's grey
PANEL_W = 430


class App(tk.Tk):
    def __init__(self, path=None):
        super().__init__()
        self.title(f"Prestige Impose {__version__}")
        if IS_WINDOWS and ICON_ICO.is_file():
            self.iconbitmap(default=str(ICON_ICO))
        self.geometry("1280x820")
        self.minsize(980, 640)

        self.src = None          # open fitz.Document (read into memory)
        self.src_path = None     # original path the person picked
        self.update_info = None
        self.plan = None
        self.sheet_index = 0
        self._after = None
        self._images = []        # keep PhotoImages alive
        self._preview_cache = {}  # source pages drawn at preview size

        self._build()
        self.bind("<Configure>", lambda e: self._schedule(150) if e.widget is self else None)
        if IS_MAC:  # Finder "Open With" and drag-onto-dock arrive as Apple events
            self.createcommand("::tk::mac::OpenDocument",
                               lambda *paths: paths and self.open_pdf(paths[0]))
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

        # Preview (left)
        left = ttk.Frame(body)
        left.pack(side="left", fill="both", expand=True)
        self.canvas = tk.Canvas(left, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        nav = ttk.Frame(left, padding=4)
        nav.pack(fill="x")
        self.prev_btn = ttk.Button(nav, text="< Prev", width=8, command=lambda: self._step(-1))
        self.prev_btn.pack(side="left")
        self.sheet_label = ttk.Label(nav, text="", width=18, anchor="center")
        self.sheet_label.pack(side="left", padx=6)
        self.next_btn = ttk.Button(nav, text="Next >", width=8, command=lambda: self._step(1))
        self.next_btn.pack(side="left")

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
            "layout": tk.StringVar(value="Gangup"),
            "gang": tk.StringVar(value="Repeat"),
            "finish": tk.StringVar(value="Based on Crop Box"),
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
        }

        ttk.Label(p, text="Preset", style="Head.TLabel").pack(anchor="w")
        pr = ttk.Frame(p)
        pr.pack(fill="x", pady=(3, 0))
        self.preset_var = tk.StringVar(value="")
        self.preset_box = ttk.Combobox(pr, textvariable=self.preset_var, state="readonly",
                                       width=24)
        self.preset_box.pack(side="left", fill="x", expand=True)
        self.preset_box.bind("<<ComboboxSelected>>", lambda e: self.apply_preset())
        if CAN_EDIT_PRESETS:  # development copy only; staff get the shared list
            ttk.Button(pr, text="Save...", width=7, command=self.save_preset).pack(
                side="left", padx=(6, 0))
            ttk.Button(pr, text="Delete", width=7, command=self.delete_preset).pack(
                side="left", padx=(4, 0))
        self._load_presets()

        ttk.Separator(p).pack(fill="x", pady=8)
        ttk.Label(p, text="Settings", style="Head.TLabel").pack(anchor="w", pady=(0, 6))
        self._row(p, "Layout:", self._combo(v["layout"], LAYOUTS))
        _, self.gang_box = self._row(p, "Gangup type:", self._combo(v["gang"], GANGS))
        self._row(p, "Finish Size:", self._combo(v["finish"], FINISHES))
        self._row(p, "Sheet:", self._combo(v["sheet"], list(SHEETS) + [CUSTOM]))

        self.custom_row = ttk.Frame(p)
        ttk.Label(self.custom_row, text="Custom (in):", width=15).pack(side="left")
        ttk.Entry(self.custom_row, textvariable=v["custom_w"], width=6).pack(side="left")
        ttk.Label(self.custom_row, text=" x ").pack(side="left")
        ttk.Entry(self.custom_row, textvariable=v["custom_h"], width=6).pack(side="left")
        self.custom_anchor = ttk.Frame(p)  # keeps the custom row in place when shown
        self.custom_anchor.pack(fill="x")

        self._row(p, "Duplex:", self._combo(v["duplex"], DUPLEX))

        ttk.Separator(p).pack(fill="x", pady=8)
        ttk.Label(p, text="Layout", style="Head.TLabel").pack(anchor="w")
        self._row(p, "Orientation:", self._combo(v["orientation"], ["Portrait", "Landscape"]))

        rc = ttk.Frame(p)
        rc.pack(fill="x", pady=3)
        ttk.Label(rc, text="Rows x Columns:", width=15).pack(side="left")
        ttk.Spinbox(rc, from_=1, to=40, textvariable=v["rows"], width=4).pack(side="left")
        ttk.Label(rc, text=" x ").pack(side="left")
        ttk.Spinbox(rc, from_=1, to=40, textvariable=v["cols"], width=4).pack(side="left")
        ttk.Button(rc, text="Fit most", command=self.fit_most).pack(side="left", padx=6)
        self.fit_hint = ttk.Label(p, text="", style="Small.TLabel", foreground="#555")
        self.fit_hint.pack(anchor="w", padx=(0, 0))

        # Gutters: two spinboxes, a Link toggle spanning both (like Illustrator's
        # chain between width and height), then Apply All / Reset.
        g = ttk.Frame(p)
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

        ttk.Separator(p).pack(fill="x", pady=8)
        ttk.Label(p, text="Scale", style="Head.TLabel").pack(anchor="w")
        self._row(p, "Scaling:", self._combo(v["scaling"], SCALING))
        sc = ttk.Frame(p)
        sc.pack(fill="x", pady=3)
        ttk.Label(sc, text="Scale Factor:", width=15).pack(side="left")
        self.pct_box = ttk.Spinbox(sc, from_=1, to=400, increment=1,
                                   textvariable=v["scale_pct"], width=6)
        self.pct_box.pack(side="left")
        ttk.Label(sc, text=" %").pack(side="left")

        ttk.Separator(p).pack(fill="x", pady=8)
        self.notes = tk.Text(p, height=14, wrap="word", relief="flat", bg=self.cget("bg"),
                             font=(UI_FONT, 9), cursor="arrow")
        self.notes.pack(fill="both", expand=True)
        self.notes.tag_configure("err", foreground="#b00020")
        self.notes.tag_configure("warn", foreground="#8a5a00")
        self.notes.tag_configure("ok", foreground="#1b6e20")

        for var in v.values():
            var.trace_add("write", lambda *_: self._schedule())

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
            finish=FINISHES[v["finish"].get()],
            sheet_w=w, sheet_h=h,
            orientation=v["orientation"].get().lower(),
            duplex=DUPLEX[v["duplex"].get()],
            rows=num("rows", "Rows", int), cols=num("cols", "Columns", int),
            gutter_x=num("gutter_x", "Column gutter"), gutter_y=num("gutter_y", "Row gutter"),
            scaling=SCALING[v["scaling"].get()],
            scale_pct=num("scale_pct", "Scale factor"),
        )

    def _sync_widgets(self):
        v = self.vars
        self.gang_box.configure(state="readonly" if v["layout"].get() == "Gangup" else "disabled")
        self.pct_box.configure(state="normal" if v["scaling"].get() == "Custom" else "disabled")
        if v["sheet"].get() == CUSTOM:
            self.custom_row.pack(in_=self.custom_anchor, fill="x", pady=3)
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
            self._apply_settings(s)

    def reset_settings(self):
        """Every new file starts from the defaults, with no preset selected."""
        self.preset_var.set("")
        self._apply_settings(Settings())

    def _apply_settings(self, s):
        v = self.vars
        sheet = next((n for n, (w, h) in SHEETS.items()
                      if sorted((w, h)) == sorted((s.sheet_w, s.sheet_h))), CUSTOM)
        pick = lambda table, val: next(k for k, x in table.items() if x == val)  # noqa: E731
        v["layout"].set(pick(LAYOUTS, s.layout))
        v["gang"].set(pick(GANGS, s.gang))
        v["finish"].set(pick(FINISHES, s.finish))
        v["sheet"].set(sheet)
        v["custom_w"].set(f"{s.sheet_w:g}")
        v["custom_h"].set(f"{s.sheet_h:g}")
        v["orientation"].set(s.orientation.capitalize())
        v["duplex"].set(pick(DUPLEX, s.duplex))
        v["rows"].set(str(s.rows))
        v["cols"].set(str(s.cols))
        self._set_gutter("gutter_x", s.gutter_x)
        self._set_gutter("gutter_y", s.gutter_y)
        v["scaling"].set(pick(SCALING, s.scaling))
        v["scale_pct"].set(f"{s.scale_pct:g}")

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
        save_preset(name, s)
        self._load_presets(select=name)

    def delete_preset(self):
        name = self.preset_var.get()
        if not name:
            return
        if messagebox.askyesno("Delete preset?", f"Delete the preset '{name}'?"):
            delete_preset(name)
            self._load_presets()

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
            doc = fitz.open(stream=path.read_bytes(), filetype="pdf")
            if doc.page_count == 0:
                raise ValueError("The PDF has no pages.")
        except Exception as e:  # show it, don't crash the window
            messagebox.showerror("Couldn't open", f"{path.name}\n\n{e}")
            return
        if self.src is not None:
            self.src.close()
        self.src, self.src_path = doc, path
        self._preview_cache = {}
        self.sheet_index = 0
        self.reset_settings()

        fin = finish_rect(doc[0], "crop")
        note = f'{path.name}  |  {doc.page_count} page(s), {fin.width / PT:.3f}" x {fin.height / PT:.3f}"'
        if has_bleed(doc[0]):
            trim = finish_rect(doc[0], "trim")
            note += f'  |  trim box {trim.width / PT:.3f}" x {trim.height / PT:.3f}" (bleed built in)'
        self.file_label.configure(text=note)
        self._refresh()

    def save(self):
        """
        Save next to the file that was opened, then reveal it in File Explorer
        or Finder. Clicking Save is the go-ahead for this write (the folder may
        be OneDrive, which syncs).
        """
        if not self.src or not self.plan or self.plan.errors:
            return
        s = self.plan.settings
        w, h = s.sheet_size()
        name = f"{self.src_path.stem} - imposed {w:g}x{h:g} {s.rows}x{s.cols}.pdf"
        dest = self.src_path.parent / name
        if dest.exists() and not messagebox.askyesno(
                "Replace?", f"{name} already exists in\n{dest.parent}\n\nReplace it?"):
            return
        part = dest.with_name(dest.name + ".part")
        try:
            doc = render(self.src, self.plan)
            doc.save(part, garbage=4, deflate=True)
            doc.close()
            os.replace(part, dest)  # a half-written file never takes the real name
        except Exception as e:
            part.unlink(missing_ok=True)
            messagebox.showerror("Save failed", f"{name}\n\n{e}")
            return
        reveal(dest)
        self._notes([("ok", f"Saved: {name}\nin {dest.parent}")])

    # -------------------------------------------------------------- updates

    def _check_updates(self):
        info = updater.check()  # background thread: network only, no Tk calls
        if info:
            self.after(0, lambda: self._offer_update(info))

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
            self.after(0, lambda: bar.configure(value=f))

        def work():
            try:
                path = updater.download(info, progress)
            except Exception as e:
                self.after(0, lambda: failed(e))
                return
            self.after(0, lambda: finish(path))

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
        win.grab_set()

    # ------------------------------------------------------------ actions

    def fit_most(self):
        if not self.src:
            return
        try:
            s = self.settings()
        except ValueError as e:
            messagebox.showerror("Check the settings", str(e))
            return
        fin = finish_rect(self.src[0], s.finish)
        k = s.scale_pct / 100 if s.scaling == "custom" else 1.0
        r, c = most_that_fit(s, fin.width, fin.height, k)
        if r and c:
            self.vars["rows"].set(str(r))
            self.vars["cols"].set(str(c))
        else:
            messagebox.showinfo("Doesn't fit", "Not even one piece fits on this sheet.")

    def _step(self, d):
        if self.plan:
            self.sheet_index = max(0, min(self.plan.sheet_count - 1, self.sheet_index + d))
            self._refresh()

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
            self.canvas.create_text(cw / 2, ch / 2, text="Open a PDF to start",
                                    font=(UI_FONT, 14), fill="#444")
            self._set_nav(0)
            self.save_btn.configure(state="disabled")
            self._notes([])
            return

        try:
            s = self.settings()
        except ValueError as e:
            self._notes([("err", str(e))])
            self.save_btn.configure(state="disabled")
            return

        self.plan = p = plan(self.src, s)
        self.sheet_index = min(self.sheet_index, max(0, p.sheet_count - 1))

        # Hint: how many fit, both orientations.
        fin = finish_rect(self.src[0], s.finish)
        k = s.scale_pct / 100 if s.scaling == "custom" else 1.0
        hints = []
        for o in ("portrait", "landscape"):
            s2 = self.settings()
            s2.orientation = o
            r, c = most_that_fit(s2, fin.width, fin.height, k)
            hints.append(f"{o}: {r} x {c} = {r * c}")
        self.fit_hint.configure(text="Most that fit  -  " + ",  ".join(hints))

        lines = [("", describe(p, self.src.page_count))]
        lines += [("err", "ERROR: " + e) for e in p.errors]
        lines += [("warn", "Check: " + w) for w in p.warnings]
        if not p.errors and not p.warnings:
            lines.append(("ok", "Ready. Nothing to check."))
        self._notes(lines)
        self.save_btn.configure(state="disabled" if p.errors else "normal")
        self._set_nav(p.sheet_count)

        if not p.sides:
            return
        n = sum(1 for side in p.sides[self.sheet_index] if side is not None)
        labels = ["Front", "Back"] if n == 2 else ["Front"]
        sw, sh = p.sheet
        gap, pad, label_h = 40, 24, 26
        zoom = min((cw - 2 * pad - gap * (n - 1)) / (n * sw), (ch - 2 * pad - label_h) / sh)
        zoom = max(zoom, 0.05)
        if len(self._preview_cache) > 40:  # many window sizes / scales seen
            self._preview_cache.clear()
        try:
            pixmaps = render_preview(self.src, p, self.sheet_index, zoom, self._preview_cache)
        except Exception as e:  # show it in the panel, keep the window alive
            self._notes(lines + [("err", f"Preview failed: {e}")])
            self.save_btn.configure(state="disabled")
            return
        w_px, h_px = pixmaps[0].width, pixmaps[0].height
        x = (cw - (n * w_px + (n - 1) * gap)) / 2
        y = (ch - label_h - h_px) / 2
        for pix, label in zip(pixmaps, labels):
            img = tk.PhotoImage(data=pix.tobytes("ppm"))  # uncompressed: fastest into Tk
            self._images.append(img)
            self.canvas.create_rectangle(x + 3, y + 3, x + w_px + 3, y + h_px + 3,
                                         fill="#9a9a9a", outline="")
            self.canvas.create_image(x, y, image=img, anchor="nw")
            # The 0.1" margin Fiery leaves blank, as a faint dashed line.
            mg = SHEET_MARGIN_IN * PT * zoom
            self.canvas.create_rectangle(x + mg, y + mg, x + w_px - mg, y + h_px - mg,
                                         outline="#9ab", dash=(3, 3))
            self.canvas.create_text(x + w_px / 2, y + h_px + 14,
                                    text=f"Sheet {self.sheet_index + 1} - {label}",
                                    font=(UI_FONT, 10))
            x += w_px + gap

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
