"""GenICam XML descriptor download helper.

Every GigE Vision camera stores its register description XML in on-board
memory. The location URL is at bootstrap register 0x0200 (REG_FIRST_URL)
and looks like::

    Local:cameralib.xml;0xADDR;0xSIZE

This module reads the URL, downloads the bytes, and decompresses if the
descriptor is zipped. Parsing the XML itself is left to the vendor driver
(register naming conventions differ enough across vendors that a generic
parser is not worth the abstraction).
"""

import io
import logging
import zipfile

from .standard import REG_FIRST_URL

logger = logging.getLogger(__name__)


def parse_first_url(url_bytes):
    """Parse the bytes read from REG_FIRST_URL into (filename, addr, size).

    Args:
        url_bytes: Raw bytes from ``client.read_mem(REG_FIRST_URL, 512)``.

    Returns:
        Tuple of (filename: str, addr: int, size: int).

    Raises:
        ValueError: If the URL string cannot be parsed.
    """
    url = url_bytes.split(b"\x00", 1)[0].decode("ascii")
    parts = url.split(";")
    if len(parts) < 3:
        raise ValueError(f"Malformed FIRST_URL: {url!r}")
    filename = parts[0].split(":")[-1]
    addr = int(parts[1], 0)
    size = int(parts[2], 0)
    return filename, addr, size


def fetch_genicam_xml(client):
    """Download the GenICam XML descriptor from a connected camera.

    Args:
        client: An open ``GVCPClient`` with control privilege.

    Returns:
        Tuple of (xml_bytes: bytes, filename: str). If the on-camera
        descriptor was zipped, ``xml_bytes`` is the decompressed XML and
        ``filename`` is the .xml entry name from the zip.
    """
    url_bytes = client.read_mem(REG_FIRST_URL, 512)
    filename, addr, size = parse_first_url(url_bytes)
    logger.info("Fetching GenICam descriptor: %s (addr=0x%X, %d bytes)",
                filename, addr, size)
    data = client.read_mem(addr, size)

    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_name = next(n for n in zf.namelist() if n.lower().endswith(".xml"))
            return zf.read(xml_name), xml_name

    return data, filename
