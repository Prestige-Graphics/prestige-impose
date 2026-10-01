"""
Update check and self-update, from the GitHub releases of this repository.

On launch the installed app asks GitHub for the latest release. If it's newer
than this copy, the app shows "Update available" with the release notes
(the "What's new" text from CHANGELOG.md). "Update now" downloads the right
file for this computer and installs it:

  Windows  the Setup .exe runs silently over the top (per-user install, no
           admin prompt) and starts the new version when it's done.
  Mac      the new .app replaces this one once the app has quit, then opens.

The download is made by the app itself, not a web browser, so it doesn't
carry the "downloaded from the internet" tag that makes Windows and macOS
ask for approval. Only the very first install goes through that.

Everything here fails quietly: no internet, or GitHub down, just means no
update notice this time.
"""

import json
import os
import platform
import ssl
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from . import __version__
from .paths import FROZEN, IS_MAC, IS_WINDOWS

REPO = "Prestige-Graphics/prestige-impose"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT = 8  # seconds


def _ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _parse(version):
    """'v1.2.10' -> (1, 2, 10). Anything odd sorts as oldest."""
    try:
        return tuple(int(p) for p in version.strip().lstrip("vV").split("."))
    except ValueError:
        return (0,)


def asset_name(version):
    """The release file meant for this computer."""
    if IS_WINDOWS:
        return f"PrestigeImpose-Setup-{version}.exe"
    if IS_MAC:
        arch = "arm64" if platform.machine() == "arm64" else "x86_64"
        return f"PrestigeImpose-{version}-mac-{arch}.zip"
    return None


def should_check():
    """Only the installed app checks; the development copy doesn't nag."""
    return FROZEN or os.environ.get("PRESTIGE_IMPOSE_CHECK_UPDATES") == "1"


def check():
    """
    Returns {version, notes, url, name, page} if a newer release with a file
    for this computer exists, else None. Never raises.
    """
    try:
        req = urllib.request.Request(LATEST_URL, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"PrestigeImpose/{__version__}",
        })
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_ssl_context()) as r:
            data = json.load(r)
        latest = data.get("tag_name", "").lstrip("vV")
        if _parse(latest) <= _parse(__version__):
            return None
        wanted = asset_name(latest)
        asset = next((a for a in data.get("assets", []) if a.get("name") == wanted), None)
        if not asset:
            return None
        return {
            "version": latest,
            "notes": (data.get("body") or "").strip() or "Improvements and fixes.",
            "url": asset["browser_download_url"],
            "name": wanted,
            "size": asset.get("size") or 0,
            "page": data.get("html_url", ""),
        }
    except Exception:
        return None


def download(info, progress=None):
    """Download the update to a temp folder. progress(fraction) is called as it goes."""
    folder = Path(tempfile.mkdtemp(prefix="prestige-impose-update-"))
    dest = folder / info["name"]
    req = urllib.request.Request(info["url"], headers={"User-Agent": f"PrestigeImpose/{__version__}"})
    with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or info.get("size") or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(min(done / total, 1.0))
    if info.get("size") and dest.stat().st_size != info["size"]:
        raise IOError("The download was incomplete. Try again.")
    return dest


def install_and_restart(path):
    """
    Hand over to the installer and return; the caller must then quit the app
    straight away so its files can be replaced.
    """
    path = Path(path)
    if IS_WINDOWS:
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                          "/CLOSEAPPLICATIONS"], creationflags=flags, close_fds=True)
        return
    if IS_MAC:
        _install_mac(path)
        return
    raise RuntimeError("Self-update isn't supported on this system.")


def _install_mac(zip_path):
    # .../Prestige Impose.app/Contents/MacOS/Prestige Impose -> the .app
    app = Path(sys.executable).resolve().parents[2]
    if app.suffix != ".app":
        raise RuntimeError("Can't find the installed app to replace.")
    work = zip_path.parent
    # ditto keeps the app's signature and permissions intact (unzip doesn't).
    subprocess.run(["/usr/bin/ditto", "-x", "-k", str(zip_path), str(work)], check=True)
    new_app = next(work.glob("*.app"), None)
    if new_app is None:
        raise RuntimeError("The update didn't contain the app.")
    script = work / "install.sh"
    script.write_text(f"""#!/bin/bash
# Wait for the running copy to quit, swap the app, open the new one.
while /bin/kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done
APP={json.dumps(str(app))}
NEW={json.dumps(str(new_app))}
rm -rf "$APP.old"
if mv "$APP" "$APP.old"; then
  if mv "$NEW" "$APP"; then rm -rf "$APP.old"; else mv "$APP.old" "$APP"; fi
fi
/usr/bin/xattr -dr com.apple.quarantine "$APP" 2>/dev/null
/usr/bin/open "$APP"
""")
    script.chmod(0o755)
    subprocess.Popen(["/bin/bash", str(script)], start_new_session=True, close_fds=True)
