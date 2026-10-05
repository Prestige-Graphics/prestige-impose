"""Send to Fiery: quantity maths and the exact IPP job sent (to a fake Fiery on this PC)."""

import struct
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from prestige_impose import fiery
from prestige_impose.engine import Settings, describe, plan
from tests.test_engine import make_marked_pdf, make_pdf


def test_quantity_to_sheets_rounds_up():
    p = plan(make_pdf(2), Settings(rows=7, cols=3, duplex=True))
    assert fiery.copies_for(p, 500) == (24, "24 sheet(s) (21 up, rounded up)")
    assert fiery.copies_for(p, 21)[0] == 1
    assert fiery.copies_for(p, 22)[0] == 2
    with pytest.raises(ValueError):
        fiery.copies_for(p, 0)
    unique = plan(make_pdf(4), Settings(rows=2, cols=1, gang="unique"))
    assert fiery.copies_for(unique, 50) == (50, "50 set(s) of 2 sheet(s)")


def test_sides_follow_the_sheet():
    src = make_pdf(2)
    assert fiery.sides_for(plan(src, Settings(duplex=False))) == "one-sided"
    assert fiery.sides_for(plan(src, Settings(duplex=True))) == "two-sided-long-edge"
    # Landscape too: the Fiery reads short-edge as top bind.
    assert fiery.sides_for(plan(src, Settings(duplex=True, orientation="landscape"))) == \
        "two-sided-long-edge"


def parse_request(data):
    """Attributes of an IPP request, with media-col members flattened, plus the document."""
    i, out, path = 8, {}, []
    while True:
        tag = data[i]; i += 1
        if tag < 0x10:
            if tag == 0x03:
                return out, data[i:]
            continue
        nl = struct.unpack(">H", data[i:i + 2])[0]; i += 2
        name = data[i:i + nl].decode(); i += nl
        vl = struct.unpack(">H", data[i:i + 2])[0]; i += 2
        val = data[i:i + vl]; i += vl
        if tag == 0x34:
            path.append(name or member)
            continue
        if tag == 0x37:
            path.pop()
            continue
        if tag == 0x4A:
            member = val.decode()
            continue
        if tag in (0x21, 0x23):
            val = struct.unpack(">i", val)[0]
        elif tag == 0x22:
            val = bool(val[0])
        else:
            val = val.decode()
        key = ".".join(path + [name or member])
        out[key] = val


@pytest.fixture
def fake_fiery():
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            got["path"] = self.path
            got["body"] = self.rfile.read(int(self.headers["Content-Length"]))
            reply = (struct.pack(">BBHI", 1, 1, 0x0000, 1) + b"\x01"
                     + fiery._attr(0x47, "attributes-charset", "utf-8")
                     + fiery._attr(0x48, "attributes-natural-language", "en") + b"\x02"
                     + fiery._attr(0x21, "job-id", 4242) + b"\x03")
            self.send_response(200)
            self.send_header("Content-Type", "application/ipp")
            self.send_header("Content-Length", str(len(reply)))
            self.end_headers()
            self.wfile.write(reply)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], got
    srv.shutdown()


def test_send_puts_everything_on_the_job(fake_fiery, monkeypatch):
    port, got = fake_fiery
    press = fiery.Press("Press 1 - test", "127.0.0.1", port)
    monkeypatch.setattr(fiery, "_user", lambda: "sabrina")
    src = make_marked_pdf(slug_in=0.4583)
    p = plan(src, Settings(rows=7, cols=3, duplex=True, gutter_x=-0.63, gutter_y=-0.63))
    job_id = fiery.send(press, "ipp/hold", b"%PDF-fake", "Royal cards", 24, fiery.sides_for(p),
                        p.sheet, tray="tray-2", colour="color")
    assert job_id == 4242
    assert got["path"] == "/ipp/hold"
    attrs, doc = parse_request(got["body"])
    assert doc == b"%PDF-fake"
    assert attrs["copies"] == 24
    assert attrs["sides"] == "two-sided-long-edge"
    assert attrs["job-name"] == "Royal cards"
    assert attrs["requesting-user-name"] == "sabrina"
    assert attrs["document-format"] == "application/pdf"
    assert attrs["media-col.media-size.x-dimension"] == 30480     # 12" in 1/100 mm
    assert attrs["media-col.media-size.y-dimension"] == 45720     # 18"
    assert attrs["media-col.media-source"] == "tray-2"
    assert attrs["media-col.media-size-name"] == "na_arch-b_12x18in"
    assert attrs["print-color-mode"] == "color"


