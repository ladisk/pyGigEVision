Protocol overview
=================

``pyGigEVision`` implements two complementary UDP protocols from the
GigE Vision specification:

* **GVCP** — Gigabit Vision Control Protocol. Request-response control
  on UDP port 3956. Used for camera discovery, register read/write,
  bulk memory access, and heartbeat keepalive.
* **GVSP** — Gigabit Vision Streaming Protocol. One-way push streaming
  on a UDP port the host chooses. The camera sends each frame as a
  Leader packet, a sequence of Data packets, and a Trailer packet.

GVCP
----

The control protocol exposes a small set of commands. Every packet is
an 8-byte header plus a payload:

::

    [0x42] [flags] [command: 2B] [payload_len: 2B] [req_id: 2B]

The :class:`~pyGigEVision.GVCPClient` class wraps the commands in
Pythonic methods (:meth:`~pyGigEVision.GVCPClient.read_reg`,
:meth:`~pyGigEVision.GVCPClient.write_reg`,
:meth:`~pyGigEVision.GVCPClient.read_mem`, etc.) and handles
acknowledgement validation, retries, ``PENDING_ACK`` responses, and
heartbeat keepalive in a background thread.

Bootstrap (boot-time) registers defined by the GigE Vision spec live
in :mod:`pyGigEVision.standard`.

GVSP
----

The streaming receiver runs on its own background thread:

* Listens on a host-chosen UDP port.
* Reads incoming packets and dispatches by packet type (Leader / Data
  / Trailer).
* Reassembles frames into pre-allocated NumPy buffers (direct offset
  writes, no dictionary-and-sort overhead).
* Detects gaps in packet sequence numbers in real time and requests
  resends directly from the receive socket.
* Pushes completed frames onto a thread-safe queue for the consumer
  to pop via :meth:`~pyGigEVision.GVSPReceiver.get_frame`.

Byte order
~~~~~~~~~~

Some cameras send pixel data in little-endian and others in big-endian
order. ``pyGigEVision`` does not assume; set the ``byteswap``
parameter of :class:`~pyGigEVision.GVSPReceiver` according to your
camera's convention.

Troubleshooting
---------------

**Discovery finds nothing.**
Check that the camera is on the same subnet as one of your network
interfaces. On Windows, also verify that the Ethernet adapter profile
is set to ``Private`` (Public profile blocks inbound UDP by default).
If a VPN like Tailscale is running, its virtual link-local interface
may shadow the camera's Ethernet adapter — pass an explicit
``interface_ip`` to :func:`pyGigEVision.discover`.

**Packets unrecoverable warnings during streaming.**
Host-side UDP buffer overflows. Try one of:

* Increase the OS UDP receive buffer.
* Reduce the camera frame rate.
* Increase the packet inter-spacing via the ``REG_SC_PACKET_DELAY``
  register (see :mod:`pyGigEVision.standard`).

**Stream channel writes get ``ACCESS_DENIED``.**
Another process holds control privilege. Either close the other client
or wait for its heartbeat to expire (default ~3 seconds).
