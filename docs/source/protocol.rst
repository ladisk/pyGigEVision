Protocol overview
=================

``pyGigEVision`` implements two complementary UDP protocols from the
GigE Vision specification:

* **GVCP** (Gigabit Vision Control Protocol): request-response control
  on UDP port 3956. Used for camera discovery, register read/write,
  bulk memory access, and heartbeat keepalive.
* **GVSP** (Gigabit Vision Streaming Protocol): one-way push streaming
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

Discovery
~~~~~~~~~

:func:`pyGigEVision.discover` called with no argument (``discover("")``)
enumerates the host network interfaces (via ``psutil``) and scans from
each one. On every interface it sends a global broadcast and a
per-subnet directed broadcast, then dedupes the replies by camera IP.
Sweeping all interfaces by default means cameras on secondary NICs and
on USB-to-GigE adapters are found without naming an interface. Pass an
explicit ``interface_ip`` to restrict the scan to a single host
interface.

Each result dict includes the camera ``ip`` and ``mac`` as well as
``interface_ip``, the host interface address the camera replied on.
A vendor driver can use ``interface_ip`` to bind the matching local
interface when it connects, which keeps the connection on the same NIC
that saw the discovery reply.

If a camera comes up on a subnet that none of the host interfaces can
reach, :meth:`~pyGigEVision.GVCPClient.force_ip` re-homes it by MAC. It
broadcasts a FORCEIP command that assigns a new ``ip`` and ``mask`` (and
optional ``gateway``) to the camera identified by ``mac``, so it lands
on a reachable subnet. The assignment is not persistent across a power
cycle.

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
If a VPN is active and owns a virtual link-local interface, that
interface may shadow the camera's Ethernet adapter. In that case, pass
an explicit ``interface_ip`` to :func:`pyGigEVision.discover` to scan
from the host interface the camera is attached to.

**Packets unrecoverable warnings during streaming.**
Host-side UDP buffer overflows. Try one of:

* Increase the OS UDP receive buffer.
* Reduce the camera frame rate.
* Increase the packet inter-spacing via the ``REG_SC_PACKET_DELAY``
  register (see :mod:`pyGigEVision.standard`).

**Stream channel writes get ``ACCESS_DENIED``.**
Another process holds control privilege. Either close the other client
or wait for its heartbeat to expire (default ~3 seconds).
