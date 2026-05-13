"""
GigE Vision Streaming Protocol (GVSP) receiver.

Receives image frames streamed from a GigE Vision camera over UDP.
The camera sends frames as a sequence of packets:
  - Leader packet: image metadata (dimensions, pixel format, timestamp)
  - Data packets: raw pixel data chunks
  - Trailer packet: signals frame complete

This module is generic — it works with any GigE Vision camera.
Byte order is configurable (byte order varies by vendor — set the appropriate
value at construction).

Implements aravis-inspired improvements:
  - Pre-allocated frame buffers (direct offset writes, no dict+sort)
  - Real-time gap detection on every received packet
  - Packet resend sent directly from the stream socket (not GVCP)
  - Three-tier timeouts: initial gap grace, resend interval, frame retention
"""

import logging
import math
import socket
import struct
import threading
import time
from queue import Queue, Empty
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# GVSP packet types
PACKET_LEADER = 0x01
PACKET_TRAILER = 0x02
PACKET_DATA = 0x03

# Leader payload type IDs
PAYLOAD_IMAGE = 0x0001

# Standard pixel format codes (GenICam PFNC)
PIXEL_MONO8 = 0x01080001
PIXEL_MONO16 = 0x01100007
PIXEL_MONO10 = 0x01100003
PIXEL_MONO12 = 0x01100005
PIXEL_MONO14 = 0x01100025

PIXEL_BPP = {
    PIXEL_MONO8: 1,
    PIXEL_MONO10: 2,
    PIXEL_MONO12: 2,
    PIXEL_MONO14: 2,
    PIXEL_MONO16: 2,
}

PIXEL_DTYPE = {
    PIXEL_MONO8: np.uint8,
    PIXEL_MONO10: np.uint16,
    PIXEL_MONO12: np.uint16,
    PIXEL_MONO14: np.uint16,
    PIXEL_MONO16: np.uint16,
}

# GVCP constants for direct resend from stream socket
_GVCP_PORT = 3956
_GVCP_KEY = 0x42
_GVCP_FLAG_ACK = 0x01
_GVCP_CMD_PACKETRESEND = 0x0040


