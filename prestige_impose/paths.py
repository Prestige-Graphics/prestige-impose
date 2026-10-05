"""
Where things live, whether running from source (Leo's development copy) or as
the installed app (staff copies, built with PyInstaller).
"""

import os
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)          # True in the installed app
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Bundled files (presets, icon): next to the code in source, unpacked by
# PyInstaller into sys._MEIPASS in the app.
RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

# The presets that come with the app. Each computer keeps its own list (see
# mypresets.py); these are added to it, once each.
PRESETS_FILE = RESOURCES / "presets" / "shared_presets.json"
FIERY_FILE = RESOURCES / "presets" / "fiery.json"      # presses and papers for Send to Fiery
ICON_ICO = RESOURCES / "assets" / "icon.ico"

# This computer's own files: its presets, and which shipped presets it has had.
if IS_WINDOWS:
    CONFIG_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "Prestige Impose"
elif IS_MAC:
    CONFIG_DIR = Path.home() / "Library" / "Application Support" / "Prestige Impose"
else:
    CONFIG_DIR = Path.home() / ".config" / "prestige-impose"
