"""pyGigEVision: pure-Python GigE Vision protocol library.

Provides GVCP (control channel), GVSP (image streaming), GigE Vision
standard register constants, and helpers for fetching the GenICam XML
descriptor from a connected camera.  Vendor-specific drivers (register
maps, calibration, image-format quirks) are built on top of this
protocol foundation.

Public API summary:

* :class:`~pyGigEVision.gvcp.GVCPClient`: UDP-based camera control: register read/write,
  bulk memory access, heartbeat keepalive.
* :exc:`~pyGigEVision.gvcp.GVCPError`: raised when the camera returns a non-SUCCESS GVCP
  status code.
* :class:`GVSPReceiver`: background UDP receiver that reassembles
  image frames into NumPy arrays.
* :func:`discover`: broadcast discovery to find cameras on the network.
* :func:`bootstrap`: single-call convenience: open GVCP, take CCP
  control, fetch GenICam XML.
* :func:`fetch_genicam_xml`: download and decompress the GenICam XML
  descriptor from a connected camera.
* :func:`parse_first_url`: parse the ``REG_FIRST_URL`` bytes into
  ``(filename, addr, size)``.

Quickstart::

    from pyGigEVision import discover, bootstrap, GVSPReceiver

    cameras = discover()
    client, xml = bootstrap(cameras[0]["ip"])
    # ... configure registers, start GVSPReceiver, grab frames
    client.disconnect()
"""

from __future__ import annotations

__version__ = "0.1.1"
from .bootstrap import bootstrap
from .genicam import fetch_genicam_xml, parse_first_url
from .gvcp import GVCPClient, GVCPError
from .gvsp import GVSPReceiver

# Namespace note: the line above re-exports the function `bootstrap` at the
# package level, which shadows the `bootstrap` submodule when accessed as a
# package attribute. `pyGigEVision.bootstrap` is the function; to get the
# submodule object (e.g., for `unittest.mock.patch.object`), use
# `importlib.import_module("pyGigEVision.bootstrap")`.

# `discover` is a @staticmethod on GVCPClient; aliased to the package level
# so users can `from pyGigEVision import discover`.
discover = GVCPClient.discover

__all__ = [
    "__version__",
    "GVCPClient",
    "GVCPError",
    "GVSPReceiver",
    "discover",
    "fetch_genicam_xml",
    "parse_first_url",
    "bootstrap",
]