def test_auto_tray_sends_no_tray(fake_fiery):
    port, got = fake_fiery
    press = fiery.Press("Press", "127.0.0.1", port)
    fiery.send(press, "ipp/hold", b"%PDF", "x", 1, "one-sided", (18 * 72, 12 * 72), tray=None)
    attrs, _ = parse_request(got["body"])
    assert "media-col.media-source" not in attrs
    assert attrs["media-col.media-size.x-dimension"] == 30480     # short edge first


def test_13x19_is_made_and_sent_at_the_press_size(fake_fiery):
    """Konica's 13x19 is 330 x 483 mm; exactly 13 x 19 in was refused as a custom
    size (proved on Press 1, 2026-10-05). Sent with the Fiery's name for it."""
    port, got = fake_fiery
    for orientation in ("portrait", "landscape"):
        p = plan(make_pdf(1), Settings(sheet_w=13, sheet_h=19, orientation=orientation))
        assert sorted(round(v / 72 * 25.4, 2) for v in p.sheet) == [330.0, 483.0]
        fiery.send(fiery.Press("Press", "127.0.0.1", port), "ipp/hold", b"%PDF", "x", 1,
                   "one-sided", p.sheet)
        attrs, _ = parse_request(got["body"])
        assert attrs["media-col.media-size-name"] == "na_super-b_13x19in"
        assert (attrs["media-col.media-size.x-dimension"],
                attrs["media-col.media-size.y-dimension"]) == (33000, 48300)
    # It's still called 13 x 19 everywhere people see it.
    assert '19" x 13" landscape' in describe(p, 1)


def test_custom_sheet_sends_no_name(fake_fiery):
    port, got = fake_fiery
    fiery.send(fiery.Press("Press", "127.0.0.1", port), "ipp/hold", b"%PDF", "x", 1,
               "one-sided", (10 * 72, 14 * 72))
    attrs, _ = parse_request(got["body"])
    assert "media-col.media-size-name" not in attrs


def test_unreachable_press_says_so():
    press = fiery.Press("Press 9", "127.0.0.1", 1)
    with pytest.raises(fiery.SendError, match="Couldn't reach Press 9"):
        fiery.send(press, "ipp/hold", b"%PDF", "x", 1, "one-sided", (864, 1296), timeout=3)


def test_papers_only_where_set_up(tmp_path, monkeypatch):
    f = tmp_path / "fiery.json"
    f.write_text('{"presses": [{"name": "P1", "host": "h1"}, {"name": "P2", "host": "h2"}],'
                 ' "papers": [{"name": "14pt Gloss", "queues": {"P1": "ipp/14pt Gloss"}}]}')
    monkeypatch.setattr(fiery, "FIERY_FILE", f)
    presses, papers = fiery.load_config()
    assert [p.name for p in papers] == [fiery.SET_IN_CWS, "14pt Gloss"]
    assert papers[0].queue_for(presses[1]) == "ipp/hold"
    assert papers[1].queue_for(presses[0]) == "ipp/14pt Gloss"
    assert papers[1].queue_for(presses[1]) is None


def test_shipped_config_lists_both_presses():
    presses, papers = fiery.load_config()
    assert [p.host for p in presses] == ["192.168.2.67", "192.168.2.71"]
    assert presses[0].name.startswith("Press 1")
