"""GigE Vision Streaming Protocol (GVSP) receiver.

Receives image frames pushed by a camera over UDP as a sequence of
packets:

* Leader packet: image metadata (dimensions, pixel format, timestamp).
* Data packets: raw pixel data chunks.
* Trailer packet: frame complete signal.

The :class:`GVSPReceiver` runs a background thread that reassembles
packets into pre-allocated NumPy buffers, detects gaps in packet
sequence numbers, requests resends directly via the receive socket
(bypassing the GVCP control channel for lower latency), and pushes
completed frames onto a thread-safe queue.

Byte order is configurable via the ``byteswap`` constructor parameter
(set ``True`` when the camera sends data in the opposite endianness
from the host; vendor-dependent).

Notes
-----
Implements aravis-inspired patterns: pre-allocated frame buffers
(direct offset writes, no dict-and-sort assembly), real-time gap
detection on every received packet, three-tier timeouts (initial gap
grace, resend interval, frame retention).

See Also
--------
pyGigEVision.gvcp : The control counterpart (GVCP).
"""

from __future__ import annotations

import contextlib
import logging
import math
import socket
import struct
import threading
import time
from queue import Empty, Queue

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
    """Accumulate packets for a single in-flight frame.

    Internal to :mod:`pyGigEVision.gvsp`.  One ``_FrameBuffer`` is created
    per block ID when its leader packet arrives (or, for data-before-leader
    arrivals, on the first data packet).  The raw image data is stored in a
    pre-allocated :class:`bytearray` so every data packet is written with a
    single slice assignment, with no temporary buffers or sort step.

    Parameters
    ----------
    block_id : int
        GVSP block identifier for this frame.
    """

    def __init__(self, block_id: int) -> None:
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
        self._raw_buffer: bytearray | None = None
        self._received: bytearray | None = None  # bitfield: 1=received
        self._last_contiguous = 0  # highest contiguous packet from start
        self._received_count = 0
        self._packet_data_size = 0

        # Resend tracking per-packet
        self._resend_requested: set[int] = set()

    def setup_buffer(self, packet_data_size: int) -> None:
        """Allocate the frame buffer once image dimensions are known.

        Parameters
        ----------
        packet_data_size : int
            Expected data payload size per packet (bytes), used to compute
            the packet count and per-packet buffer offsets.
        """
        if self.width <= 0 or self.height <= 0:
            return

        max_pixels = 2048 * 2048
        if self.width * self.height > max_pixels:
            logger.warning(
                f"Frame {self.block_id}: invalid dimensions {self.width}x{self.height}, skipping"
            )
            return

        bpp = PIXEL_BPP.get(self.pixel_format, 2)
        total_bytes = self.width * self.height * bpp
        self.expected_packets = math.ceil(total_bytes / packet_data_size)
        self._packet_data_size = packet_data_size
        self._raw_buffer = bytearray(total_bytes)
        self._received = bytearray(self.expected_packets + 1)  # 0-indexed unused
        self._last_contiguous = 0
        self._received_count = 0

    def write_packet(self, packet_id: int, payload: bytes) -> None:
        """Write a data packet directly to the correct buffer offset."""
        self.last_packet_at = time.monotonic()

        if self._raw_buffer is not None and self._packet_data_size > 0:
            # Auto-detect actual payload size from first full packet.
            # The assumed _packet_data_size (packet_size - 8) may differ
            # from actual payloads due to extended GVSP headers.
            if packet_id == 1 and len(payload) != self._packet_data_size and len(payload) > 0:
                self._packet_data_size = len(payload)
                bpp = PIXEL_BPP.get(self.pixel_format, 2)
                total_bytes = self.width * self.height * bpp
                self.expected_packets = math.ceil(total_bytes / self._packet_data_size)
                self._received = bytearray(self.expected_packets + 1)

            offset = (packet_id - 1) * self._packet_data_size
            end = min(offset + len(payload), len(self._raw_buffer))
            if offset < len(self._raw_buffer):
                self._raw_buffer[offset:end] = payload[: end - offset]
            if packet_id <= len(self._received) - 1 and not self._received[packet_id]:
                self._received[packet_id] = 1
                self._received_count += 1
                if packet_id == self._last_contiguous + 1:
                    while (
                        self._last_contiguous + 1 < len(self._received)
                        and self._received[self._last_contiguous + 1]
                    ):
                        self._last_contiguous += 1

    def missing_packets(self) -> list[int]:
        """Return list of missing packet IDs (gaps in received set)."""
        if self._received is None or self.expected_packets == 0:
            return []
        return [i for i in range(1, self.expected_packets + 1) if not self._received[i]]

    def is_complete(self) -> bool:
        """Return ``True`` when leader, trailer, and all data packets are received."""
        if not self.leader_received or not self.trailer_received:
            return False
        if self.expected_packets > 0:
            return self._received_count >= self.expected_packets
        return True

    def assemble(self, byteswap: bool = False) -> np.ndarray | None:
        """Assemble the frame from the pre-allocated buffer.

        Parameters
        ----------
        byteswap : bool, optional
            Swap the byte order of each pixel after assembly.  Default is
            ``False``.

        Returns
        -------
        numpy.ndarray or None
            2-D array of shape ``(height, width)`` with the appropriate
            ``dtype`` from :data:`PIXEL_DTYPE`, or ``None`` if the leader
            has not been received or the dimensions are invalid.
        """
        if not self.leader_received:
            return None

        if self.width <= 0 or self.height <= 0:
            return None

        max_pixels = 2048 * 2048
        if self.width * self.height > max_pixels:
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
    """Receive GVSP image frames on a UDP socket.

    Binds a UDP socket on the given *local_ip*/*local_port*, starts a
    background thread that reassembles GVSP packets into NumPy arrays, and
    exposes a thread-safe queue via :meth:`get_frame` / :meth:`get_frame_with_info`.

    Packet resends are sent directly from the stream socket to the camera's
    GVCP port (3956), bypassing any :class:`~pyGigEVision.gvcp.GVCPClient`
    lock, which keeps the control channel free for register reads during
    acquisition.

    Parameters
    ----------
    local_ip : str, optional
        Local interface IPv4 address to bind to, e.g. ``"169.254.0.1"``.
        Empty string (default) lets the OS choose.
    local_port : int, optional
        Local UDP port to bind to.  ``0`` (default) asks the OS to
        assign a free port; read back via the :attr:`port` property.
    max_queue : int, optional
        Maximum number of completed frames to hold in the internal queue
        before the oldest is discarded.  Default is ``30``.
    gvcp_client : GVCPClient or None, optional
        If provided, ``camera_ip`` is read from ``gvcp_client.camera_ip``
        when *camera_ip* is empty.  The client is not otherwise used.
    packet_size : int, optional
        Expected network packet size in bytes (Ethernet MTU).  The data
        payload per packet is ``packet_size - 8``.  Default is ``1500``
        (standard Ethernet MTU).
    byteswap : bool, optional
        Swap the byte order of each pixel after assembly.  Set to ``True``
        when the camera sends data in the opposite endianness from the host.
        Default is ``False``.
    camera_ip : str, optional
        IPv4 address of the camera, used as the destination for direct
        resend requests.  Falls back to ``gvcp_client.camera_ip`` when
        *gvcp_client* is supplied.  Leave empty to disable resends.
    initial_packet_timeout : float, optional
        Grace period in seconds before the first resend request is issued
        for a gap.  Default is ``0.005``.
    packet_timeout : float, optional
        Interval in seconds between successive resend attempts for the
        same gap.  Default is ``0.020``.
    frame_retention : float, optional
        Maximum time in seconds to keep an incomplete frame before emitting
        it with whatever data arrived.  Default is ``0.200``.

    Notes
    -----
    The constructor binds the socket immediately.  Call :meth:`start` to
    launch the background receiver thread.

    The receiver is not thread-safe for concurrent calls to :meth:`start`,
    :meth:`stop`, or :meth:`close`; those should be called from a single
    controlling thread.  :meth:`get_frame` and :meth:`get_frame_with_info`
    are safe to call from any thread.

    Examples
    --------
    Minimal usage, receiving one frame::

        receiver = GVSPReceiver(local_ip="169.254.0.1", camera_ip="169.254.67.34")
        receiver.start()
        # ... configure camera to stream to receiver.port ...
        frame = receiver.get_frame(timeout=5.0)
        receiver.stop()

    Context-manager style (using :meth:`close` after ``stop``)::

        receiver = GVSPReceiver(local_ip="169.254.0.1")
        receiver.start()
        try:
            frame, info = receiver.get_frame_with_info(timeout=10.0)
        finally:
            receiver.stop()
            receiver.close()
    """

    def __init__(
        self,
        local_ip: str = "",
        local_port: int = 0,
        max_queue: int = 30,
        gvcp_client: object | None = None,
        packet_size: int = 1500,
        byteswap: bool = False,
        camera_ip: str = "",
        initial_packet_timeout: float = 0.005,
        packet_timeout: float = 0.020,
        frame_retention: float = 0.200,
    ) -> None:
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
        with contextlib.suppress(OSError):
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024 * 1024)
        self._sock.bind((local_ip, local_port))
        self._sock.settimeout(0.05)  # short timeout for responsive gap checking

        self._port = self._sock.getsockname()[1]
        self._frame_queue: Queue[tuple[np.ndarray, dict]] = Queue(maxsize=max_queue)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_buffers: dict[int, _FrameBuffer] = {}
        self._resend_stats = {"requested": 0, "recovered": 0, "failed": 0}
        self.resend_enabled = True

        # Resend req_id counter (for direct resend from stream socket)
        self._resend_req_id = 0

    @property
    def port(self) -> int:
        """int : UDP port the receiver is bound to.

        Read the assigned port after construction, especially when
        *local_port* was ``0`` (OS-assigned)::

            receiver = GVSPReceiver()
            print(receiver.port)  # e.g. 49152
        """
        return self._port

    def start(self) -> None:
        """Start the background receiver thread.

        Idempotent. Does nothing if the thread is already running.

        Examples
        --------
        ::

            receiver = GVSPReceiver(local_ip="169.254.0.1")
            receiver.start()
            # ... acquire frames ...
            receiver.stop()
        """
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background receiver thread.

        Signals the thread to exit and waits up to 5 seconds for it to
        finish.  Clears any in-flight frame buffers.  The socket is kept
        open; call :meth:`close` to release it.
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        self._frame_buffers.clear()

    def close(self) -> None:
        """Stop the receiver and close the UDP socket.

        After calling ``close``, the receiver must not be used again.
        """
        self.stop()
        self._sock.close()

    def get_frame(self, timeout: float = 5.0) -> np.ndarray | None:
        """Block until a frame is available and return it as a NumPy array.

        Discards the accompanying metadata.  Use :meth:`get_frame_with_info`
        to retrieve metadata alongside the image.

        Parameters
        ----------
        timeout : float, optional
            Maximum time in seconds to wait for a frame.  Default is ``5.0``.

        Returns
        -------
        numpy.ndarray or None
            2-D array of shape ``(height, width)`` with dtype from
            :data:`PIXEL_DTYPE`, or ``None`` if no frame arrived within
            *timeout*.

        Examples
        --------
        ::

            receiver.start()
            frame = receiver.get_frame(timeout=2.0)
            if frame is not None:
                print(frame.shape, frame.dtype)
        """
        result = self.get_frame_with_info(timeout)
        if result is None:
            return None
        return result[0]

    def get_frame_with_info(self, timeout: float = 5.0) -> tuple[np.ndarray, dict] | None:
        """Block until a frame is available and return it with metadata.

        Parameters
        ----------
        timeout : float, optional
            Maximum time in seconds to wait for a frame.  Default is ``5.0``.

        Returns
        -------
        tuple of (numpy.ndarray, dict) or None
            ``(frame, info)`` where *frame* is a 2-D NumPy array and *info*
            is a dict with the following keys:

            ``"block_id"``
                GVSP block identifier (int).
            ``"timestamp"``
                Camera timestamp from the leader packet (int, camera ticks).
            ``"pixel_format"``
                GenICam PFNC pixel format code, e.g. :data:`PIXEL_MONO16` (int).
            ``"width"``
                Image width in pixels (int).
            ``"height"``
                Image height in pixels (int).
            ``"missing_packets"``
                Number of data packets that were not recovered before the
                frame was emitted (int; ``0`` for perfect frames).

            Returns ``None`` if no frame arrived within *timeout*.

        Examples
        --------
        ::

            result = receiver.get_frame_with_info(timeout=3.0)
            if result is not None:
                frame, info = result
                print(info["block_id"], info["missing_packets"])
        """
        try:
            return self._frame_queue.get(timeout=timeout)
        except Empty:
            return None

    # --- Internal ---

    def _receive_loop(self) -> None:
        """Main receiver loop with real-time gap detection."""
        while not self._stop_event.is_set():
            try:
                data, addr = self._sock.recvfrom(65536)
            except TimeoutError:
                # No packet received; check for gaps and stale frames
                self._check_gaps_and_timeouts()
                continue
            except OSError:
                break

            if len(data) < 8:
                continue

            self._parse_packet(data)

            # Check gaps on every packet (aravis pattern)
            self._check_gaps_and_timeouts()

    def _parse_packet(self, data: bytes) -> None:
        """Parse a single GVSP packet."""
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

    def _handle_leader(self, block_id: int, payload: bytes) -> None:
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

    def _handle_data(self, block_id: int, packet_id: int, payload: bytes) -> None:
        """Write data packet directly to pre-allocated frame buffer."""
        if block_id not in self._frame_buffers:
            if len(self._frame_buffers) >= self._MAX_CONCURRENT_FRAMES:
                oldest = min(self._frame_buffers, key=lambda k: self._frame_buffers[k].created_at)
                self._frame_buffers.pop(oldest, None)
            self._frame_buffers[block_id] = _FrameBuffer(block_id)
        self._frame_buffers[block_id].write_packet(packet_id, payload)

    def _handle_trailer(self, block_id: int, payload: bytes) -> None:
        """Handle trailer packet, emit completed frame."""
        if block_id not in self._frame_buffers:
            return

        buf = self._frame_buffers[block_id]
        buf.trailer_received = True

        # If we didn't get a leader (no pre-allocated buffer), calculate
        # expected packets now for the missing count
        if buf.expected_packets == 0 and buf.leader_received and buf.width > 0 and buf.height > 0:
            bpp = PIXEL_BPP.get(buf.pixel_format, 2)
            total_bytes = buf.width * buf.height * bpp
            buf.expected_packets = math.ceil(total_bytes / self._packet_data_size)

        # Log missing packets
        missing = buf.missing_packets()
        if missing:
            self._resend_stats["failed"] += len(missing)
            logger.warning(
                f"Frame {block_id}: {len(missing)}/{buf.expected_packets} packets unrecoverable"
            )

        # Assemble and emit
        self._emit_frame(buf)

    def _emit_frame(self, buf: _FrameBuffer) -> None:
        """Assemble frame and put it on the output queue."""
        frame = buf.assemble(byteswap=self.byteswap)
        if frame is not None:
            info = {
                "block_id": buf.block_id,
                "timestamp": buf.timestamp,
                "pixel_format": buf.pixel_format,
                "width": buf.width,
                "height": buf.height,
                "missing_packets": max(
                    0, buf.expected_packets - buf._received_count if buf.expected_packets > 0 else 0
                ),
            }
            if self._frame_queue.full():
                with contextlib.suppress(Empty):
                    self._frame_queue.get_nowait()
            self._frame_queue.put((frame, info))

        self._frame_buffers.pop(buf.block_id, None)

    def _check_gaps_and_timeouts(self) -> None:
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

            # Frame retention timeout: emit whatever we have
            if (
                since_last > self._frame_retention
                and buf.leader_received
                and (buf.trailer_received or age > self._frame_retention * 2)
            ):
                self._emit_frame(buf)
                to_remove.append(block_id)
                continue

            # Real-time gap detection: request resend for missing packets
            if (
                self.resend_enabled
                and self._camera_ip
                and buf.leader_received
                and buf.expected_packets > 0
                and age > self._initial_packet_timeout
            ):
                missing = buf.missing_packets()
                # Only resend packets we haven't already requested
                new_missing = [p for p in missing if p not in buf._resend_requested]
                if new_missing:
                    # Cap at 25% of frame packets per request (aravis default)
                    max_resend = max(1, buf.expected_packets // 4)
                    to_resend = new_missing[:max_resend]
                    self._send_resend_direct(block_id, to_resend)
                    buf._resend_requested.update(to_resend)

            # Hard timeout: drop frame
            if age > self._frame_retention * 5:
                to_remove.append(block_id)

        for bid in to_remove:
            self._frame_buffers.pop(bid, None)

    def _send_resend_direct(self, block_id: int, packet_ids: list[int]) -> None:
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
            header = struct.pack(
                ">BBHHH",
                _GVCP_KEY,
                _GVCP_FLAG_ACK,
                _GVCP_CMD_PACKETRESEND,
                len(payload),
                self._resend_req_id,
            )
            try:
                self._sock.sendto(header + payload, (self._camera_ip, _GVCP_PORT))
                self._resend_stats["requested"] += last - first + 1
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
