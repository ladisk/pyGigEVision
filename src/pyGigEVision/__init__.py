"""pyGigEVision — pure-Python GigE Vision protocol library.

Provides GVCP (control), GVSP (streaming), GigE Vision standard register
constants, and helpers for fetching the GenICam XML descriptor from a
connected camera. Vendor-specific drivers (register maps, calibration,
image-format quirks) are built on top — pyGigEVision is the protocol
foundation.

Quickstart::

    from pyGigEVision import discover, bootstrap, GVSPReceiver

    cameras = discover()
    client, xml = bootstrap(cameras[0]["ip"])
    # ... configure registers, start GVSPReceiver, grab frames
"""

__version__ = "0.0.1"

from .gvcp import GVCPClient, GVCPError
from .gvsp import GVSPReceiver
from .genicam import fetch_genicam_xml, parse_first_url
from .bootstrap import bootstrap

# `discover` is a @staticmethod on GVCPClient — alias to the package level
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
