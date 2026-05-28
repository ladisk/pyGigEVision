"""
GigE Vision Control Protocol (GVCP) client.

Implements UDP-based camera discovery, register read/write, memory access,
and heartbeat keepalive for GigE Vision v1.2 devices.

This module is generic — it works with any GigE Vision camera.

Protocol: UDP port 3956. Packet header is 8 bytes:
    key(1B=0x42) + flag(1B) + command(2B) + payload_len(2B) + req_id(2B)
ACK header is 8 bytes:
    status(2B) + ack_cmd(2B) + length(2B) + ack_id(2B)
"""

import contextlib
import socket
import struct
import threading
import time

from .standard import REG_CCP

# --- GVCP Constants ---
GVCP_PORT = 3956
GVCP_KEY = 0x42
FLAG_ACK = 0x01
FLAG_BROADCAST = 0x11

# Commands
CMD_DISCOVERY = 0x0002
CMD_READREG = 0x0080
CMD_WRITEREG = 0x0082
CMD_READMEM = 0x0084
CMD_WRITEMEM = 0x0086
CMD_PACKETRESEND = 0x0040

# Status codes
STATUS_SUCCESS = 0x0000
STATUS_NAMES = {
    0x0000: "SUCCESS",
    0x8001: "NOT_IMPLEMENTED",
    0x8002: "INVALID_PARAMETER",
    0x8003: "INVALID_ADDRESS",
    0x8004: "WRITE_PROTECT",
    0x8005: "BAD_ALIGNMENT",
    0x8006: "ACCESS_DENIED",
    0x8007: "BUSY",
    0x800C: "PACKET_NOT_YET_AVAILABLE",
    0x800D: "PACKET_AND_PREV_REMOVED",
    0x800E: "PACKET_REMOVED",
    0x8FFF: "GENERIC_ERROR",
}

# Max payload for READMEM (safe for standard Ethernet)
READMEM_CHUNK = 512


class GVCPError(Exception):
    """GVCP protocol error with status code."""

    def __init__(self, message: str, status: int = 0):
        self.status = status
        self.status_name = STATUS_NAMES.get(status, f"UNKNOWN_0x{status:04X}")
        super().__init__(f"{message} (status: {self.status_name})")


