"""Unit tests for GVCP protocol encoding/decoding.

These tests verify packet construction and parsing without needing
a physical camera.
"""

import socket
import struct
from unittest.mock import MagicMock

import pytest

from pyGigEVision.gvcp import (
    CMD_DISCOVERY,
    CMD_READMEM,
    CMD_READREG,
    CMD_WRITEREG,
    FLAG_ACK,
    FLAG_BROADCAST,
    GVCP_KEY,
    READMEM_CHUNK,
    REG_CCP,
    STATUS_NAMES,
    STATUS_SUCCESS,
    GVCPClient,
    GVCPError,
)


class TestGVCPPacketFormat:
    """Test GVCP packet header construction."""

    def test_header_size(self):
        """GVCP header is exactly 8 bytes."""
        header = struct.pack(">BBHHH", GVCP_KEY, FLAG_ACK, CMD_READREG, 4, 1)
        assert len(header) == 8

    def test_header_key(self):
        """First byte is always 0x42."""
        header = struct.pack(">BBHHH", GVCP_KEY, FLAG_ACK, CMD_READREG, 4, 1)
        assert header[0] == 0x42

    def test_discovery_packet(self):
        """Discovery packet: broadcast flag, zero payload."""
        pkt = struct.pack(">BBHHH", GVCP_KEY, FLAG_BROADCAST, CMD_DISCOVERY, 0, 0xFFFF)
        assert len(pkt) == 8
        assert struct.unpack(">H", pkt[2:4])[0] == CMD_DISCOVERY
        assert struct.unpack(">H", pkt[4:6])[0] == 0  # no payload

    def test_readreg_payload(self):
        """READREG payload is a 4-byte address."""
        addr = 0xD300
        payload = struct.pack(">I", addr)
        assert len(payload) == 4
        assert struct.unpack(">I", payload)[0] == addr

    def test_writereg_payload(self):
        """WRITEREG payload is address + value (8 bytes)."""
        addr = 0xD314
        value = 1
        payload = struct.pack(">II", addr, value)
        assert len(payload) == 8

    def test_readmem_payload(self):
        """READMEM payload is address + reserved + count."""
        addr = 0x0200
        size = 512
        payload = struct.pack(">IHH", addr, 0, size)
        assert len(payload) == 8

    def test_req_id_is_two_bytes(self):
        """req_id must be 2 bytes (H), not 4 bytes (I)."""
        # This was bug #1 in the original driver
        req_id = 42
        header = struct.pack(">BBHHH", GVCP_KEY, FLAG_ACK, CMD_READREG, 4, req_id)
        parsed_id = struct.unpack(">H", header[6:8])[0]
        assert parsed_id == req_id


class TestGVCPError:
    """Test error handling."""

    def test_error_with_known_status(self):
        err = GVCPError("test", 0x8006)
        assert err.status == 0x8006
        assert err.status_name == "ACCESS_DENIED"
        assert "ACCESS_DENIED" in str(err)

    def test_error_with_unknown_status(self):
        err = GVCPError("test", 0x9999)
        assert "UNKNOWN" in err.status_name

    def test_error_with_zero_status(self):
        err = GVCPError("test", 0)
        assert err.status_name == "SUCCESS"

    def test_all_known_statuses(self):
        """Every status in STATUS_NAMES has a human-readable name."""
        for _code, name in STATUS_NAMES.items():
            assert isinstance(name, str)
            assert len(name) > 0


class TestGVCPClientInit:
    """Test client initialization (no network)."""

    def test_default_init(self):
        client = GVCPClient("192.168.1.1")
        assert client.camera_ip == "192.168.1.1"
        assert client.local_ip == ""
        assert client.timeout == 2.0
        assert not client._connected

    def test_init_with_options(self):
        client = GVCPClient("10.0.0.1", local_ip="10.0.0.2", timeout=5.0)
        assert client.camera_ip == "10.0.0.1"
        assert client.local_ip == "10.0.0.2"
        assert client.timeout == 5.0

    def test_readmem_chunk_size(self):
        """READMEM chunk must be <= 512 for safe Ethernet."""
        assert READMEM_CHUNK <= 512


