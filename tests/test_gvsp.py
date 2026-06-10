"""Unit tests for GVSP frame assembly.

Tests frame buffer logic and packet parsing without a physical camera.
"""

import time

import numpy as np

from pyGigEVision.gvsp import (
    PIXEL_BPP,
    PIXEL_DTYPE,
    PIXEL_MONO8,
    PIXEL_MONO16,
    GVSPReceiver,
    _FrameBuffer,
)


class TestFrameBuffer:
    """Test frame assembly from packets."""

    def test_empty_buffer(self):
        buf = _FrameBuffer(block_id=1)
        assert not buf.is_complete()
        assert buf.assemble() is None

    def _make_buf(self, width, height, pixel_format=PIXEL_MONO16, packet_data_size=1492):
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

    def test_assemble_writability_consistent_across_byteswap(self):
        """Both byteswap paths must return a writable array."""
        buf = self._make_buf(2, 2, packet_data_size=8)
        pixels = np.array([0x0102, 0x0304, 0x0506, 0x0708], dtype=np.uint16)
        buf.write_packet(1, pixels.tobytes())

        a = buf.assemble(byteswap=False)
        b = buf.assemble(byteswap=True)
        assert a.flags.writeable is True
        assert b.flags.writeable is True
        assert a.flags.writeable == b.flags.writeable

    def test_assemble_mono8(self):
        """Assemble Mono8 frame."""
        buf = self._make_buf(4, 2, pixel_format=PIXEL_MONO8, packet_data_size=8)

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
        np.testing.assert_array_equal(frame.ravel(), [1, 2, 3, 4, 5, 6, 7, 8])

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
        assert GVSPReceiver._contiguous_ranges([1, 2, 5, 6, 7, 10]) == [(1, 2), (5, 7), (10, 10)]

    def test_all_separate(self):
        assert GVSPReceiver._contiguous_ranges([1, 3, 5]) == [(1, 1), (3, 3), (5, 5)]


class TestReceiveLoopThrottle:
    """The per-packet gap check must be throttled to sustain line rate."""

    def test_gap_check_throttled_under_packet_flood(self):
        rx = GVSPReceiver(local_ip="127.0.0.1")
        rx._sock.close()  # drop the real bound socket; drive the loop with a fake

        calls = {"n": 0}

        def count():
            calls["n"] += 1

        rx._check_gaps_and_timeouts = count

        # 300 well-formed but inert packets (unknown packet type -> no handler
        # is invoked), then stop the loop via a single socket timeout.
        packets = [b"\x00" * 40 for _ in range(300)]

        class _FakeSock:
            def recvfrom(self, _n):
                if packets:
                    return packets.pop(0), ("127.0.0.1", 1)
                rx._stop_event.set()
                raise TimeoutError

            def close(self):
                pass

        rx._sock = _FakeSock()
        rx._receive_loop()

        # Throttled: ~300//128 = 2 checks from packets (+1 from the final
        # timeout). Without throttling this would be ~301.
        assert calls["n"] <= 5


class TestFrameLifecycle:
    """Completed frames must not accumulate in _frame_buffers."""

    def test_completed_frame_freed_after_emit(self):
        rx = GVSPReceiver(local_ip="127.0.0.1")
        try:
            rx._packet_data_size = 8
            buf = _FrameBuffer(7)
            buf.leader_received = True
            buf.pixel_format = PIXEL_MONO16
            buf.width, buf.height = 4, 2  # 16 bytes -> 2 packets of 8
            buf.setup_buffer(8)
            buf.write_packet(1, b"\x00" * 8)
            buf.write_packet(2, b"\x00" * 8)
            rx._frame_buffers[7] = buf

            rx._handle_trailer(7, b"")

            assert 7 not in rx._frame_buffers  # freed on emit
            assert rx._frame_queue.qsize() == 1  # frame emitted
        finally:
            rx.close()