class _FrameBuffer:
    """Accumulates packets for a single frame using a pre-allocated buffer."""

    def __init__(self, block_id: int):
        self.block_id = block_id
        self.timestamp = 0
        self.pixel_format = 0
        self.width = 0
        self.height = 0
        self.payload_type = 0
        self.leader_received = False
        self.trailer_received = False
        self.expected_packets = 0
        self.created_at = time.monotonic()
        self.last_packet_at = time.monotonic()

        # Pre-allocated buffer (set up when leader arrives and we know size)
        self._raw_buffer: Optional[bytearray] = None
        self._received: Optional[bytearray] = None  # bitfield: 1=received
        self._last_contiguous = 0  # highest contiguous packet from start
        self._received_count = 0
        self._packet_data_size = 0

        # Resend tracking per-packet
        self._resend_requested: set[int] = set()

    def setup_buffer(self, packet_data_size: int):
        """Allocate frame buffer once dimensions are known."""
        if self.width <= 0 or self.height <= 0:
            return

        MAX_PIXELS = 2048 * 2048
        if self.width * self.height > MAX_PIXELS:
            logger.warning(f"Frame {self.block_id}: invalid dimensions "
                           f"{self.width}x{self.height}, skipping")
            return

        bpp = PIXEL_BPP.get(self.pixel_format, 2)
        total_bytes = self.width * self.height * bpp
        self.expected_packets = math.ceil(total_bytes / packet_data_size)
        self._packet_data_size = packet_data_size
        self._raw_buffer = bytearray(total_bytes)
        self._received = bytearray(self.expected_packets + 1)  # 0-indexed unused
        self._last_contiguous = 0
        self._received_count = 0

    def write_packet(self, packet_id: int, payload: bytes):
        """Write a data packet directly to the correct buffer offset."""
        self.last_packet_at = time.monotonic()

        if self._raw_buffer is not None and self._packet_data_size > 0:
            # Auto-detect actual payload size from first full packet.
            # The assumed _packet_data_size (packet_size - 8) may differ
            # from actual payloads due to extended GVSP headers.
            if (packet_id == 1 and len(payload) != self._packet_data_size
                    and len(payload) > 0):
                self._packet_data_size = len(payload)
                bpp = PIXEL_BPP.get(self.pixel_format, 2)
                total_bytes = self.width * self.height * bpp
                self.expected_packets = math.ceil(
                    total_bytes / self._packet_data_size)
                self._received = bytearray(self.expected_packets + 1)

            offset = (packet_id - 1) * self._packet_data_size
            end = min(offset + len(payload), len(self._raw_buffer))
            if offset < len(self._raw_buffer):
                self._raw_buffer[offset:end] = payload[:end - offset]
            if packet_id <= len(self._received) - 1:
                if not self._received[packet_id]:
                    self._received[packet_id] = 1
                    self._received_count += 1
                    if packet_id == self._last_contiguous + 1:
                        while (self._last_contiguous + 1 < len(self._received)
                               and self._received[self._last_contiguous + 1]):
                            self._last_contiguous += 1

    def missing_packets(self) -> list[int]:
        """Return list of missing packet IDs (gaps in received set)."""
        if self._received is None or self.expected_packets == 0:
            return []
        return [i for i in range(1, self.expected_packets + 1)
                if not self._received[i]]

    def is_complete(self) -> bool:
        if not self.leader_received or not self.trailer_received:
            return False
        if self.expected_packets > 0:
            return self._received_count >= self.expected_packets
        return True

    def assemble(self, byteswap: bool = False) -> Optional[np.ndarray]:
        """Assemble the frame from the pre-allocated buffer."""
        if not self.leader_received:
            return None

        if self.width <= 0 or self.height <= 0:
            return None

        MAX_PIXELS = 2048 * 2048
        if self.width * self.height > MAX_PIXELS:
            return None

        bpp = PIXEL_BPP.get(self.pixel_format, 2)
        dtype = PIXEL_DTYPE.get(self.pixel_format, np.uint16)
        expected_size = self.width * self.height * bpp

        if self._raw_buffer is not None:
            raw = bytes(self._raw_buffer[:expected_size])
        else:
            raw = b"\x00" * expected_size

        arr = np.frombuffer(raw, dtype=dtype)

        if byteswap:
            arr = arr.byteswap()

        try:
            return arr.reshape((self.height, self.width))
        except ValueError:
            return arr


