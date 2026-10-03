# PyInstaller build recipe for Prestige Impose (Windows and Mac).
#
#     pyinstaller packaging/prestige_impose.spec --noconfirm
#
# Builds a normal program folder (not a single self-unpacking .exe, which
# antivirus is far more likely to flag) at dist/Prestige Impose/, and on a Mac
# also dist/Prestige Impose.app.

import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent
VERSION = re.search(r'__version__ = "([^"]+)"',
                    (ROOT / "prestige_impose" / "__init__.py").read_text()).group(1)
IS_MAC = sys.platform == "darwin"
NAME = "Prestige Impose"

a = Analysis(
    [str(ROOT / "run_app.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(ROOT / "presets" / "shared_presets.json"), "presets"),
        (str(ROOT / "presets" / "fiery.json"), "presets"),
        (str(ROOT / "assets" / "icon.ico"), "assets"),
    ] + collect_data_files("tkinterdnd2"),   # the tkdnd drag-and-drop library
    hiddenimports=["certifi", "tkinterdnd2"],
    excludes=["pytest", "PIL"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=NAME,
    console=False,                     # no terminal window
    icon=str(ROOT / "assets" / ("icon.png" if IS_MAC else "icon.ico")),
    version=None,
)

coll = COLLECT(exe, a.binaries, a.datas, name=NAME)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{NAME}.app",
        icon=str(ROOT / "assets" / "icon.png"),   # converted to .icns (needs Pillow)
        bundle_identifier="com.prestigegraphics.impose",
        version=VERSION,
        info_plist={
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION,
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
            # Shows up in Finder's right-click "Open With" for PDFs, without
            # taking over as the default PDF app.
            "CFBundleDocumentTypes": [{
                "CFBundleTypeName": "PDF document",
                "CFBundleTypeRole": "Viewer",
                "LSHandlerRank": "Alternate",
                "LSItemContentTypes": ["com.adobe.pdf"],
            }],
        },
    )
