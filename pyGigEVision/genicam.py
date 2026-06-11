"""GenICam XML descriptor download helper.

Every GigE Vision camera stores its register description XML in on-board
memory.  The location URL is at bootstrap register 0x0200
(``REG_FIRST_URL``) and follows the format::

    Local:cameralib.xml;0xADDR;0xSIZE

This module reads the URL, downloads the bytes, and decompresses the
descriptor if the camera stores it as a ZIP archive (common for larger
XML files).

Notes
-----
Parsing the XML itself is left to the vendor driver.  Register naming
conventions differ enough across vendors that a generic parser would add
more abstraction than value.  Vendor drivers receive the raw XML bytes
from :func:`fetch_genicam_xml` and interpret them using their own
register maps.
"""

from __future__ import annotations

import io
import logging
import zipfile

from .standard import REG_FIRST_URL

logger = logging.getLogger(__name__)


def parse_first_url(url_bytes: bytes) -> tuple[str, int, int]:
    """Parse the bytes read from REG_FIRST_URL into (filename, addr, size).

    Parameters
    ----------
    url_bytes : bytes
        Raw bytes from ``client.read_mem(REG_FIRST_URL, 512)``.  The
        string is null-terminated; everything after the first null byte
        is ignored.  Non-ASCII trailing bytes are replaced with the
        Unicode replacement character and then discarded by the null split.

    Returns
    -------
    tuple of (str, int, int)
        ``(filename, addr, size)`` where *filename* is the XML or ZIP
        entry name (e.g. ``"cameralib.xml"``), *addr* is the start
        address of the descriptor in camera memory, and *size* is the
        byte length.

        Numeric fields accept both ``0x``-prefixed hex (``0x10000``) and
        bare hex without a prefix (``ff000``, emitted by some cameras), as
        well as plain decimal integers.

    Raises
    ------
    ValueError
        If the URL string cannot be split into at least three
        semicolon-separated parts (malformed descriptor).

    Examples
    --------
    >>> url = b"Local:cameralib.xml;0x10000;0x4000\\x00"
    >>> filename, addr, size = parse_first_url(url)
    >>> filename
    'cameralib.xml'
    >>> hex(addr)
    '0x10000'
    >>> size
    16384
    """

    def _parse_int(field: str) -> int:
        field = field.strip()
        try:
            return int(field, 0)  # 0x-prefixed hex or decimal
        except ValueError:
            return int(field, 16)  # bare hex without a prefix, e.g. "ff000"

    url = url_bytes.split(b"\x00", 1)[0].decode("ascii", errors="replace")
    parts = url.split(";")
    if len(parts) < 3:
        raise ValueError(f"Malformed FIRST_URL: {url!r}")
    filename = parts[0].split(":")[-1]
    addr = _parse_int(parts[1])
    size = _parse_int(parts[2])
    return filename, addr, size


def fetch_genicam_xml(client: object) -> tuple[bytes, str]:
    """Download the GenICam XML descriptor from a connected camera.

    Reads the ``REG_FIRST_URL`` register to locate the descriptor, fetches
    the raw bytes, and decompresses them if the camera stored the XML as a
    ZIP archive.

    Parameters
    ----------
    client : ~pyGigEVision.gvcp.GVCPClient
        An open :class:`~pyGigEVision.gvcp.GVCPClient` with control
        privilege.  Must expose a ``read_mem(addr, size)`` method that
        returns ``bytes``.

    Returns
    -------
    tuple of (bytes, str)
        ``(xml_bytes, filename)`` where *xml_bytes* is the raw (and, if
        necessary, decompressed) GenICam XML, and *filename* is the name
        of the XML entry (from the zip archive if the descriptor was
        compressed, otherwise the filename from ``REG_FIRST_URL``).

    Examples
    --------
    Typical usage with a connected client::

        from pyGigEVision import GVCPClient
        from pyGigEVision.genicam import fetch_genicam_xml

        with GVCPClient("169.254.1.10") as client:
            xml_bytes, filename = fetch_genicam_xml(client)
            print(f"Received {len(xml_bytes)} bytes from '{filename}'")
    """
    url_bytes = client.read_mem(REG_FIRST_URL, 512)
    filename, addr, size = parse_first_url(url_bytes)
    logger.info("Fetching GenICam descriptor: %s (addr=0x%X, %d bytes)", filename, addr, size)
    data = client.read_mem(addr, size)

    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
            return zf.read(xml_name), xml_name

    return data, filename