class GVCPClient:
    """GigE Vision Control Protocol client for camera register access.

    Usage:
        with GVCPClient("169.254.67.34") as cam:
            width = cam.read_reg(0xD300)
            exposure = cam.read_float(0xE808)
            cam.write_float(0xE808, 100.0)
    """

    def __init__(self, camera_ip: str, local_ip: str | None = None, timeout: float = 2.0):
        self.camera_ip = camera_ip
        self.local_ip = local_ip or ""
        self.timeout = timeout

        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._req_id = 0
        self._connected = False
        self._control_lost = False
        self._heartbeat_thread: threading.Thread | None = None
        self._heartbeat_stop = threading.Event()
        self._n_retries = 3
        self._cmd_timeout = 0.5  # seconds per attempt

    # --- Context Manager ---

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    # --- Discovery ---

    @staticmethod
    def discover(interface_ip: str = "", timeout: float = 2.0) -> list[dict]:
        """Broadcast GVCP discovery, return list of found cameras.

        Args:
            interface_ip: Local IP to bind to (empty = all interfaces).
            timeout: How long to wait for responses.

        Returns:
            List of dicts with keys: ip, manufacturer, model,
            device_version, serial, user_name, spec_version.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(timeout)
            if interface_ip:
                sock.bind((interface_ip, 0))

            pkt = struct.pack(">BBHHH", GVCP_KEY, FLAG_BROADCAST, CMD_DISCOVERY, 0, 0xFFFF)

            # Send to broadcast addresses
            for dest in ("255.255.255.255",):
                with contextlib.suppress(OSError):
                    sock.sendto(pkt, (dest, GVCP_PORT))
            # Also try subnet broadcast if we have an interface IP
            if interface_ip:
                parts = interface_ip.split(".")
                subnet_broadcast = f"{parts[0]}.{parts[1]}.255.255"
                with contextlib.suppress(OSError):
                    sock.sendto(pkt, (subnet_broadcast, GVCP_PORT))

            cameras = []
            seen_ips = set()
            while True:
                try:
                    data, addr = sock.recvfrom(4096)
                    if addr[0] in seen_ips:
                        continue
                    seen_ips.add(addr[0])

                    if len(data) < 256:
                        continue

                    # Parse discovery ACK payload (starts at byte 8)
                    payload = data[8:]

                    def _str(offset, size, _payload=payload):
                        return (
                            _payload[offset : offset + size]
                            .split(b"\x00")[0]
                            .decode("ascii", errors="replace")
                        )

                    # Try extended format first (some cameras add 24 bytes before strings)
                    # then fall back to standard offsets
                    mfr_ext = _str(72, 32)
                    mfr_std = _str(48, 32)

                    if mfr_ext and not mfr_std:
                        # Extended discovery format
                        cameras.append(
                            {
                                "ip": addr[0],
                                "spec_version": f"{struct.unpack('>H', payload[0:2])[0]}."
                                f"{struct.unpack('>H', payload[2:4])[0]}",
                                "manufacturer": mfr_ext,
                                "model": _str(104, 32),
                                "device_version": _str(136, 32),
                                "manufacturer_info": _str(168, 48),
                                "serial": _str(216, 16),
                                "user_name": _str(232, 16),
                            }
                        )
                    else:
                        # Standard discovery format
                        cameras.append(
                            {
                                "ip": addr[0],
                                "spec_version": f"{struct.unpack('>H', payload[0:2])[0]}."
                                f"{struct.unpack('>H', payload[2:4])[0]}",
                                "manufacturer": mfr_std,
                                "model": _str(80, 32),
                                "device_version": _str(112, 32),
                                "manufacturer_info": _str(144, 48),
                                "serial": _str(192, 16),
                                "user_name": _str(208, 16),
                            }
                        )
                except TimeoutError:
                    break
        finally:
            sock.close()

        return cameras

    # --- Connection ---

    def connect(self, force: bool = True):
        """Open socket, take control (CCP=2), start heartbeat.

        If another application (or a stale session) holds CCP control
        and ``force`` is True (default), we poll until the heartbeat
        timeout expires and the lock releases. This handles the common
        scenario where a previous Python session crashed without
        disconnecting.

        Args:
            force: If True, poll/retry on ACCESS_DENIED (up to ~15 s).
                   If False, raise immediately.
        """
        if self._connected:
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.local_ip:
            self._sock.bind((self.local_ip, 0))
        self._sock.settimeout(self.timeout)

        # Take control — poll on ACCESS_DENIED until old session's
        # heartbeat times out.
        max_wait = 15.0  # seconds — generous upper bound
        deadline = time.monotonic() + max_wait
        attempt = 0
        try:
            while True:
                try:
                    self._write_reg_raw(REG_CCP, 0x00000002)
                    break  # success
                except GVCPError as e:
                    if e.status == 0x8006 and force:  # ACCESS_DENIED
                        attempt += 1
                        if attempt == 1:
                            print(
                                "ACCESS_DENIED: waiting for stale CCP lock to expire...", flush=True
                            )
                        if time.monotonic() >= deadline:
                            raise GVCPError(
                                "Could not take CCP control after "
                                f"{max_wait:.0f}s — another application may "
                                "be actively connected",
                                0x8006,
                            ) from e
                        time.sleep(1.0)
                    else:
                        raise
        except Exception:
            self._sock.close()
            self._sock = None
            raise
        self._connected = True
        self._control_lost = False

        # Start heartbeat
        self._heartbeat_stop.clear()
        self._heartbeat_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._heartbeat_thread.start()

    def disconnect(self):
        """Stop heartbeat, release control, close socket."""
        if not self._connected:
            return

        self._heartbeat_stop.set()
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5.0)

        with contextlib.suppress(OSError, GVCPError):
            self._write_reg_raw(REG_CCP, 0x00000000)

        self._connected = False
        if self._sock:
            self._sock.close()
            self._sock = None

    # --- Register Access ---

    def read_reg(self, addr: int) -> int:
        """Read a single 32-bit register, return raw uint32."""
        with self._lock:
            return self._read_reg_raw(addr)

    def read_float(self, addr: int) -> float:
        """Read a register as IEEE 754 big-endian float."""
        raw = self.read_reg(addr)
        return struct.unpack(">f", struct.pack(">I", raw))[0]

    def write_reg(self, addr: int, value: int):
        """Write a 32-bit unsigned integer to a register."""
        with self._lock:
            self._write_reg_raw(addr, value)

    def write_float(self, addr: int, value: float):
        """Write an IEEE 754 float to a register."""
        raw = struct.unpack(">I", struct.pack(">f", value))[0]
        self.write_reg(addr, raw)

    def read_mem(self, addr: int, size: int) -> bytes:
        """Read a memory block (auto-chunks at 512 bytes)."""
        result = bytearray()
        offset = 0
        while offset < size:
            chunk_len = min(READMEM_CHUNK, size - offset)
            with self._lock:
                data = self._read_mem_raw(addr + offset, chunk_len)
            result.extend(data[:chunk_len])
            offset += chunk_len
        return bytes(result)

    # --- Internal Packet Methods ---

    def _next_id(self) -> int:
        self._req_id = (self._req_id + 1) & 0xFFFF
        if self._req_id == 0:
            self._req_id = 1
        return self._req_id

    def _send_cmd(self, flag: int, cmd: int, payload: bytes = b"") -> bytes:
        """Send a GVCP command and return raw ACK data.

        Validates that the ACK packet's req_id matches the command we sent.
        Stale ACKs from previous commands are silently discarded.
        PENDING_ACK (0x0089) responses extend the deadline.

        Retries up to ``_n_retries`` times, each with a ``_cmd_timeout``
        deadline.
        """
        req_id = self._next_id()
        header = struct.pack(">BBHHH", GVCP_KEY, flag, cmd, len(payload), req_id)
        hard_deadline = time.monotonic() + 30.0

        for _attempt in range(self._n_retries):
            self._sock.sendto(header + payload, (self.camera_ip, GVCP_PORT))

            deadline = time.monotonic() + self._cmd_timeout
            while time.monotonic() < deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._sock.settimeout(max(remaining, 0.01))
                try:
                    data, _ = self._sock.recvfrom(8192)
                except TimeoutError:
                    break  # this attempt timed out, retry

                if len(data) < 8:
                    continue  # runt packet, ignore

                ack_status = struct.unpack(">H", data[0:2])[0]
                ack_cmd = struct.unpack(">H", data[2:4])[0]
                ack_id = struct.unpack(">H", data[6:8])[0]

                # Handle PENDING_ACK: camera needs more time
                if ack_cmd == 0x0089:
                    if len(data) >= 12:
                        pending_ms = struct.unpack(">I", data[8:12])[0]
                        new_deadline = time.monotonic() + pending_ms / 1000.0
                        deadline = min(new_deadline, hard_deadline)
                    continue

                # Stale ACK from a previous command — discard
                if ack_id != req_id:
                    continue

                # Got our response
                if ack_status != STATUS_SUCCESS:
                    raise GVCPError(f"Command 0x{cmd:04X} failed", ack_status)
                return data

        raise GVCPError(f"Timeout waiting for ACK (cmd=0x{cmd:04X}, {self._n_retries} retries)")

    def _read_reg_raw(self, addr: int) -> int:
        """Internal: read single register (not locked)."""
        payload = struct.pack(">I", addr)
        data = self._send_cmd(FLAG_ACK, CMD_READREG, payload)
        return struct.unpack(">I", data[8:12])[0]

    def _write_reg_raw(self, addr: int, value: int):
        """Internal: write single register (not locked)."""
        payload = struct.pack(">II", addr, value)
        self._send_cmd(FLAG_ACK, CMD_WRITEREG, payload)

    def _read_mem_raw(self, addr: int, size: int) -> bytes:
        """Internal: read memory chunk (not locked)."""
        payload = struct.pack(">IHH", addr, 0, size)
        data = self._send_cmd(FLAG_ACK, CMD_READMEM, payload)
        # READMEM ACK: header(8) + address(4) + data
        return data[12:]

    # --- Packet Resend ---

    def send_packetresend(
        self, block_id: int, first_packet_id: int, last_packet_id: int, stream_channel: int = 0
    ):
        """Request retransmission of missing GVSP packets."""
        payload = struct.pack(">HHII", stream_channel, block_id, first_packet_id, last_packet_id)
        with self._lock:
            self._send_cmd(FLAG_ACK, CMD_PACKETRESEND, payload)

    # --- Heartbeat ---

    def _heartbeat_loop(self):
        """Background thread: read CCP every 2s to keep session alive.

        Also checks the CCP control bit — if cleared by another
        application (or firmware), sets ``_control_lost`` so callers
        can detect it.
        """
        while not self._heartbeat_stop.wait(2.0):
            try:
                with self._lock:
                    value = self._read_reg_raw(REG_CCP)
                if (value & 0x02) == 0:  # control bit cleared
                    self._control_lost = True
            except (OSError, GVCPError):
                pass
