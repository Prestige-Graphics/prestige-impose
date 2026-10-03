"""
Where things live, whether running from source (Leo's development copy) or as
the installed app (staff copies, built with PyInstaller).
"""

import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)          # True in the installed app
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# Bundled files (presets, icon): next to the code in source, unpacked by
# PyInstaller into sys._MEIPASS in the app.
RESOURCES = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

PRESETS_FILE = RESOURCES / "presets" / "shared_presets.json"
FIERY_FILE = RESOURCES / "presets" / "fiery.json"      # presses and papers for Send to Fiery
ICON_ICO = RESOURCES / "assets" / "icon.ico"

# Shared presets are edited on the development copy and shipped with each
# release. The installed app can't change them (and its files may be
# replaced on the next update anyway).
CAN_EDIT_PRESETS = not FROZEN
