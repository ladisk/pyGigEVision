"""Tests for fetch_genicam_xml — mocks GVCPClient.read_mem."""

import io
import zipfile
from unittest.mock import MagicMock

from pyGigEVision.genicam import fetch_genicam_xml, parse_first_url


def test_parse_first_url_plain():
    url = b"Local:cameralib.xml;0x10000;0x4000\x00" + b"\x00" * 470
    filename, addr, size = parse_first_url(url)
    assert filename == "cameralib.xml"
    assert addr == 0x10000
    assert size == 0x4000


def test_parse_first_url_zipped():
    url = b"Local:cameralib.zip;0x20000;0x1000\x00" + b"\x00" * 470
    filename, addr, size = parse_first_url(url)
    assert filename == "cameralib.zip"
    assert addr == 0x20000
    assert size == 0x1000


def test_fetch_genicam_xml_plain():
    raw_xml = b"<RegisterDescription>fake xml</RegisterDescription>"
    url_bytes = (b"Local:cam.xml;0x10000;%d\x00" % len(raw_xml)).ljust(512, b"\x00")
    client = MagicMock()
    # First read_mem(0x0200, 512) returns the URL; second returns the XML
    client.read_mem.side_effect = [url_bytes, raw_xml]
    xml, filename = fetch_genicam_xml(client)
    assert xml == raw_xml
    assert filename == "cam.xml"


def test_fetch_genicam_xml_zipped():
    inner_xml = b"<RegisterDescription>real xml</RegisterDescription>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("cam.xml", inner_xml)
    zipped = buf.getvalue()
    url_bytes = (b"Local:cam.zip;0x20000;%d\x00" % len(zipped)).ljust(512, b"\x00")
    client = MagicMock()
    client.read_mem.side_effect = [url_bytes, zipped]
    xml, filename = fetch_genicam_xml(client)
    assert xml == inner_xml
    assert filename == "cam.xml"


def test_parse_first_url_prefixed_hex():
    fn, addr, size = parse_first_url(b"Local:cam.xml;0x10000;0x4000\x00")
    assert (fn, addr, size) == ("cam.xml", 0x10000, 0x4000)


def test_parse_first_url_bare_hex_with_letters():
    # FLIR style: no 0x prefix, contains a-f
    fn, addr, size = parse_first_url(b"Local:cam.zip;ff000;1a000\x00")
    assert (fn, addr, size) == ("cam.zip", 0xFF000, 0x1A000)


def test_parse_first_url_decimal_still_decimal():
    # plain decimal stays decimal
    fn, addr, size = parse_first_url(b"Local:cam.xml;4096;256\x00")
    assert (addr, size) == (4096, 256)
