"""
Self-test for a built app: `Prestige Impose --selftest`. The release build runs
it on every platform before publishing, so a broken build (missing PDF library,
missing Tcl/Tk, presets not bundled) never reaches staff.

Exit code 0 = passed. The windowed app has no console, so details go to the
file named by --selftest-log if given.
"""

import hashlib
import sys
import traceback


def _checks():
    import pymupdf as fitz

    from . import __version__
    from .engine import Settings, load_presets, plan, render

    yield f"version {__version__}"

    import tkinter
    tkinter.Tcl().eval("info patchlevel")  # Tcl runtime bundled and loads
    yield f"tkinter {tkinter.TkVersion}"

    import os
    import platform
    import tkinterdnd2
    tkdnd = os.path.join(os.path.dirname(tkinterdnd2.__file__), "tkdnd")
    want = {"win32": "win-x64", "darwin": "osx-arm64" if platform.machine() == "arm64" else "osx-x64"}
    sub = want.get(sys.platform)
    assert sub is None or os.path.isdir(os.path.join(tkdnd, sub)), f"drag-and-drop files missing ({sub})"
    yield f"drag and drop ({sub or 'n/a'})"

    presets = load_presets()
    assert presets, "no shared presets bundled"
    yield f"{len(presets)} preset(s)"

    from .fiery import load_config
    from .paths import FIERY_FILE
    assert FIERY_FILE.is_file(), "presets/fiery.json not bundled"
    presses, papers = load_config()
    assert len(presses) >= 2, "Fiery presses missing"
    yield f"{len(presses)} Fiery press(es), {len(papers) - 1} paper(s)"

    # A 2-page card with a real image, imposed 7 x 3 duplex with negative gutters.
    src = fitz.open()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40), False)
    pix.clear_with(120)
    for i in range(2):
        page = src.new_page(width=252, height=144)
        page.insert_text((20, 70), f"side {i + 1}", fontsize=24)
        page.insert_image(fitz.Rect(150, 20, 240, 80), pixmap=pix)
    src = fitz.open(stream=src.tobytes(), filetype="pdf")
    p = plan(src, Settings(duplex=True, rows=7, cols=3, gutter_x=-0.1, gutter_y=-0.1))
    assert not p.errors, p.errors
    out = fitz.open(stream=render(src, p).tobytes(garbage=4, deflate=True), filetype="pdf")
    assert len(out) == 2, f"expected 2 sides, got {len(out)}"

    def images(doc):  # decoded pixels: lossless re-compression is fine, changes aren't
        return {hashlib.md5(doc.xref_stream(x)).hexdigest()
                for x in range(1, doc.xref_length())
                if doc.xref_get_key(x, "Subtype")[1] == "/Image"}
    assert images(src) == images(out), "image pixels changed during imposition"
    yield "impose 7x3 duplex, image pixels identical"


def run(log_path=None):
    lines, ok = [], True
    try:
        for line in _checks():
            lines.append("ok   " + line)
    except Exception:
        ok = False
        lines.append("FAIL " + traceback.format_exc())
    text = "\n".join(lines) + ("\nPASSED\n" if ok else "\nFAILED\n")
    if log_path:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(text)
    if sys.stdout:
        print(text)
    return 0 if ok else 1
