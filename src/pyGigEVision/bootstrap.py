"""Convenience helper to bring a GigE Vision camera up to a usable state.

Performs the standard boot sequence shared by every GigE Vision driver:
acquire control privilege, start heartbeat keepalive, fetch the GenICam
XML descriptor. Vendor drivers use this to skip boilerplate, or roll
their own if they need finer control.
"""

from .gvcp import GVCPClient
from .genicam import fetch_genicam_xml
from .standard import REG_CCP, REG_HEARTBEAT_TIMEOUT

# CCP value 2 = exclusive control access
_CCP_EXCLUSIVE = 0x00000002

# 3 second heartbeat timeout — matches pyTelops default
_DEFAULT_HEARTBEAT_MS = 3000


def bootstrap(camera_ip, heartbeat_ms=_DEFAULT_HEARTBEAT_MS):
    """Connect to a camera, take control, fetch its GenICam XML.

    Args:
        camera_ip: IPv4 address of the target camera.
        heartbeat_ms: Heartbeat timeout to write to the camera, in ms.

    Returns:
        Tuple of (client: GVCPClient, xml_bytes: bytes). The client is
        connected and holds exclusive control privilege; the caller is
        responsible for ``client.close()`` when done.
    """
    client = GVCPClient(camera_ip)
    client.connect()
    client.write_reg(REG_CCP, _CCP_EXCLUSIVE)
    client.write_reg(REG_HEARTBEAT_TIMEOUT, heartbeat_ms)
    xml, _filename = fetch_genicam_xml(client)
    return client, xml
