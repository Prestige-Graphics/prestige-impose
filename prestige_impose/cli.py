"""
Command-line imposition, for scripts and for the production agent. Same engine
and presets as the window.

    python -m prestige_impose.cli "<file.pdf>" --preset "Illustrator Business Cards 12x18"
    python -m prestige_impose.cli "<file.pdf>" --preset "..." --rows 8       # preset, one change
    python -m prestige_impose.cli "<file.pdf>" --duplex on --rows 7 --cols 3 --gutter -0.6
    python -m prestige_impose.cli "<file.pdf>" --fit-most --out-dir .tmp/out   # pulls in, tries turning
    python -m prestige_impose.cli "<file.pdf>" --pull-in --rows 7 --cols 3     # pull in, keep crop marks
    python -m prestige_impose.cli "<file.pdf>" --rotate 90 --head-to-head --marks between
    python -m prestige_impose.cli --list-presets

Anything given on the command line overrides the preset. The output goes to
--out-dir (default: the current folder); the input file is only read.
"""

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import pymupdf as fitz

from .engine import (PT, SHEETS, Settings, best_fit, describe, load_presets, plan,
                     pull_in_gutters, render, settings_for_file)


def parse_sheet(text):
    for name, size in SHEETS.items():
        if text.replace(" ", "").lower() == name.split("(")[0].replace(" ", "").lower():
            return size
    try:
        w, h = (float(v) for v in text.lower().split("x"))
        return w, h
    except ValueError:
        raise SystemExit(f"Sheet size '{text}' not understood. Use e.g. 12x18 or 13x19.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="prestige_impose.cli",
                                 description="Impose a PDF onto a press sheet.")
    ap.add_argument("pdf", nargs="?")
    ap.add_argument("--preset", help="a saved preset name; other options override it")
    ap.add_argument("--list-presets", action="store_true")
    ap.add_argument("--layout", choices=["gangup", "normal"])
    ap.add_argument("--gang", choices=["repeat", "unique"])
    ap.add_argument("--finish", choices=["crop", "trim"],
                    help="crop: the whole page fills a slot. trim: the trim box does")
    ap.add_argument("--sheet", help="e.g. 12x18 (default), 13x19")
    ap.add_argument("--orientation", choices=["portrait", "landscape"])
    ap.add_argument("--duplex", choices=["off", "on"])
    ap.add_argument("--rows", type=int)
    ap.add_argument("--cols", type=int)
    ap.add_argument("--fit-most", action="store_true",
                    help="most pieces that fit: pulls in (keeping the file's crop marks) and tries turning")
    ap.add_argument("--pull-in", action="store_true",
                    help="pull in until only a little of the file's crop marks shows "
                         "(or the cut lines meet, if it has none)")
    ap.add_argument("--rotate", type=int, choices=[0, 90], help="turn every piece 90 degrees")
    ap.add_argument("--head-to-head", action="store_true", help="turn every other row upside down")
    ap.add_argument("--gutter", type=float, help="inches, both directions (negative = overlap)")
    ap.add_argument("--gutter-x", type=float, help="inches between columns")
    ap.add_argument("--gutter-y", type=float, help="inches between rows")
    ap.add_argument("--scale", help="none, fit, or a percentage like 95")
    ap.add_argument("--marks", nargs="?", const="outside", choices=["none", "outside", "between"],
                    help="crop marks: outside the layout, or also between pieces (off by default)")
    ap.add_argument("--out-dir", default=".", help="folder for the imposed PDF")
    a = ap.parse_args(argv)

    presets = load_presets()
    if a.list_presets:
        for name, p in presets.items():
            print(f"{name}: {p}")
        if not presets:
            print("No presets saved yet.")
        return 0
    if not a.pdf:
        ap.error("give a PDF")

    src_path = Path(a.pdf)
    if not src_path.is_file():
        raise SystemExit(f"Not a file: {src_path}")
    if src_path.suffix.lower() != ".pdf":
        raise SystemExit(f"This handles PDFs. Got {src_path.suffix or 'no extension'}.")

    if a.preset:
        if a.preset not in presets:
            raise SystemExit(f"No preset called '{a.preset}'. Saved: {', '.join(presets) or 'none'}")
        s = replace(presets[a.preset])
    else:
        s = Settings()
    for key in ("layout", "gang", "finish", "orientation", "rows", "cols", "rotate"):
        if getattr(a, key) is not None:
            setattr(s, key, getattr(a, key))
    if a.sheet:
        s.sheet_w, s.sheet_h = parse_sheet(a.sheet)
    if a.duplex:
        s.duplex = a.duplex == "on"
    if a.gutter is not None:
        s.gutter_x = s.gutter_y = a.gutter
    if a.gutter_x is not None:
        s.gutter_x = a.gutter_x
    if a.gutter_y is not None:
        s.gutter_y = a.gutter_y
    if a.scale == "fit":
        s.scaling = "fit"
    elif a.scale == "none":
        s.scaling = "none"
    elif a.scale:
        s.scaling, s.scale_pct = "custom", float(a.scale.rstrip("%"))
    if a.head_to_head:
        s.head_to_head = True
    if a.marks:
        s.crop_marks = a.marks

    src = fitz.open(stream=src_path.read_bytes(), filetype="pdf")
    if s.pull_in and a.gutter is None and a.gutter_x is None and a.gutter_y is None:
        s = settings_for_file(src, s)
    if a.pull_in:
        g = pull_in_gutters(src, s)
        if g is None:
            raise SystemExit("No cut line inside the page to pull in to (no trim box or crop marks).")
        s.gutter_x, s.gutter_y = g
    if a.fit_most:
        best = best_fit(src, s)
        if not best:
            raise SystemExit("Not even one piece fits on this sheet.")
        s.rows, s.cols, s.rotate, s.gutter_x, s.gutter_y = best

    p = plan(src, s)
    print(describe(p, len(src)))
    for w in p.warnings:
        print(f"  WARNING: {w}")
    if p.errors:
        for e in p.errors:
            print(f"  ERROR: {e}")
        return 1

    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = s.sheet_size()
    out_path = out_dir / f"{src_path.stem} - imposed {w:g}x{h:g} {s.rows}x{s.cols}.pdf"
    doc = render(src, p)
    doc.save(out_path, garbage=4, deflate=True)
    doc.close()

    with fitz.open(out_path) as check:
        pages, size = len(check), check[0].rect
    print(f"Written: {out_path}")
    print(f'  {pages} page(s), {size.width / PT:g}" x {size.height / PT:g}", '
          f"{out_path.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