class TestConstants:
    """Test protocol constants."""

    def test_gvcp_port(self):
        from pyGigEVision.gvcp import GVCP_PORT

        assert GVCP_PORT == 3956

    def test_command_codes(self):
        assert CMD_DISCOVERY == 0x0002
        assert CMD_READREG == 0x0080
        assert CMD_WRITEREG == 0x0082
        assert CMD_READMEM == 0x0084


# ---------------------------------------------------------------------------
# Tests for _send_cmd robustness (ACK ID validation, retries, PENDING_ACK)
# ---------------------------------------------------------------------------


def _make_ack(
    status: int, ack_cmd: int, payload_len: int, ack_id: int, extra: bytes = b""
) -> bytes:
    """Build a raw GVCP ACK packet."""
    return struct.pack(">HHHH", status, ack_cmd, payload_len, ack_id) + extra


def _make_readreg_ack(ack_id: int, value: int, status: int = STATUS_SUCCESS) -> bytes:
    """Build a READREG_ACK with a 4-byte register value."""
    return _make_ack(status, CMD_READREG | 0x0001, 4, ack_id, struct.pack(">I", value))


def _make_writereg_ack(ack_id: int, status: int = STATUS_SUCCESS) -> bytes:
    """Build a WRITEREG_ACK (no extra payload)."""
    return _make_ack(status, CMD_WRITEREG | 0x0001, 0, ack_id)


def _client_with_mock_socket() -> GVCPClient:
    """Return a GVCPClient with a mock socket (no real network)."""
    client = GVCPClient("192.168.1.1")
    client._sock = MagicMock()
    client._req_id = 0  # _next_id will return 1 first
    # Fast timeouts for testing
    client._cmd_timeout = 0.1
    client._n_retries = 3
    return client


class TestSendCmdAckValidation:
    """Test _send_cmd ACK ID matching and stale packet discard."""

    def test_normal_read_reg(self):
        """Normal READREG: matching ack_id is accepted."""
        client = _client_with_mock_socket()
        ack = _make_readreg_ack(ack_id=1, value=0xDEADBEEF)
        client._sock.recvfrom = MagicMock(return_value=(ack, ("192.168.1.1", 3956)))

        result = client._read_reg_raw(0xD300)
        assert result == 0xDEADBEEF

    def test_normal_write_reg(self):
        """Normal WRITEREG: matching ack_id is accepted."""
        client = _client_with_mock_socket()
        ack = _make_writereg_ack(ack_id=1)
        client._sock.recvfrom = MagicMock(return_value=(ack, ("192.168.1.1", 3956)))

        # Should not raise
        client._write_reg_raw(0xD300, 42)

    def test_stale_ack_discarded(self):
        """Stale ACK (wrong ack_id) is discarded, correct one accepted."""
        client = _client_with_mock_socket()
        stale_ack = _make_readreg_ack(ack_id=99, value=0xBAAAAAAD)
        good_ack = _make_readreg_ack(ack_id=1, value=0x12345678)
        client._sock.recvfrom = MagicMock(
            side_effect=[
                (stale_ack, ("192.168.1.1", 3956)),
                (good_ack, ("192.168.1.1", 3956)),
            ]
        )

        result = client._read_reg_raw(0xD300)
        assert result == 0x12345678
        assert client._sock.recvfrom.call_count == 2

    def test_multiple_stale_acks_discarded(self):
        """Multiple stale ACKs before the correct one."""
        client = _client_with_mock_socket()
        stale1 = _make_readreg_ack(ack_id=50, value=0x11111111)
        stale2 = _make_readreg_ack(ack_id=51, value=0x22222222)
        good = _make_readreg_ack(ack_id=1, value=0xCAFECAFE)
        client._sock.recvfrom = MagicMock(
            side_effect=[
                (stale1, ("192.168.1.1", 3956)),
                (stale2, ("192.168.1.1", 3956)),
                (good, ("192.168.1.1", 3956)),
            ]
        )

        result = client._read_reg_raw(0xD300)
        assert result == 0xCAFECAFE
        assert client._sock.recvfrom.call_count == 3

    def test_runt_packet_ignored(self):
        """Packets shorter than 8 bytes are ignored."""
        client = _client_with_mock_socket()
        runt = b"\x00\x00\x00"  # 3 bytes — too short
        good = _make_readreg_ack(ack_id=1, value=42)
        client._sock.recvfrom = MagicMock(
            side_effect=[
                (runt, ("192.168.1.1", 3956)),
                (good, ("192.168.1.1", 3956)),
            ]
        )

        result = client._read_reg_raw(0xD300)
        assert result == 42