class GVSPReceiver:
    """Receives GVSP image frames on a UDP socket.

    Args:
        local_ip: Local IP to bind to.
        local_port: Local UDP port (0 = auto-assign).
        max_queue: Max completed frames to buffer.
        gvcp_client: Optional GVCPClient (used for camera_ip only).
        packet_size: Network packet size (default 1500 = standard MTU).
        byteswap: Swap pixel byte order after reception (vendor-dependent).
        camera_ip: Camera IP for direct resend (auto-detected from gvcp_client).
        initial_packet_timeout: Grace period before first resend (seconds).
        packet_timeout: Timeout between resend attempts (seconds).
        frame_retention: Max time to keep an incomplete frame (seconds).
    """

    def __init__(self, local_ip: str = "", local_port: int = 0,
                 max_queue: int = 30,
                 gvcp_client=None, packet_size: int = 1500,
                 byteswap: bool = False, camera_ip: str = "",
                 initial_packet_timeout: float = 0.005,
                 packet_timeout: float = 0.020,
                 frame_retention: float = 0.200):
        self.local_ip = local_ip
        self.byteswap = byteswap
        self._gvcp = gvcp_client
        self._packet_data_size = packet_size - 8
        self._camera_ip = camera_ip or (gvcp_client.camera_ip if gvcp_client else "")

        # Three-tier timeout strategy (aravis-inspired)
        self._initial_packet_timeout = initial_packet_timeout
        self._packet_timeout = packet_timeout
        self._frame_retention = frame_retention

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF,
                                  16 * 1024 * 1024)
        except OSError:
            pass
        self._sock.bind((local_ip, local_port))
        self._sock.settimeout(0.05)  # short timeout for responsive gap checking

        self._port = self._sock.getsockname()[1]
        self._frame_queue: Queue = Queue(maxsize=max_queue)
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._frame_buffers: dict[int, _FrameBuffer] = {}
        self._resend_stats = {"requested": 0, "recovered": 0, "failed": 0}
        self.resend_enabled = True

        # Resend req_id counter (for direct resend from stream socket)
        self._resend_req_id = 0

    @property
    def port(self) -> int:
        """UDP port the receiver is bound to."""
        return self._port

    def start(self):
        """Start the receiver thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the receiver thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._frame_buffers.clear()

    def close(self):
        """Stop and close the socket."""
        self.stop()
        self._sock.close()

    def get_frame(self, timeout: float = 5.0) -> Optional[np.ndarray]:
        """Block until a frame is available, return as numpy array."""
        result = self.get_frame_with_info(timeout)
        if result is None:
            return None
        return result[0]

    def get_frame_with_info(self, timeout: float = 5.0
                            ) -> Optional[tuple[np.ndarray, dict]]:
        """Block until a frame is available, return (array, metadata)."""
        try:
            return self._frame_queue.get(timeout=timeout)
        except Empty:
            return None

    # --- Internal ---

    def _receive_loop(self):
        """Main receiver loop with real-time gap detection."""
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(65536)
            except socket.timeout:
                # No packet received — check for gaps and stale frames
                self._check_gaps_and_timeouts()
                continue
            except OSError:
                break

            if len(data) < 8:
                continue

            self._parse_packet(data)

            # Check gaps on every packet (aravis pattern)
            self._check_gaps_and_timeouts()

    def _parse_packet(self, data: bytes):
        """Parse a single GVSP packet."""
        status = struct.unpack(">H", data[0:2])[0]
        format_byte = data[4]
        # Bit 7 of byte 4 = bit 31 of packet_infos = extended ID flag
        extended = bool(format_byte & 0x80)

        if extended:
            # Extended header (GigE Vision 2.x):
            #   [0:2]  status, [2:4] block_id_high, [4:8] packet_infos,
            #   [8:16] block_id_64, [16:20] packet_id_32
            if len(data) < 20:
                return
            packet_infos = struct.unpack(">I", data[4:8])[0]
            packet_type = (packet_infos >> 24) & 0x0F
            block_id = struct.unpack(">Q", data[8:16])[0]
            packet_id = struct.unpack(">I", data[16:20])[0]
            header_size = 20
        else:
            block_id = struct.unpack(">H", data[2:4])[0]
            packet_type = format_byte & 0x07
            packet_id = (data[5] << 16) | (data[6] << 8) | data[7]
            header_size = 8

        payload = data[header_size:]

        if packet_type == PACKET_LEADER:
            self._handle_leader(block_id, payload)
        elif packet_type == PACKET_DATA:
            self._handle_data(block_id, packet_id, payload)
        elif packet_type == PACKET_TRAILER:
            self._handle_trailer(block_id, payload)

    def _handle_leader(self, block_id: int, payload: bytes):
        """Parse leader packet and pre-allocate frame buffer."""
        buf = _FrameBuffer(block_id)

        if len(payload) >= 24:
            buf.payload_type = struct.unpack(">H", payload[2:4])[0]
            buf.timestamp = struct.unpack(">Q", payload[4:12])[0]
            buf.pixel_format = struct.unpack(">I", payload[12:16])[0]
            buf.width = struct.unpack(">I", payload[16:20])[0]
            buf.height = struct.unpack(">I", payload[20:24])[0]

        buf.leader_received = True
        buf.setup_buffer(self._packet_data_size)
        self._frame_buffers[block_id] = buf

    _MAX_CONCURRENT_FRAMES = 100

    def _handle_data(self, block_id: int, packet_id: int, payload: bytes):
        """Write data packet directly to pre-allocated frame buffer."""
        if block_id not in self._frame_buffers:
            if len(self._frame_buffers) >= self._MAX_CONCURRENT_FRAMES:
                oldest = min(self._frame_buffers,
                             key=lambda k: self._frame_buffers[k].created_at)
                self._frame_buffers.pop(oldest, None)
            self._frame_buffers[block_id] = _FrameBuffer(block_id)
        self._frame_buffers[block_id].write_packet(packet_id, payload)

    def _handle_trailer(self, block_id: int, payload: bytes):
        """Handle trailer packet, emit completed frame."""
        if block_id not in self._frame_buffers:
            return

        buf = self._frame_buffers[block_id]
        buf.trailer_received = True

        # If we didn't get a leader (no pre-allocated buffer), calculate
        # expected packets now for the missing count
        if buf.expected_packets == 0 and buf.leader_received:
            if buf.width > 0 and buf.height > 0:
                bpp = PIXEL_BPP.get(buf.pixel_format, 2)
                total_bytes = buf.width * buf.height * bpp
                buf.expected_packets = math.ceil(
                    total_bytes / self._packet_data_size)

        # Log missing packets
        missing = buf.missing_packets()
        if missing:
            self._resend_stats["failed"] += len(missing)
            logger.warning(
                f"Frame {block_id}: {len(missing)}/{buf.expected_packets} "
                f"packets unrecoverable")

        # Assemble and emit
        self._emit_frame(buf)

    def _emit_frame(self, buf: _FrameBuffer):
        """Assemble frame and put it on the output queue."""
        frame = buf.assemble(byteswap=self.byteswap)
        if frame is not None:
            info = {
                "block_id": buf.block_id,
                "timestamp": buf.timestamp,
                "pixel_format": buf.pixel_format,
                "width": buf.width,
                "height": buf.height,
                "missing_packets": max(0,
                    buf.expected_packets - buf._received_count
                    if buf.expected_packets > 0 else 0),
            }
            if self._frame_queue.full():
                try:
                    self._frame_queue.get_nowait()
                except Empty:
                    pass
            self._frame_queue.put((frame, info))

        self._frame_buffers.pop(buf.block_id, None)

    def _check_gaps_and_timeouts(self):
        """Real-time gap detection and frame retention timeout.

        Called on every received packet and on socket timeouts.
        - Requests resend for packets missing longer than initial_packet_timeout
        - Emits or drops frames older than frame_retention
        """
        now = time.monotonic()
        to_remove = []

        for block_id, buf in list(self._frame_buffers.items()):
            age = now - buf.created_at
            since_last = now - buf.last_packet_at

            # Frame retention timeout — emit whatever we have
            if since_last > self._frame_retention and buf.leader_received:
                if buf.trailer_received or age > self._frame_retention * 2:
                    self._emit_frame(buf)
                    to_remove.append(block_id)
                    continue

            # Real-time gap detection — request resend for missing packets
            if (self.resend_enabled and self._camera_ip
                    and buf.leader_received and buf.expected_packets > 0
                    and age > self._initial_packet_timeout):
                missing = buf.missing_packets()
                # Only resend packets we haven't already requested
                new_missing = [p for p in missing
                               if p not in buf._resend_requested]
                if new_missing:
                    # Cap at 25% of frame packets per request (aravis default)
                    max_resend = max(1, buf.expected_packets // 4)
                    to_resend = new_missing[:max_resend]
                    self._send_resend_direct(block_id, to_resend)
                    buf._resend_requested.update(to_resend)

            # Hard timeout — drop frame
            if age > self._frame_retention * 5:
                to_remove.append(block_id)

        for bid in to_remove:
            self._frame_buffers.pop(bid, None)

    def _send_resend_direct(self, block_id: int, packet_ids: list[int]):
        """Send PACKETRESEND directly from the stream socket.

        Sends to camera's GVCP port (3956) from the stream socket,
        avoiding the GVCP client lock. This is the aravis approach.
        """
        if not packet_ids:
            return

        ranges = self._contiguous_ranges(packet_ids)
        for first, last in ranges:
            self._resend_req_id = (self._resend_req_id + 1) & 0xFFFF
            if self._resend_req_id == 0:
                self._resend_req_id = 1

            payload = struct.pack(">HHII", 0, block_id, first, last)
            header = struct.pack(">BBHHH", _GVCP_KEY, _GVCP_FLAG_ACK,
                                 _GVCP_CMD_PACKETRESEND,
                                 len(payload), self._resend_req_id)
            try:
                self._sock.sendto(header + payload,
                                  (self._camera_ip, _GVCP_PORT))
                self._resend_stats["requested"] += (last - first + 1)
            except OSError:
                pass

    @staticmethod
    def _contiguous_ranges(ids: list[int]) -> list[tuple[int, int]]:
        """Group sorted packet IDs into contiguous (first, last) ranges."""
        if not ids:
            return []
        ids = sorted(ids)
        ranges = []
        first = last = ids[0]
        for pid in ids[1:]:
            if pid == last + 1:
                last = pid
            else:
                ranges.append((first, last))
                first = last = pid
        ranges.append((first, last))
        return ranges
