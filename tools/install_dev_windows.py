"""
DEVELOPMENT COPY ONLY (Leo's PC). Staff install the release from GitHub instead.

Install this source folder as Prestige Impose: a Start menu entry with its
own icon that opens the program with no console window. Pin it from there
(right-click > Pin to taskbar), or pin the running window; both work because
the shortcut and the program share one app ID.

It also adds Prestige Impose to the right-click menu for PDFs in File Explorer:
  - Open with > Prestige Impose          (Windows 11's main right-click menu)
  - Impose with Prestige Impose          (under "Show more options")
Both are for this Windows user only (HKEY_CURRENT_USER, no admin needed) and
leave the default PDF app alone.

    python tools/install_dev_windows.py            # install / refresh
    python tools/install_dev_windows.py --remove   # take it all out again

Running from source keeps preset Save/Delete available; those presets ship to
staff in the next release. Don't also install the release on this PC: both
use the same Start menu name and right-click entries.

Safe to re-run: it just rewrites the shortcut. The shortcut points at this
folder's code, so changes to the program show up without reinstalling. If the
agent folder moves, run it again.
"""

import argparse
import os
import sys
import winreg
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools.make_icon import main as make_icon_files  # noqa: E402

APP_NAME = "Prestige Impose"
APP_ID = "PrestigeGraphics.Impose"   # must match prestige_impose/app.py
ICON = ROOT / "assets" / "icon.ico"
VENV = ROOT / ".venv"
SCRIPT = ROOT / "run_app.py"
START_MENU = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
SHORTCUT = START_MENU / f"{APP_NAME}.lnk"

# Right-click menu registration, all under HKCU\Software\Classes.
PROGID = "PrestigeGraphics.Impose.pdf"                       # the "Open with" entry
OPENWITH_KEY = r"Software\Classes\.pdf\OpenWithProgids"
PROGID_KEY = rf"Software\Classes\{PROGID}"
VERB_KEY = r"Software\Classes\SystemFileAssociations\.pdf\shell\PrestigeImpose"


def base_pythonw():
    """
    The real, windowless pythonw.exe behind the venv. The venv's own
    Scripts/pythonw.exe is a stand-in that relaunches the console python.exe,
    which pops a terminal window. run_app.py loads the venv's packages when
    started this way.
    """
    cfg = VENV / "pyvenv.cfg"
    if not cfg.is_file():
        raise SystemExit(f"Can't find {cfg}. Set up the agent's .venv first.")
    for line in cfg.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            exe = Path(value.strip()) / "pythonw.exe"
            if exe.is_file():
                return exe
            raise SystemExit(f"No pythonw.exe in {exe.parent}.")
    raise SystemExit(f"No 'home' line in {cfg}.")


def install():
    import pythoncom
    import win32com.client
    from win32com.propsys import propsys, pscon
    from win32com.shell import shellcon

    pythonw = base_pythonw()
    if not ICON.is_file():
        make_icon_files()

    shell = win32com.client.Dispatch("WScript.Shell")
    lnk = shell.CreateShortcut(str(SHORTCUT))
    lnk.TargetPath = str(pythonw)
    lnk.Arguments = f'"{SCRIPT}"'
    lnk.WorkingDirectory = str(ROOT)
    lnk.IconLocation = f"{ICON},0"
    lnk.Description = "Impose PDFs onto press sheets for the C4070"
    lnk.Save()

    # Give the shortcut the program's app ID so Windows treats them as one app:
    # the running window groups under the pin instead of showing as "Python".
    store = propsys.SHGetPropertyStoreFromParsingName(
        str(SHORTCUT), None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID,
                   propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()

    print(f"Installed: {SHORTCUT}")
    print(f"Icon:      {ICON}")
    print("Open Start, find 'Prestige Impose', right-click > Pin to taskbar.")
    install_right_click(pythonw)


def _set(key_path, values):
    """Create an HKCU key and set string values on it ('' = the default value)."""
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as k:
        for name, value in values.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _delete_tree(key_path):
    """Delete an HKCU key and everything under it. Missing is fine."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as k:
            while True:
                try:
                    child = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _delete_tree(rf"{key_path}\{child}")
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except FileNotFoundError:
        pass


def _refresh_explorer():
    """Tell Explorer file associations changed, so the menu updates now."""
    import ctypes
    SHCNE_ASSOCCHANGED, SHCNF_IDLIST = 0x08000000, 0x0000
    ctypes.windll.shell32.SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, None, None)


def install_right_click(pythonw):
    command = f'"{pythonw}" "{SCRIPT}" "%1"'
    icon = f"{ICON},0"
    # Open with > Prestige Impose
    _set(PROGID_KEY, {"": "PDF (Prestige Impose)", "FriendlyTypeName": "PDF document"})
    _set(rf"{PROGID_KEY}\DefaultIcon", {"": icon})
    _set(rf"{PROGID_KEY}\Application", {"ApplicationName": APP_NAME,
                                         "ApplicationIcon": icon,
                                         "AppUserModelID": APP_ID})
    _set(rf"{PROGID_KEY}\shell\open", {"FriendlyAppName": APP_NAME})
    _set(rf"{PROGID_KEY}\shell\open\command", {"": command})
    _set(OPENWITH_KEY, {PROGID: ""})
    # Impose with Prestige Impose (classic menu / Show more options)
    _set(VERB_KEY, {"": f"Impose with {APP_NAME}", "Icon": icon})
    _set(rf"{VERB_KEY}\command", {"": command})
    _refresh_explorer()
    print("Right-click on a PDF: Open with > Prestige Impose, "
          "or Show more options > Impose with Prestige Impose.")


def remove_right_click():
    _delete_tree(VERB_KEY)
    _delete_tree(PROGID_KEY)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, OPENWITH_KEY, 0, winreg.KEY_WRITE) as k:
            winreg.DeleteValue(k, PROGID)
    except FileNotFoundError:
        pass
    _refresh_explorer()
    print("Removed the right-click menu entries.")


def remove():
    if SHORTCUT.exists():
        SHORTCUT.unlink()
        print(f"Removed: {SHORTCUT}")
    else:
        print("Start menu entry not installed.")
    remove_right_click()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    a = ap.parse_args()
    remove() if a.remove else install()
    return 0


if __name__ == "__main__":
    sys.exit(main())