class TestFrameComplete:
    """The emitted metadata exposes a ``complete`` flag."""

    def _drive_frame(self, missing_second_packet):
        rx = GVSPReceiver(local_ip="127.0.0.1")
        try:
            rx._packet_data_size = 8
            buf = _FrameBuffer(11)
            buf.leader_received = True
            buf.pixel_format = PIXEL_MONO16
            buf.width, buf.height = 4, 2  # 16 bytes -> 2 packets of 8
            buf.setup_buffer(8)
            buf.write_packet(1, b"\x00" * 8)
            if not missing_second_packet:
                buf.write_packet(2, b"\x00" * 8)
            rx._frame_buffers[11] = buf

            rx._handle_trailer(11, b"")
            _frame, info = rx._frame_queue.get_nowait()
            return info
        finally:
            rx.close()

    def test_complete_true_for_full_frame(self):
        info = self._drive_frame(missing_second_packet=False)
        assert info["missing_packets"] == 0
        assert info["complete"] is True

    def test_complete_false_for_partial_frame(self):
        info = self._drive_frame(missing_second_packet=True)
        assert info["missing_packets"] == 1
        assert info["complete"] is False


class TestPacketTimeout:
    """An in-progress frame is finalized after ``packet_timeout`` of silence."""

    def test_partial_frame_emitted_after_packet_timeout(self):
        # packet_timeout is much shorter than frame_retention, so the only way
        # this frame can be emitted is via the inter-packet wait.
        rx = GVSPReceiver(
            local_ip="127.0.0.1",
            packet_timeout=0.01,
            frame_retention=10.0,
        )
        try:
            rx._packet_data_size = 8
            buf = _FrameBuffer(13)
            buf.leader_received = True
            buf.pixel_format = PIXEL_MONO16
            buf.width, buf.height = 4, 2  # 16 bytes -> 2 packets of 8
            buf.setup_buffer(8)
            buf.write_packet(1, b"\x00" * 8)  # packet 2 never arrives
            rx._frame_buffers[13] = buf

            # Backdate so the inter-packet silence exceeds packet_timeout but
            # the much longer frame_retention has not elapsed.
            now = time.monotonic()
            buf.created_at = now - 0.5
            buf.last_packet_at = now - 0.5

            rx._check_gaps_and_timeouts()

            assert 13 not in rx._frame_buffers  # finalized and freed
            assert rx._frame_queue.qsize() == 1
            _frame, info = rx._frame_queue.get_nowait()
            assert info["complete"] is False
            assert info["missing_packets"] == 1
        finally:
            rx.close()

    def test_complete_frame_not_emitted_early_by_packet_timeout(self):
        # A frame still receiving packets within packet_timeout must not be
        # finalized prematurely.
        rx = GVSPReceiver(
            local_ip="127.0.0.1",
            packet_timeout=10.0,
            frame_retention=10.0,
        )
        try:
            rx._packet_data_size = 8
            buf = _FrameBuffer(14)
            buf.leader_received = True
            buf.pixel_format = PIXEL_MONO16
            buf.width, buf.height = 4, 2
            buf.setup_buffer(8)
            buf.write_packet(1, b"\x00" * 8)  # still in progress, recently
            rx._frame_buffers[14] = buf

            rx._check_gaps_and_timeouts()

            assert 14 in rx._frame_buffers  # not finalized
            assert rx._frame_queue.qsize() == 0
        finally:
            rx.close()


class TestResendStats:
    """Resend recovery accounting and per-download reset."""

    def test_recovered_counts_requested_packets_that_arrived(self):
        rx = GVSPReceiver(local_ip="127.0.0.1")
        try:
            rx._packet_data_size = 8
            buf = _FrameBuffer(9)
            buf.leader_received = True
            buf.pixel_format = PIXEL_MONO16
            buf.width, buf.height = 4, 2  # 2 packets
            buf.setup_buffer(8)
            # packet 1 was resend-requested and then arrived (recovered);
            # packet 2 arrived normally.
            buf._resend_requested = {1}
            buf.write_packet(1, b"\x00" * 8)
            buf.write_packet(2, b"\x00" * 8)
            rx._frame_buffers[9] = buf

            rx._handle_trailer(9, b"")

            assert rx._resend_stats["recovered"] == 1
        finally:
            rx.close()

    def test_reset_resend_stats_zeroes_counters(self):
        rx = GVSPReceiver(local_ip="127.0.0.1")
        try:
            rx._resend_stats["requested"] = 5
            rx._resend_stats["recovered"] = 2
            rx._resend_stats["failed"] = 1

            rx.reset_resend_stats()

            assert rx._resend_stats == {"requested": 0, "recovered": 0, "failed": 0}
        finally:
            rx.close()


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
