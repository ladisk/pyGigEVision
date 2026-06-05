import socket
import types
from unittest.mock import patch

from pyGigEVision.gvcp import _enumerate_interfaces


def _snic(addr, netmask, family=socket.AF_INET):
    return types.SimpleNamespace(
        family=family, address=addr, netmask=netmask, broadcast=None, ptp=None
    )


def _stats(isup):
    return types.SimpleNamespace(isup=isup, duplex=0, speed=1000, mtu=1500, flags="")


def test_enumerate_interfaces_returns_up_ipv4_non_loopback():
    addrs = {
        "eth0": [_snic("192.168.0.10", "255.255.255.0")],
        "usb0": [_snic("169.254.1.5", "255.255.0.0")],
        "lo": [_snic("127.0.0.1", "255.0.0.0")],
        "down0": [_snic("10.0.0.5", "255.255.255.0")],
    }
    stats = {"eth0": _stats(True), "usb0": _stats(True), "lo": _stats(True), "down0": _stats(False)}
    with (
        patch("psutil.net_if_addrs", return_value=addrs),
        patch("psutil.net_if_stats", return_value=stats),
    ):
        out = _enumerate_interfaces()
    assert ("192.168.0.10", "255.255.255.0") in out
    assert ("169.254.1.5", "255.255.0.0") in out
    assert all(not ip.startswith("127.") for ip, _ in out)
    assert all(ip != "10.0.0.5" for ip, _ in out)
