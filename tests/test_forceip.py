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

    def sendto(self, data, addr):
        _CaptureSock.last = (data, addr)

    def close(self):
        pass


def test_force_ip_builds_correct_packet(monkeypatch):
    monkeypatch.setattr(gvcp_mod.socket, "socket", _CaptureSock)
    GVCPClient.force_ip("aa:bb:cc:dd:ee:ff", "192.168.1.50", "255.255.255.0", "192.168.1.1")
    data, addr = _CaptureSock.last
    assert addr == ("255.255.255.255", 3956)
    key, flag, cmd, length, req = struct.unpack(">BBHHH", data[:8])
    assert key == 0x42
    assert cmd == 0x0004
    payload = data[8:]
    assert len(payload) == 64
    assert payload[2:8] == bytes.fromhex("aabbccddeeff")
    assert payload[24:28] == socket.inet_aton("192.168.1.50")
    assert payload[44:48] == socket.inet_aton("255.255.255.0")
    assert payload[60:64] == socket.inet_aton("192.168.1.1")


def test_force_ip_accepts_raw_mac_bytes(monkeypatch):
    monkeypatch.setattr(gvcp_mod.socket, "socket", _CaptureSock)
    GVCPClient.force_ip(b"\x01\x02\x03\x04\x05\x06", "10.0.0.5", "255.0.0.0")
    payload = _CaptureSock.last[0][8:]
    assert payload[2:8] == b"\x01\x02\x03\x04\x05\x06"
    assert payload[60:64] == socket.inet_aton("0.0.0.0")
