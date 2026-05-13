"""Sanity tests for GigE Vision standard register addresses."""

from pyGigEVision import standard as std


def test_bootstrap_addresses():
    assert std.REG_CCP == 0x0A00
    assert std.REG_HEARTBEAT_TIMEOUT == 0x0938
    assert std.REG_FIRST_URL == 0x0200


def test_stream_channel_addresses():
    assert std.REG_SC_HOST_PORT == 0x0D00
    assert std.REG_SC_PACKET_SIZE == 0x0D04
    assert std.REG_SC_PACKET_DELAY == 0x0D08
    assert std.REG_SC_DEST_ADDR == 0x0D18


def test_packet_size_flag_layout():
    # Bits 15:2 = packet size; bit 1 = do-not-fragment; bit 0 = test packet
    assert std.SC_PACKET_SIZE_MASK == 0xFFFC
    assert std.SC_SCPS_DO_NOT_FRAGMENT == 1 << 1
    assert std.SC_SCPS_FIRE_TEST_PACKET == 1 << 0