class TestSendCmdTimeout:
    """Test retry and timeout behavior."""

    def test_timeout_raises_after_retries(self):
        """After _n_retries timeouts, GVCPError is raised."""
        client = _client_with_mock_socket()
        client._n_retries = 2
        client._cmd_timeout = 0.05
        client._sock.recvfrom = MagicMock(side_effect=socket.timeout)

        with pytest.raises(GVCPError, match="Timeout"):
            client._read_reg_raw(0xD300)

        # sendto called once per retry
        assert client._sock.sendto.call_count == 2

    def test_retry_succeeds_on_second_attempt(self):
        """First attempt times out, second attempt gets an ACK."""
        client = _client_with_mock_socket()
        client._n_retries = 3
        client._cmd_timeout = 0.05
        # req_id will be 1 for the first call to _next_id (only called once
        # since _send_cmd calls it at the top, before the retry loop)
        good_ack = _make_readreg_ack(ack_id=1, value=0xABCD)

        # First recvfrom: timeout, second: success
        client._sock.recvfrom = MagicMock(
            side_effect=[
                socket.timeout,
                (good_ack, ("192.168.1.1", 3956)),
            ]
        )

        result = client._read_reg_raw(0xD300)
        assert result == 0xABCD

    def test_error_status_raises(self):
        """Non-SUCCESS status in matching ACK raises GVCPError."""
        client = _client_with_mock_socket()
        ack = _make_readreg_ack(ack_id=1, value=0, status=0x8006)
        client._sock.recvfrom = MagicMock(return_value=(ack, ("192.168.1.1", 3956)))

        with pytest.raises(GVCPError, match="ACCESS_DENIED"):
            client._read_reg_raw(0xD300)


class TestSendCmdPendingAck:
    """Test PENDING_ACK handling."""

    def test_pending_ack_extends_deadline(self):
        """PENDING_ACK (0x0089) extends the wait, then real ACK arrives."""
        client = _client_with_mock_socket()
        client._cmd_timeout = 0.1

        # PENDING_ACK: ack_cmd=0x0089, extra 4 bytes = timeout in ms
        pending_timeout_ms = 2000
        pending_ack = _make_ack(STATUS_SUCCESS, 0x0089, 4, 0, struct.pack(">I", pending_timeout_ms))

        good_ack = _make_readreg_ack(ack_id=1, value=0x42)

        client._sock.recvfrom = MagicMock(
            side_effect=[
                (pending_ack, ("192.168.1.1", 3956)),
                (good_ack, ("192.168.1.1", 3956)),
            ]
        )

        result = client._read_reg_raw(0xD300)
        assert result == 0x42


class TestHeartbeatControlLoss:
    """Test heartbeat control-loss detection."""

    def test_init_control_lost_is_false(self):
        client = GVCPClient("192.168.1.1")
        assert client._control_lost is False

    def test_control_lost_detected(self):
        """If CCP read returns 0 (control bit cleared), flag is set."""
        client = _client_with_mock_socket()
        client._connected = True
        client._control_lost = False

        # Simulate CCP register returning 0 (no control)
        ack = _make_readreg_ack(ack_id=1, value=0x00000000)
        client._sock.recvfrom = MagicMock(return_value=(ack, ("192.168.1.1", 3956)))

        # Call _read_reg_raw directly to simulate what heartbeat does
        with client._lock:
            value = client._read_reg_raw(REG_CCP)
        if (value & 0x02) == 0:
            client._control_lost = True

        assert client._control_lost is True

    def test_control_still_held(self):
        """If CCP read returns 0x02 (control bit set), flag stays False."""
        client = _client_with_mock_socket()
        client._connected = True
        client._control_lost = False

        ack = _make_readreg_ack(ack_id=1, value=0x00000002)
        client._sock.recvfrom = MagicMock(return_value=(ack, ("192.168.1.1", 3956)))

        with client._lock:
            value = client._read_reg_raw(REG_CCP)
        if (value & 0x02) == 0:
            client._control_lost = True

        assert client._control_lost is False

    def test_retry_config_defaults(self):
        """New init attributes have correct defaults."""
        client = GVCPClient("192.168.1.1")
        assert client._n_retries == 3
        assert client._cmd_timeout == 0.5
