"""
Send an imposed PDF to a Fiery's Held queue over IPP (the printing protocol
the Fiery already listens on), with copies, two-sided, sheet size, tray and
colour set on the job.

Which presses and papers there are lives in presets/fiery.json, shared like
the presets. A paper is a Fiery Virtual Printer: a queue set up in Command
WorkStation with the paper type, weight (and usually tray) already set and
the job action Held. The Fiery's own IPP queue can't take paper type or
weight, so that's how they get onto the job.

Tested against two Fiery ES IC-419 servers (Konica C4070), 2026-10-02:
copies sent here show in Command WorkStation.
"""

import getpass
import json
import struct
import urllib.request
from dataclasses import dataclass, field
from math import ceil

from .paths import FIERY_FILE

HOLD_QUEUE = "ipp/hold"
TRAYS = {"Auto": None, "Tray 1": "tray-1", "Tray 2": "tray-2", "Tray 3": "tray-3",
         "Tray 4": "tray-4", "Tray 5": "tray-5"}
COLOURS = {"Colour": "color", "Grayscale": "monochrome"}
SET_IN_CWS = "Set in Command WorkStation"

# The Fiery's own names for its sheet sizes (from its media-supported list),
# by size in hundredths of a millimetre, short edge first. Sending the name as
# well as the size lets it pick its catalogue paper rather than a custom size.
SIZE_NAMES = {
    (33020, 48260): "na_super-b_13x19in",
    (30480, 45720): "na_arch-b_12x18in",
    (27940, 43180): "na_ledger_11x17in",
    (21590, 27940): "na_letter_8.5x11in",
    (21590, 35560): "na_legal_8.5x14in",
    (32000, 45000): "iso_sra3_320x450mm",
    (29700, 42000): "iso_a3_297x420mm",
    (21000, 29700): "iso_a4_210x297mm",
}

# What staff see if presets/fiery.json is missing.
DEFAULT_PRESSES = [
    {"name": "Press 1 - C4070", "host": "192.168.2.67"},
    {"name": "Press 2 - C4070NEW", "host": "192.168.2.71"},
]


@dataclass
class Press:
    name: str
    host: str
    port: int = 631


@dataclass
class Paper:
    name: str
    queues: dict = field(default_factory=dict)   # press name -> IPP queue path

    def queue_for(self, press):
        return self.queues.get(press.name)


