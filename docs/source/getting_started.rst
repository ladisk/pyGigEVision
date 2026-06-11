Getting started
===============

Installation
------------

From PyPI:

.. code-block:: bash

    pip install pyGigEVision

From source:

.. code-block:: bash

    git clone https://github.com/ladisk/pyGigEVision.git
    cd pyGigEVision
    pip install -e .

Requirements
------------

* Python 3.10 or newer
* NumPy 1.20 or newer
* ``psutil`` (used to enumerate host network interfaces for
  multi-interface discovery)
* A network interface that can reach the camera (usually a link-local
  ``169.254.x.x`` address on a dedicated Ethernet adapter, or a routed
  ``192.168.x.x`` subnet)
* Windows Firewall (or equivalent) allowing inbound UDP for the Python
  process

First contact
-------------

Discover any GigE Vision cameras on the network:

.. code-block:: python

    from pyGigEVision import discover

    cameras = discover(timeout=2.0)
    for cam in cameras:
        print(f"{cam['manufacturer']:30s} {cam['model']:30s} {cam['ip']}")

Called with no interface argument, ``discover()`` sweeps every host
network interface, so cameras on secondary NICs and USB-to-GigE adapters
are found by default. Each result dict includes ``ip``, ``mac``, and
``interface_ip`` (the host interface the camera replied on), which lets a
caller bind the correct local interface when connecting.

If a camera comes up on a subnet none of your host interfaces can reach,
use ``force_ip(mac, ip, mask)`` to re-home it to a reachable address:

.. code-block:: python

    from pyGigEVision import GVCPClient

    # force_ip is a static method; it broadcasts and needs no connection.
    GVCPClient.force_ip(cam["mac"], "169.254.10.50", "255.255.0.0")

If no cameras appear, see the :doc:`protocol` page for troubleshooting
network setup and packet capture.

Connecting and grabbing one frame
---------------------------------

The :func:`pyGigEVision.bootstrap` helper performs the standard boot
sequence: open a control session, acquire control privilege, start the
heartbeat thread, and fetch the GenICam XML descriptor.

.. code-block:: python

    from pyGigEVision import bootstrap, GVSPReceiver

    client, xml = bootstrap("169.254.1.10")
    print(f"Downloaded {len(xml)} bytes of GenICam XML")

    # From here you configure your camera's vendor-specific registers
    # (Width, Height, PixelFormat, AcquisitionStart, ...) using
    # client.write_reg(), then receive frames via GVSPReceiver.

    client.disconnect()

For a complete end-to-end example, see :doc:`examples`.

What pyGigEVision is and is not
-------------------------------

``pyGigEVision`` implements the **protocol layer** defined by the GigE
Vision specification. It does not know which register addresses your
camera uses for ``Width`` or ``ExposureTime``; those are
vendor-specific and discovered from the camera's GenICam XML.

For a turn-key driver for a specific camera, you would either:

* Use a vendor-specific package built on top of ``pyGigEVision``.
* Write your own thin vendor layer that parses the GenICam XML and
  wraps the relevant registers. See the :doc:`examples` page for a
  starting point.
