"""GigE Vision Control Protocol (GVCP) client.

Implements the UDP-based control protocol from the GigE Vision
specification: device discovery (broadcast), register read/write
(``READREG``/``WRITEREG``), bulk memory access (``READMEM``), and
heartbeat keepalive for the ``Control Channel Privilege`` register.

The protocol runs on UDP port 3956. Each packet is an 8-byte header
followed by a payload. Header layout::

    key(1B=0x42) flag(1B) command(2B) payload_len(2B) req_id(2B)

ACK packets use an 8-byte response header::

    status(2B) ack_cmd(2B) length(2B) ack_id(2B)

This module is vendor-agnostic. The same code works against any GigE
Vision compliant camera; vendor-specific register addresses and features
are layered on top by vendor drivers.

See Also
--------
pyGigEVision.gvsp : The streaming counterpart (GVSP).
pyGigEVision.standard : GigE Vision spec register addresses.
pyGigEVision.bootstrap : Convenience helper to perform the standard
    boot sequence (open GVCP, take CCP, start heartbeat, fetch XML).
"""

from __future__ import annotations

import contextlib
import ipaddress
import select
import socket
import struct
import threading
import time

import psutil

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


def _enumerate_interfaces() -> list[tuple[str, str]]:
    """Return ``(ip, netmask)`` for every up, non-loopback IPv4 interface."""
    out: list[tuple[str, str]] = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if st is None or not st.isup:
            continue
        for a in addrs:
            if a.family == socket.AF_INET and a.address and not a.address.startswith("127."):
                out.append((a.address, a.netmask or "255.255.255.0"))
    return out


def _subnet_broadcasts_for(ip: str, netmask: str | None) -> list[str]:
    """Return broadcast destinations for an interface: global plus directed.

    Parameters
    ----------
    ip : str
        IPv4 address of the local interface.
    netmask : str or None
        Subnet mask string (e.g. ``"255.255.255.0"``).  When ``None``, a
        ``/16`` subnet is assumed and the directed broadcast is derived from
        the first two octets of *ip*.

    Returns
    -------
    list of str
        Always contains ``"255.255.255.255"``; additionally contains the
        directed subnet broadcast address derived from *ip* and *netmask*.
    """
    targets = ["255.255.255.255"]
    try:
        if netmask:
            net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
            targets.append(str(net.broadcast_address))
        else:
            parts = ip.split(".")
            targets.append(f"{parts[0]}.{parts[1]}.255.255")
    except (ValueError, IndexError):
        pass
    return targets


def _parse_discovery_ack(data: bytes, src_ip: str) -> dict | None:
    """Parse one GVCP discovery ACK into a camera dict, or ``None`` if invalid.

    Handles both the standard GigE Vision discovery ACK layout and the
    extended layout used by some cameras that shift the string fields by
    24 bytes.  The extended layout is detected when the manufacturer field
    at the extended offset is non-empty and the standard offset is empty.

    Parameters
    ----------
    data : bytes
        Raw UDP payload received from the camera (8-byte GVCP header +
        discovery ACK payload).  Must be at least 256 bytes.
    src_ip : str
        Source IPv4 address of the packet (used as the ``"ip"`` field in
        the returned dict).

    Returns
    -------
    dict or None
        Camera information dict with keys ``"ip"``, ``"spec_version"``,
        ``"manufacturer"``, ``"model"``, ``"device_version"``,
        ``"manufacturer_info"``, ``"serial"``, ``"user_name"``; or ``None``
        if *data* is too short to contain a valid ACK.
    """
    if len(data) < 256:
        return None
    payload = data[8:]

    def _str(offset: int, size: int) -> str:
        return payload[offset : offset + size].split(b"\x00")[0].decode("ascii", errors="replace")

    mfr_ext = _str(72, 32)
    mfr_std = _str(48, 32)
    spec_version = f"{struct.unpack('>H', payload[0:2])[0]}.{struct.unpack('>H', payload[2:4])[0]}"
    mac = ":".join(f"{b:02x}" for b in payload[10:16])
    if mfr_ext and not mfr_std:
        return {
            "ip": src_ip,
            "spec_version": spec_version,
            "mac": mac,
            "manufacturer": mfr_ext,
            "model": _str(104, 32),
            "device_version": _str(136, 32),
            "manufacturer_info": _str(168, 48),
            "serial": _str(216, 16),
            "user_name": _str(232, 16),
        }
    return {
        "ip": src_ip,
        "spec_version": spec_version,
        "mac": mac,
        "manufacturer": mfr_std,
        "model": _str(80, 32),
        "device_version": _str(112, 32),
        "manufacturer_info": _str(144, 48),
        "serial": _str(192, 16),
        "user_name": _str(208, 16),
    }


