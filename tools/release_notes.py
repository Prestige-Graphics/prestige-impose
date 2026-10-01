"""
Print the "What's new" notes for one version from CHANGELOG.md. Staff see this
text in the app's update window, so it's written for them, in plain words.

    python tools/release_notes.py 1.2.0
    python tools/release_notes.py          # the current version
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def notes(version):
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\b.*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not m or not m.group(1).strip():
        raise SystemExit(f"CHANGELOG.md has no notes for {version}. Add them before releasing.")
    return m.group(1).strip()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        v = sys.argv[1].lstrip("v")
    else:
        sys.path.insert(0, str(ROOT))
        from prestige_impose import __version__ as v
    print(notes(v))