def load_config():
    """(presses, papers). Papers always start with "Set in Command WorkStation"
    (the plain Held queue); then whatever virtual printers are listed."""
    try:
        raw = json.loads(FIERY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    presses = [Press(p["name"], p["host"], int(p.get("port", 631)))
               for p in raw.get("presses") or DEFAULT_PRESSES]
    papers = [Paper(SET_IN_CWS, {p.name: HOLD_QUEUE for p in presses})]
    for p in raw.get("papers") or []:
        papers.append(Paper(p["name"], dict(p.get("queues") or {})))
    return presses, papers


def copies_for(plan_, quantity):
    """
    How many copies of the imposed file to ask for. Gangup repeat: quantity is
    finished pieces, so sheets = pieces / pieces per sheet, rounded up (each
    sheet in the file is one design). Otherwise quantity is sets of the file.
    Returns (copies, label) where label says what that means.
    """
    s = plan_.settings
    if quantity < 1:
        raise ValueError("Quantity must be at least 1.")
    if s.layout == "gangup" and s.gang == "repeat":
        per = max(1, plan_.per_sheet)
        sheets = ceil(quantity / per)
        designs = plan_.sheet_count
        each = " of each design" if designs > 1 else ""
        return sheets, f"{sheets} sheet(s){each} ({per} up, rounded up)"
    return quantity, f"{quantity} set(s) of {plan_.sheet_count} sheet(s)"


def sides_for(plan_):
    """
    IPP two-sided setting. Backs are always laid out mirrored left/right
    (the sheet turns on its left/right edge, as you look at it), which the
    Fiery calls left bind / Top-Top for portrait and landscape sheets alike.
    It reads "short edge" as top bind, so that's never sent (Leo, 2026-10-05:
    landscape jobs arrived as top bind).
    """
    return "two-sided-long-edge" if plan_.settings.duplex else "one-sided"


# ------------------------------------------------------------------- IPP wire

def _attr(tag, name, value):
    if isinstance(value, int) and not isinstance(value, bool):
        v = struct.pack(">i", value)
    else:
        v = value.encode() if isinstance(value, str) else value
    return struct.pack(">BH", tag, len(name)) + name.encode() + struct.pack(">H", len(v)) + v


def _member(tag, name, value):
    """A member of a collection: name goes in a memberAttrName value."""
    return _attr(0x4A, "", name) + _attr(tag, "", value)


def _media_col(sheet_pt, tray):
    # Sheet size in hundredths of a millimetre, short edge first (the way the
    # Fiery lists its paper); a landscape PDF is turned to fit.
    a, b = sorted(round(v / 72 * 2540) for v in sheet_pt)
    size = (_attr(0x34, "", b"") + _member(0x21, "x-dimension", a)
            + _member(0x21, "y-dimension", b) + _attr(0x37, "", b""))
    body = _attr(0x34, "media-col", b"") + _attr(0x4A, "", "media-size") + size
    name = SIZE_NAMES.get((a, b))
    if name:
        body += _member(0x44, "media-size-name", name)
    if tray:
        body += _member(0x44, "media-source", tray)
    return body + _attr(0x37, "", b"")


def build_print_job(uri, pdf, job_name, copies, sides, sheet_pt, tray=None, colour="color",
                    user=None, request_id=1):
    """The bytes of an IPP Print-Job request (operation 0x0002)."""
    head = struct.pack(">BBHI", 1, 1, 0x0002, request_id)
    ops = (b"\x01" + _attr(0x47, "attributes-charset", "utf-8")
           + _attr(0x48, "attributes-natural-language", "en")
           + _attr(0x45, "printer-uri", uri)
           + _attr(0x42, "requesting-user-name", user or _user())
           + _attr(0x42, "job-name", job_name[:200])
           + _attr(0x22, "ipp-attribute-fidelity", b"\x00")
           + _attr(0x49, "document-format", "application/pdf"))
    job = (b"\x02" + _attr(0x21, "copies", int(copies))
           + _attr(0x44, "sides", sides)
           + _attr(0x44, "print-color-mode", colour)
           + _media_col(sheet_pt, tray))
    return head + ops + job + b"\x03" + pdf


def parse_response(data):
    """(status code, {name: value}) from an IPP response."""
    if len(data) < 8:
        raise ValueError("Empty reply from the Fiery.")
    status = struct.unpack(">H", data[2:4])[0]
    i, out = 8, {}
    while i < len(data):
        tag = data[i]; i += 1
        if tag < 0x10:
            if tag == 0x03:
                break
            continue
        nl = struct.unpack(">H", data[i:i + 2])[0]; i += 2
        name = data[i:i + nl].decode(errors="replace"); i += nl
        vl = struct.unpack(">H", data[i:i + 2])[0]; i += 2
        val = data[i:i + vl]; i += vl
        if tag in (0x21, 0x23) and vl == 4:
            val = struct.unpack(">i", val)[0]
        else:
            val = val.decode(errors="replace")
        if name and name not in out:
            out[name] = val
    return status, out


def _user():
    try:
        return getpass.getuser() or "Prestige Impose"
    except Exception:
        return "Prestige Impose"


class SendError(Exception):
    pass


def send(press, queue, pdf, job_name, copies, sides, sheet_pt, tray=None, colour="color",
         timeout=120):
    """
    Send the PDF bytes to press/queue. Returns the Fiery's job id (or None if
    it didn't say). Raises SendError with a plain-language reason.
    """
    url = f"http://{press.host}:{press.port}/{queue}"
    uri = f"ipp://{press.host}/{queue}"
    body = build_print_job(uri, pdf, job_name, copies, sides, sheet_pt, tray, colour)
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/ipp"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status, attrs = parse_response(r.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise SendError(f"{press.name} has no queue called '{queue}'. Check the virtual "
                            "printer's name in Command WorkStation.") from e
        raise SendError(f"{press.name} refused the job (HTTP {e.code}).") from e
    except OSError as e:
        raise SendError(f"Couldn't reach {press.name} at {press.host}. Is this computer on "
                        f"the office network, and is the press on?\n\n({e})") from e
    if status >= 0x0400:
        msg = attrs.get("status-message") or f"IPP status 0x{status:04x}"
        raise SendError(f"{press.name} refused the job: {msg}")
    return attrs.get("job-id")
