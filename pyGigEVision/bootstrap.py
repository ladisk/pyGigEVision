"""Convenience helper to bring a GigE Vision camera up to a usable state.

Performs the standard boot sequence shared by every GigE Vision driver:
acquire control privilege, start heartbeat keepalive, fetch the GenICam
XML descriptor.  Vendor drivers use this to skip boilerplate, or roll
their own if they need finer control over each step.
"""

from __future__ import annotations

from .genicam import fetch_genicam_xml
from .gvcp import GVCPClient
from .standard import REG_CCP, REG_HEARTBEAT_TIMEOUT

# CCP value 2 = exclusive control access
_CCP_EXCLUSIVE = 0x00000002

# 3 second heartbeat timeout — matches pyTelops default
_DEFAULT_HEARTBEAT_MS = 3000


def bootstrap(
    camera_ip: str, heartbeat_ms: int = _DEFAULT_HEARTBEAT_MS
) -> tuple[GVCPClient, bytes]:
    """Connect to a camera, take control, and fetch its GenICam XML.

    Performs the three-step standard boot sequence: open the GVCP socket,
    write exclusive ``CCP`` control privilege, set the heartbeat timeout,
    and fetch the GenICam XML descriptor via :func:`~pyGigEVision.genicam.fetch_genicam_xml`.

    Parameters
    ----------
    camera_ip : str
        IPv4 address of the target camera, e.g. ``"169.254.1.10"``.
    heartbeat_ms : int, optional
        Heartbeat timeout to write to the camera's
        ``REG_HEARTBEAT_TIMEOUT`` register, in milliseconds.
        Default is ``3000`` (3 seconds).

    Returns
    -------
    tuple of (~pyGigEVision.gvcp.GVCPClient, bytes)
        ``(client, xml_bytes)`` where *client* is a connected
        :class:`~pyGigEVision.gvcp.GVCPClient` holding exclusive control
        privilege and *xml_bytes* is the raw GenICam XML.  The caller is
        responsible for calling ``client.disconnect()`` when done.

    Raises
    ------
    ~pyGigEVision.gvcp.GVCPError
        If taking CCP control or reading the GenICam XML fails.
    OSError
        If the UDP socket cannot be created or bound.

    Examples
    --------
    >>> from pyGigEVision import bootstrap
    >>> client, xml = bootstrap("169.254.1.10")
    >>> print(f"Got {len(xml)} bytes of GenICam XML")
    >>> client.disconnect()
    """
    client = GVCPClient(camera_ip)
    client.connect()
    client.write_reg(REG_CCP, _CCP_EXCLUSIVE)
    client.write_reg(REG_HEARTBEAT_TIMEOUT, heartbeat_ms)
    xml, _filename = fetch_genicam_xml(client)
    return client, xml
