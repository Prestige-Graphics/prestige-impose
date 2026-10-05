"""
Each computer's own presets (Leo, 2026-10-05: everyone has their own).

The list lives in this computer's settings folder (paths.CONFIG_DIR), so it
survives updates. The presets that come with the app (presets/
shared_presets.json) are added to it once each: the first time the app runs,
and again whenever an update ships a new one. One that's been added before
isn't added back, so deleting a shipped preset sticks.
"""

import json

from . import engine
from .paths import CONFIG_DIR, PRESETS_FILE

MY_PRESETS = "presets.json"
SEEN = "shipped presets added.json"


def _read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def activate(folder=None):
    """
    Point the app's presets at this computer's list, adding any shipped
    presets it hasn't had yet. Returns the list's path, or None if the
    settings folder can't be written (then the shipped list is used as is).
    """
    folder = folder or CONFIG_DIR
    mine, seen_file = folder / MY_PRESETS, folder / SEEN
    shipped = _read(PRESETS_FILE, {})
    seen = set(_read(seen_file, []))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        engine.PRESETS_FILE = mine
        new = {n: d for n, d in shipped.items() if n not in seen}
        if new or not mine.exists():
            current = engine._read_presets_file()
            for name, d in new.items():
                current.setdefault(name, d)   # never replaces one of theirs
            engine._write_presets(current)
        seen_file.write_text(json.dumps(sorted(seen | set(shipped)), indent=2),
                             encoding="utf-8")
        return mine
    except OSError:
        engine.PRESETS_FILE = PRESETS_FILE
        return None
