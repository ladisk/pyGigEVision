import socket
import types
from unittest.mock import patch

import pyGigEVision.gvcp as gvcp_mod
from pyGigEVision.gvcp import _enumerate_interfaces, _parse_discovery_ack, _subnet_broadcasts_for


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


def test_subnet_broadcasts_with_netmask():
    targets = _subnet_broadcasts_for("192.168.5.10", "255.255.255.0")
    assert "255.255.255.255" in targets
    assert "192.168.5.255" in targets


def test_subnet_broadcasts_without_netmask_uses_slash16():
    targets = _subnet_broadcasts_for("169.254.3.7", None)
    assert "255.255.255.255" in targets
    assert "169.254.255.255" in targets


def _standard_ack(manufacturer="ACME", model="CamX", mac=b"\x01\x02\x03\x04\x05\x06"):
    payload = bytearray(256)
    payload[0:2] = (1).to_bytes(2, "big")
    payload[2:4] = (2).to_bytes(2, "big")
    payload[10:16] = mac
    payload[48 : 48 + len(manufacturer)] = manufacturer.encode()
    payload[80 : 80 + len(model)] = model.encode()
    return b"\x00" * 8 + bytes(payload)


def test_parse_discovery_ack_standard():
    cam = _parse_discovery_ack(_standard_ack(), "192.168.5.20")
    assert cam is not None
    assert cam["ip"] == "192.168.5.20"
    assert cam["manufacturer"] == "ACME"
    assert cam["model"] == "CamX"


def test_parse_discovery_ack_too_short_returns_none():
    assert _parse_discovery_ack(b"\x00" * 20, "1.2.3.4") is None


class _FakeSock:
    responses = []

    def __init__(self, family, type_):
        self.sent = []
        self._responses = list(_FakeSock.responses)
        self.closed = False

    def setsockopt(self, *a):
        pass

    def bind(self, addr):
        self.bound = addr

    def sendto(self, data, addr):
        self.sent.append(addr)

    def settimeout(self, t):
        pass

    def recvfrom(self, n):
        if self._responses:
            return self._responses.pop(0)
        raise BlockingIOError

    def close(self):
        self.closed = True


def test_discover_enumerates_all_interfaces_and_dedupes(monkeypatch):
    ack = _standard_ack(manufacturer="ACME", model="CamX")
    _FakeSock.responses = [(ack, ("169.254.9.9", 3956))]
    monkeypatch.setattr(
        gvcp_mod,
        "_enumerate_interfaces",
        lambda: [("192.168.0.10", "255.255.255.0"), ("169.254.1.5", "255.255.0.0")],
    )
    monkeypatch.setattr(gvcp_mod.socket, "socket", _FakeSock)
    calls = {"n": 0}

    def fake_select(rlist, wlist, xlist, timeout):
        calls["n"] += 1
        return (rlist[:1], [], []) if calls["n"] == 1 else ([], [], [])

    monkeypatch.setattr(gvcp_mod.select, "select", fake_select)

    cams = gvcp_mod.GVCPClient.discover(timeout=0.2)
    assert len(cams) == 1
    assert cams[0]["ip"] == "169.254.9.9"
    assert cams[0]["model"] == "CamX"


def test_discover_sends_global_and_subnet_broadcasts(monkeypatch):
    _FakeSock.responses = []
    sent_targets = []

    class _RecordSock(_FakeSock):
        def sendto(self, data, addr):
            sent_targets.append(addr[0])

    monkeypatch.setattr(
        gvcp_mod, "_enumerate_interfaces", lambda: [("192.168.5.10", "255.255.255.0")]
    )
    monkeypatch.setattr(gvcp_mod.socket, "socket", _RecordSock)
    monkeypatch.setattr(gvcp_mod.select, "select", lambda *a: ([], [], []))
    gvcp_mod.GVCPClient.discover(timeout=0.1)
    assert "255.255.255.255" in sent_targets
    assert "192.168.5.255" in sent_targets