class GVCPError(Exception):
    """GVCP protocol error raised when the camera returns a non-SUCCESS status.

    Attributes
    ----------
    status : int
        Numeric GVCP status code, e.g. ``0x8006`` for ACCESS_DENIED.
    status_name : str
        Human-readable name from :data:`STATUS_NAMES`, or
        ``"UNKNOWN_0xXXXX"`` for unrecognised codes.

    Parameters
    ----------
    message : str
        Short description of what operation failed.
    status : int, optional
        GVCP status code returned by the camera.  Default is ``0``
        (``SUCCESS``), used when the error is locally generated (e.g.
        timeout after all retries).

    Examples
    --------
    >>> err = GVCPError("Register read failed", 0x8006)
    >>> err.status
    32774
    >>> err.status_name
    'ACCESS_DENIED'
    """

    def __init__(self, message: str, status: int = 0) -> None:
        self.status = status
        self.status_name = STATUS_NAMES.get(status, f"UNKNOWN_0x{status:04X}")
        super().__init__(f"{message} (status: {self.status_name})")


class GVCPClient:
    """GigE Vision Control Protocol client for camera register access.

    Manages a single UDP socket to a specific camera, handles request/ACK
    sequencing (including stale-ACK discard and PENDING_ACK extension),
    takes and releases the ``Control Channel Privilege`` (CCP) register,
    and maintains a background heartbeat thread to keep the session alive.

    Parameters
    ----------
    camera_ip : str
        IPv4 address of the camera, e.g. ``"169.254.67.34"``.
    local_ip : str or None, optional
        Local network interface address to bind the GVCP socket to.
        ``None`` (default) lets the OS choose the interface based on
        the camera's IP and routing rules.
    timeout : float, optional
        Socket timeout in seconds for the initial connection and the
        overall socket.  Default is ``2.0``.

    Notes
    -----
    The constructor does not perform any network I/O.  Call
    :meth:`connect` (or use the context-manager form) to acquire control
    privilege and start the heartbeat thread.

    The client is safe for concurrent use: :meth:`read_reg`,
    :meth:`write_reg`, :meth:`read_mem`, :meth:`read_float`,
    :meth:`write_float`, and :meth:`send_packetresend` all acquire the
    internal ``_lock`` before touching the socket.

    Examples
    --------
    Using the context manager (recommended)::

        with GVCPClient("169.254.67.34") as cam:
            width = cam.read_reg(0xD300)
            exposure = cam.read_float(0xE808)
            cam.write_float(0xE808, 100.0)

    Manual lifecycle::

        client = GVCPClient("169.254.67.34")
        client.connect()
        try:
            width = client.read_reg(0xD300)
        finally:
            client.disconnect()
    """

    def __init__(
        self,
        camera_ip: str,
        local_ip: str | None = None,
        timeout: float = 2.0,
    ) -> None:
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

    def __enter__(self) -> GVCPClient:
        """Enter the context manager by calling :meth:`connect`.

        Returns
        -------
        GVCPClient
            ``self``, so the ``as`` clause captures the connected client.
        """
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        """Exit the context manager by calling :meth:`disconnect`."""
        self.disconnect()

    # --- Discovery ---

    @staticmethod
    def discover(interface_ip: str = "", timeout: float = 2.0) -> list[dict]:
        """Broadcast a GVCP discovery packet and return all responding cameras.

        When *interface_ip* is empty (the default), discovery sweeps every
        host interface: it binds a dedicated socket per NIC and sends both
        the global broadcast (``255.255.255.255``) and the per-subnet
        broadcast for each interface, then merges the results.  When
        *interface_ip* is given, a single socket bound to that interface is
        used.  All sends go to UDP port 3956 and each discovery ACK is
        parsed into a dictionary.

        Both the standard GigE Vision discovery ACK layout and the extended
        layout (used by some cameras that prepend 24 extra bytes before the
        string fields) are handled.  Duplicate responses from the same IP
        are deduplicated.

        Parameters
        ----------
        interface_ip : str, optional
            Local interface IPv4 address to bind the socket to, e.g.
            ``"169.254.0.1"``.  Empty string (default) lets the OS choose,
            which sends the broadcast on all active interfaces.
        timeout : float, optional
            How long to wait for discovery responses, in seconds.
            Default is ``2.0``.

        Returns
        -------
        list of dict
            One entry per discovered camera.  Each dict has keys:

            ``"ip"``
                IPv4 address string of the camera.
            ``"spec_version"``
                GigE Vision spec version the camera reports, e.g. ``"1.2"``.
            ``"manufacturer"``
                Manufacturer name string.
            ``"model"``
                Model name string.
            ``"device_version"``
                Firmware / device version string.
            ``"manufacturer_info"``
                Additional manufacturer info string.
            ``"serial"``
                Serial number string.
            ``"user_name"``
                User-assigned name string (may be empty).

        Examples
        --------
        >>> cameras = GVCPClient.discover(interface_ip="169.254.0.1", timeout=1.0)
        >>> for cam in cameras:
        ...     print(cam["ip"], cam["model"])
        """
        pkt = struct.pack(">BBHHH", GVCP_KEY, FLAG_BROADCAST, CMD_DISCOVERY, 0, 0xFFFF)

        if interface_ip:
            targets = [(interface_ip, _subnet_broadcasts_for(interface_ip, None))]
        else:
            targets = [
                (ip, _subnet_broadcasts_for(ip, mask)) for ip, mask in _enumerate_interfaces()
            ]
            if not targets:
                targets = [("", ["255.255.255.255"])]

        socks: list[socket.socket] = []
        try:
            for bind_ip, bcasts in targets:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                if bind_ip:
                    try:
                        sock.bind((bind_ip, 0))
                    except OSError:
                        sock.close()
                        continue
                for dest in bcasts:
                    with contextlib.suppress(OSError):
                        sock.sendto(pkt, (dest, GVCP_PORT))
                socks.append(sock)

            cameras: list[dict] = []
            seen_ips: set[str] = set()
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                rlist, _, _ = select.select(socks, [], [], remaining)
                if not rlist:
                    break
                for sock in rlist:
                    try:
                        data, addr = sock.recvfrom(4096)
                    except OSError:
                        continue
                    if addr[0] in seen_ips:
                        continue
                    seen_ips.add(addr[0])
                    cam = _parse_discovery_ack(data, addr[0])
                    if cam is not None:
                        cameras.append(cam)
            return cameras
        finally:
            for sock in socks:
                sock.close()

    # --- Connection ---

    def connect(self, force: bool = True) -> None:
        """Open the UDP socket, take CCP control, and start the heartbeat thread.

        If another application (or a stale previous session) holds the CCP
        control privilege and *force* is ``True``, this method polls with
        1-second intervals until the remote heartbeat timeout expires and the
        lock is released automatically by the camera.  This handles the
        common scenario where a previous Python session crashed without
        calling :meth:`disconnect`.

        A call on an already-connected client is a no-op.

        Parameters
        ----------
        force : bool, optional
            If ``True`` (default), retry on ``ACCESS_DENIED`` for up to
            15 seconds, printing a warning on the first retry.  If
            ``False``, raise :exc:`GVCPError` immediately when access is
            denied.

        Raises
        ------
        GVCPError
            If the CCP register write fails for any reason other than
            ``ACCESS_DENIED``, or if *force* is ``True`` but the 15-second
            retry window expires without gaining control.
        OSError
            If the UDP socket cannot be created or bound.
        """
        if self._connected:
            return

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if self.local_ip:
            self._sock.bind((self.local_ip, 0))
        self._sock.settimeout(self.timeout)

        # Take control: poll on ACCESS_DENIED until old session's
        # heartbeat times out.
        max_wait = 15.0  # seconds; generous upper bound
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
                                f"{max_wait:.0f}s; another application may "
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

    def disconnect(self) -> None:
        """Stop the heartbeat, release CCP control, and close the socket.

        Releases the ``Control Channel Privilege`` register (writes 0x00000000
        to ``REG_CCP``) so other applications can immediately connect without
        waiting for the heartbeat timeout.  Any errors during the release are
        silently suppressed to ensure the socket is always closed.

        A call on a client that is not connected is a no-op.
        """
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
        """Read a single 32-bit register from the camera.

        Sends a ``READREG`` command and returns the raw unsigned 32-bit value.
        Thread-safe: acquires the internal socket lock before sending.

        Parameters
        ----------
        addr : int
            Register address (32-bit unsigned).  Use constants from
            :mod:`pyGigEVision.standard` for spec-defined registers, or
            vendor-specific addresses from the camera's GenICam XML.

        Returns
        -------
        int
            Raw register value as a 32-bit unsigned integer.

        Raises
        ------
        GVCPError
            If the camera returns a non-SUCCESS status, or if all retry
            attempts time out.

        Examples
        --------
        >>> with GVCPClient("169.254.67.34") as cam:
        ...     width = cam.read_reg(0xD300)
        ...     print(f"Width: {width}")
        """
        with self._lock:
            return self._read_reg_raw(addr)

    def read_float(self, addr: int) -> float:
        """Read a register and interpret it as an IEEE 754 big-endian float.

        Reads the raw 32-bit value from *addr* via :meth:`read_reg` and
        reinterprets the bit pattern as a single-precision float.

        Parameters
        ----------
        addr : int
            Register address (32-bit unsigned) of the float-valued register.

        Returns
        -------
        float
            The register value reinterpreted as a 32-bit IEEE 754
            single-precision float.

        Raises
        ------
        GVCPError
            If the underlying :meth:`read_reg` call fails.

        Examples
        --------
        >>> with GVCPClient("169.254.67.34") as cam:
        ...     exposure_us = cam.read_float(0xE808)
        """
        raw = self.read_reg(addr)
        return struct.unpack(">f", struct.pack(">I", raw))[0]

    def write_reg(self, addr: int, value: int) -> None:
        """Write a 32-bit unsigned integer to a camera register.

        Sends a ``WRITEREG`` command.  Thread-safe: acquires the internal
        socket lock before sending.

        Parameters
        ----------
        addr : int
            Register address (32-bit unsigned).
        value : int
            Value to write (32-bit unsigned, 0–4294967295).

        Raises
        ------
        GVCPError
            If the camera returns a non-SUCCESS status (e.g. ``WRITE_PROTECT``,
            ``ACCESS_DENIED``), or if all retry attempts time out.

        Examples
        --------
        >>> with GVCPClient("169.254.67.34") as cam:
        ...     cam.write_reg(0xD300, 640)
        """
        with self._lock:
            self._write_reg_raw(addr, value)

    def write_float(self, addr: int, value: float) -> None:
        """Write a float value to a camera register as IEEE 754 big-endian.

        Packs *value* as a 32-bit single-precision float and writes the raw
        bit pattern to the register at *addr* via :meth:`write_reg`.

        Parameters
        ----------
        addr : int
            Register address (32-bit unsigned) of the float-valued register.
        value : float
            Value to write.  The float is packed with big-endian byte order
            before transmission.

        Raises
        ------
        GVCPError
            If the underlying :meth:`write_reg` call fails.

        Examples
        --------
        >>> with GVCPClient("169.254.67.34") as cam:
        ...     cam.write_float(0xE808, 1000.0)  # set exposure to 1000 µs
        """
        raw = struct.unpack(">I", struct.pack(">f", value))[0]
        self.write_reg(addr, raw)

    def read_mem(self, addr: int, size: int) -> bytes:
        """Read a contiguous block of camera memory.

        Splits the request into chunks of at most :data:`READMEM_CHUNK` bytes
        (512 bytes, safe for standard Ethernet) and concatenates the results.
        Each chunk is read with the lock held, so concurrent register
        operations may interleave between chunks.

        Parameters
        ----------
        addr : int
            Start address of the memory block (32-bit unsigned).
        size : int
            Number of bytes to read.  If *size* is 0, an empty ``bytes``
            object is returned immediately.

        Returns
        -------
        bytes
            Raw memory contents, exactly *size* bytes.

        Raises
        ------
        GVCPError
            If any ``READMEM`` chunk fails.

        Examples
        --------
        >>> with GVCPClient("169.254.67.34") as cam:
        ...     xml_url = cam.read_mem(0x0200, 512)
        ...     print(xml_url.split(b"\\x00")[0].decode())
        """
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
        """Increment and return the next request ID (1–65535, wraps at 0xFFFF).

        The value 0 is skipped; after 0xFFFF the counter resets to 1.
        """
        self._req_id = (self._req_id + 1) & 0xFFFF
        if self._req_id == 0:
            self._req_id = 1
        return self._req_id

    def _send_cmd(self, flag: int, cmd: int, payload: bytes = b"") -> bytes:
        """Send a GVCP command packet and return the raw ACK data.

        Builds and sends an 8-byte GVCP header followed by *payload*.
        Reads response packets until one with a matching request ID arrives
        or all retries are exhausted.

        Stale ACKs (wrong ``ack_id``) are silently discarded.  Runt packets
        shorter than 8 bytes are also discarded.  ``PENDING_ACK`` (command
        code ``0x0089``) responses extend the per-attempt deadline by the
        number of milliseconds indicated in the response payload, bounded by
        a hard 30-second absolute deadline.

        Parameters
        ----------
        flag : int
            GVCP flag byte, e.g. :data:`FLAG_ACK` or :data:`FLAG_BROADCAST`.
        cmd : int
            GVCP command code, e.g. :data:`CMD_READREG`.
        payload : bytes, optional
            Command payload bytes.  Default is empty (no payload).

        Returns
        -------
        bytes
            Raw ACK packet bytes, including the 8-byte ACK header.

        Raises
        ------
        GVCPError
            If the camera returns a non-SUCCESS status in the ACK, or if
            all ``_n_retries`` attempts time out without a matching ACK.
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

                # Stale ACK from a previous command; discard
                if ack_id != req_id:
                    continue

                # Got our response
                if ack_status != STATUS_SUCCESS:
                    raise GVCPError(f"Command 0x{cmd:04X} failed", ack_status)
                return data

        raise GVCPError(f"Timeout waiting for ACK (cmd=0x{cmd:04X}, {self._n_retries} retries)")

    def _read_reg_raw(self, addr: int) -> int:
        """Send a READREG command and return the 32-bit result (not locked)."""
        payload = struct.pack(">I", addr)
        data = self._send_cmd(FLAG_ACK, CMD_READREG, payload)
        return struct.unpack(">I", data[8:12])[0]

    def _write_reg_raw(self, addr: int, value: int) -> None:
        """Send a WRITEREG command for a single register (not locked)."""
        payload = struct.pack(">II", addr, value)
        self._send_cmd(FLAG_ACK, CMD_WRITEREG, payload)

    def _read_mem_raw(self, addr: int, size: int) -> bytes:
        """Send a READMEM command and return the raw memory bytes (not locked).

        The READMEM ACK layout is: 8-byte ACK header + 4-byte address echo
        + data, so payload starts at byte offset 12.
        """
        payload = struct.pack(">IHH", addr, 0, size)
        data = self._send_cmd(FLAG_ACK, CMD_READMEM, payload)
        # READMEM ACK: header(8) + address(4) + data
        return data[12:]

    # --- Packet Resend ---

    def send_packetresend(
        self,
        block_id: int,
        first_packet_id: int,
        last_packet_id: int,
        stream_channel: int = 0,
    ) -> None:
        """Request retransmission of missing GVSP stream packets.

        Sends a ``CMD_PACKETRESEND`` command asking the camera to re-send the
        specified packet range for a given stream block.  Used by
        :class:`pyGigEVision.gvsp.GVSPReceiver` to recover from packet loss.

        Parameters
        ----------
        block_id : int
            The GVSP block (frame) identifier for which packets are missing.
        first_packet_id : int
            ID of the first missing packet within the block.
        last_packet_id : int
            ID of the last missing packet within the block (inclusive).
        stream_channel : int, optional
            GVSP stream channel index.  Default is ``0`` (the only channel
            on most cameras).

        Raises
        ------
        GVCPError
            If the camera returns a non-SUCCESS status or the request times
            out after all retries.
        """
        payload = struct.pack(">HHII", stream_channel, block_id, first_packet_id, last_packet_id)
        with self._lock:
            self._send_cmd(FLAG_ACK, CMD_PACKETRESEND, payload)

    # --- Heartbeat ---

    def _heartbeat_loop(self) -> None:
        """Background daemon thread that keeps the GVCP session alive.

        Reads the CCP register every 2 seconds.  The read itself acts as the
        heartbeat that prevents the camera from expiring the control-channel
        privilege.

        Also monitors the CCP value: if the control bit (bit 1) is cleared
        (indicating that another application has taken over or the camera
        reset the privilege), sets :attr:`_control_lost` to ``True`` so
        callers can detect the loss of control.

        Network and protocol errors are silently suppressed; the loop
        continues until :attr:`_heartbeat_stop` is set by :meth:`disconnect`.
        """
        while not self._heartbeat_stop.wait(2.0):
            try:
                with self._lock:
                    value = self._read_reg_raw(REG_CCP)
                if (value & 0x02) == 0:  # control bit cleared
                    self._control_lost = True
            except (OSError, GVCPError):
                pass
