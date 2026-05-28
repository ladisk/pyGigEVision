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

__version__ = "0.1.0"

from .bootstrap import bootstrap
from .genicam import fetch_genicam_xml, parse_first_url
from .gvcp import GVCPClient, GVCPError
from .gvsp import GVSPReceiver

# Namespace note: the line above re-exports the function `bootstrap` at the
# package level, which shadows the `bootstrap` submodule when accessed as a
# package attribute. `pyGigEVision.bootstrap` is the function; to get the
# submodule object (e.g., for `unittest.mock.patch.object`), use
# `importlib.import_module("pyGigEVision.bootstrap")`.

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
