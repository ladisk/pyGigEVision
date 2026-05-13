"""Unit tests for GVSP frame assembly.

Tests frame buffer logic and packet parsing without a physical camera.
"""

import struct
import numpy as np
import pytest

from pyGigEVision.gvsp import (
    _FrameBuffer, GVSPReceiver, PIXEL_MONO16, PIXEL_MONO8,
    PIXEL_BPP, PIXEL_DTYPE, PACKET_LEADER, PACKET_DATA, PACKET_TRAILER,
)


class TestFrameBuffer:
    """Test frame assembly from packets."""

    def test_empty_buffer(self):
        buf = _FrameBuffer(block_id=1)
        assert not buf.is_complete()
        assert buf.assemble() is None

    def _make_buf(self, width, height, pixel_format=PIXEL_MONO16,
                  packet_data_size=1492):
        """Helper: create a FrameBuffer with pre-allocated buffer."""
        buf = _FrameBuffer(block_id=1)
        buf.leader_received = True
        buf.pixel_format = pixel_format
        buf.width = width
        buf.height = height
        buf.setup_buffer(packet_data_size)
        return buf

    def test_assemble_small_frame(self):
        """Assemble a 4x4 Mono16 frame from raw bytes."""
        buf = self._make_buf(4, 4, packet_data_size=32)
        buf.trailer_received = True

        pixels = np.arange(16, dtype=np.uint16)
        buf.write_packet(1, pixels.tobytes())

        frame = buf.assemble()
        assert frame is not None
        assert frame.shape == (4, 4)
        assert frame.dtype == np.uint16
        np.testing.assert_array_equal(frame.ravel(), pixels)

    def test_assemble_with_byteswap(self):
        """Byteswap should reverse byte order of each pixel."""
        buf = self._make_buf(2, 2, packet_data_size=8)

        pixels = np.array([0x0102, 0x0304, 0x0506, 0x0708], dtype=np.uint16)
        buf.write_packet(1, pixels.tobytes())

        frame_no_swap = buf.assemble(byteswap=False)
        frame_swapped = buf.assemble(byteswap=True)

        assert frame_no_swap[0, 0] != frame_swapped[0, 0]
        assert frame_swapped[0, 0] == pixels[0].byteswap()

    def test_assemble_mono8(self):
        """Assemble Mono8 frame."""
        buf = self._make_buf(4, 2, pixel_format=PIXEL_MONO8,
                             packet_data_size=8)

        pixels = np.arange(8, dtype=np.uint8)
        buf.write_packet(1, pixels.tobytes())

        frame = buf.assemble()
        assert frame.shape == (2, 4)
        assert frame.dtype == np.uint8

    def test_missing_packets_padded(self):
        """Missing data should be zero-padded."""
        # 4x4 Mono16 = 32 bytes, split into 2 packets of 16 bytes
        buf = self._make_buf(4, 4, packet_data_size=16)
        buf.trailer_received = True

        half = np.ones(8, dtype=np.uint16) * 42
        buf.write_packet(1, half.tobytes())
        # packet 2 is missing

        frame = buf.assemble()
        assert frame is not None
        assert frame.shape == (4, 4)
        assert frame.ravel()[0] == 42
        assert frame.ravel()[8] == 0  # zero-padded

    def test_multi_packet_ordering(self):
        """Packets written out of order are placed at correct offsets."""
        # 4x2 Mono16 = 16 bytes, split into 2 packets of 8 bytes
        buf = self._make_buf(4, 2, packet_data_size=8)

        part1 = np.array([1, 2, 3, 4], dtype=np.uint16)
        part2 = np.array([5, 6, 7, 8], dtype=np.uint16)

        # Insert out of order
        buf.write_packet(2, part2.tobytes())
        buf.write_packet(1, part1.tobytes())

        frame = buf.assemble()
        np.testing.assert_array_equal(
            frame.ravel(), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_is_complete(self):
        buf = self._make_buf(4, 2, packet_data_size=8)
        # 16 bytes / 8 = 2 expected packets
        assert not buf.is_complete()

        buf.trailer_received = True
        assert not buf.is_complete()

        buf.write_packet(1, b"\x00" * 8)
        assert not buf.is_complete()

        buf.write_packet(2, b"\x00" * 8)
        assert buf.is_complete()


class TestContiguousRanges:
    """Test packet ID range grouping for resend requests."""

    def test_empty(self):
        assert GVSPReceiver._contiguous_ranges([]) == []

    def test_single(self):
        assert GVSPReceiver._contiguous_ranges([5]) == [(5, 5)]

    def test_contiguous(self):
        assert GVSPReceiver._contiguous_ranges([1, 2, 3]) == [(1, 3)]

    def test_gaps(self):
        assert GVSPReceiver._contiguous_ranges([1, 2, 5, 6, 7, 10]) == [
            (1, 2), (5, 7), (10, 10)]

    def test_all_separate(self):
        assert GVSPReceiver._contiguous_ranges([1, 3, 5]) == [
            (1, 1), (3, 3), (5, 5)]


class TestPixelFormats:
    """Test pixel format definitions."""

    def test_mono16_properties(self):
        assert PIXEL_BPP[PIXEL_MONO16] == 2
        assert PIXEL_DTYPE[PIXEL_MONO16] == np.uint16

    def test_mono8_properties(self):
        assert PIXEL_BPP[PIXEL_MONO8] == 1
        assert PIXEL_DTYPE[PIXEL_MONO8] == np.uint8

    def test_all_formats_have_bpp_and_dtype(self):
        for fmt in PIXEL_BPP:
            assert fmt in PIXEL_DTYPE
