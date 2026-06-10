import socket
import struct

import pyGigEVision.gvcp as gvcp_mod
from pyGigEVision.gvcp import GVCPClient


class _CaptureSock:
    last = None

    def __init__(self, *a):
        pass

    def setsockopt(self, *a):
        pass

    def bind(self, *a):
        pass

    def sendto(self, data, addr):
        _CaptureSock.last = (data, addr)

    def close(self):
        pass


def test_force_ip_builds_correct_packet(monkeypatch):
    monkeypatch.setattr(gvcp_mod.socket, "socket", _CaptureSock)
    # Force the single global-broadcast path so the captured dest is
    # deterministic regardless of the host's real interfaces.
    monkeypatch.setattr(gvcp_mod, "_enumerate_interfaces", lambda: [])
    GVCPClient.force_ip("aa:bb:cc:dd:ee:ff", "192.168.1.50", "255.255.255.0", "192.168.1.1")
    data, addr = _CaptureSock.last
    assert addr == ("255.255.255.255", 3956)
    key, flag, cmd, length, req = struct.unpack(">BBHHH", data[:8])
    assert req == 1
    assert key == 0x42
    assert cmd == 0x0004
    payload = data[8:]
    # FORCEIP_CMD layout per the GigE Vision spec (matches the Wireshark GVCP
    # dissector): MAC at 2, static IP at 20, subnet mask at 36, gateway at 52;
    # 56-byte payload. Fields sit in 16-byte slots after a 12-byte reserved gap.
    assert len(payload) == 56
    assert payload[2:8] == bytes.fromhex("aabbccddeeff")
    assert payload[20:24] == socket.inet_aton("192.168.1.50")
    assert payload[36:40] == socket.inet_aton("255.255.255.0")
    assert payload[52:56] == socket.inet_aton("192.168.1.1")


def test_force_ip_accepts_raw_mac_bytes(monkeypatch):
    monkeypatch.setattr(gvcp_mod.socket, "socket", _CaptureSock)
    GVCPClient.force_ip(b"\x01\x02\x03\x04\x05\x06", "10.0.0.5", "255.0.0.0")
    payload = _CaptureSock.last[0][8:]
    assert payload[2:8] == b"\x01\x02\x03\x04\x05\x06"
    assert payload[20:24] == socket.inet_aton("10.0.0.5")
    assert payload[52:56] == socket.inet_aton("0.0.0.0")


def test_force_ip_sweeps_each_interface(monkeypatch):
    """With no interface_ip, FORCEIP is sent on every enumerated NIC."""
    sent = []

    class FakeSock:
        def setsockopt(self, *a):
            pass

        def bind(self, *a):
            pass

        def sendto(self, pkt, dest):
            sent.append((pkt, dest))

        def close(self):
            pass

    monkeypatch.setattr(gvcp_mod.socket, "socket", lambda *a, **k: FakeSock())
    # Patch the SAME enumerator force_ip and discover use. It returns
    # (ip, netmask) pairs.
    monkeypatch.setattr(
        gvcp_mod,
        "_enumerate_interfaces",
        lambda: [("169.254.1.1", "255.255.0.0"), ("192.168.5.10", "255.255.255.0")],
    )
    GVCPClient.force_ip("aa:bb:cc:dd:ee:ff", "169.254.9.9", "255.255.0.0")

    # At least one FORCEIP packet per interface.
    assert len(sent) >= 2
    payload = sent[0][0][8:]  # strip 8-byte GVCP header
    assert payload[20:24] == socket.inet_aton("169.254.9.9")
    assert payload[36:40] == socket.inet_aton("255.255.0.0")


def test_force_ip_interface_ip_binds_single_nic(monkeypatch):
    """An explicit interface_ip binds and sends only on that NIC."""
    bound = []
    sent = []

    class FakeSock:
        def setsockopt(self, *a):
            pass

        def bind(self, addr):
            bound.append(addr)

        def sendto(self, pkt, dest):
            sent.append((pkt, dest))

        def close(self):
            pass

    monkeypatch.setattr(gvcp_mod.socket, "socket", lambda *a, **k: FakeSock())
    # Enumerator should NOT be consulted when interface_ip is given.
    monkeypatch.setattr(
        gvcp_mod,
        "_enumerate_interfaces",
        lambda: [("1.2.3.4", "255.0.0.0"), ("5.6.7.8", "255.0.0.0")],
    )
    GVCPClient.force_ip(
        "aa:bb:cc:dd:ee:ff", "169.254.9.9", "255.255.0.0", interface_ip="169.254.1.1"
    )
    assert bound == [("169.254.1.1", 0)]
    assert len(sent) >= 1


def test_force_ip_falls_back_to_global_broadcast(monkeypatch):
    """When enumeration yields nothing, fall back to one global broadcast."""
    monkeypatch.setattr(gvcp_mod.socket, "socket", _CaptureSock)
    monkeypatch.setattr(gvcp_mod, "_enumerate_interfaces", lambda: [])
    _CaptureSock.last = None
    GVCPClient.force_ip("aa:bb:cc:dd:ee:ff", "10.0.0.5", "255.0.0.0")
    data, addr = _CaptureSock.last
    assert addr == ("255.255.255.255", 3956)
    payload = data[8:]
    assert payload[20:24] == socket.inet_aton("10.0.0.5")
