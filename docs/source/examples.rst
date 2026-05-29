Examples
========

Three runnable scripts ship in the ``examples/`` directory of the
source repository. Each is self-contained and demonstrates one piece
of the API. The scripts are vendor-neutral and run against any
GigE Vision compliant camera.

.. note::

   The third example needs a vendor-specific register address (the
   "start acquisition" command) filled in to actually trigger a frame.
   pyGigEVision is the protocol layer, not a turn-key camera
   abstraction. Use ``02_bootstrap_and_xml.py`` to download your
   camera's GenICam XML and look up the right address.

01_discover.py: Discover cameras
---------------------------------

Broadcasts a GigE Vision discovery packet and prints every camera that
responds. No arguments; runs against the auto-detected interface.

Use this first to sanity-check network setup (firewall, adapter
profile, IP routing).

02_bootstrap_and_xml.py: Bootstrap and download XML
---------------------------------------------------

Performs the standard boot sequence (open GVCP, take control, start
heartbeat) and saves the camera's GenICam XML descriptor to
``camera_descriptor.xml``. The XML lists every register the camera
exposes: addresses, types, allowed values, human-readable names.

Pass a camera IP as the first argument to target a specific camera;
omit to auto-discover the first one found.

03_grab_one_frame.py: End-to-end single frame
----------------------------------------------

The full protocol-level pipeline:

1. Bootstrap the camera.
2. Configure the stream channel via standard SC registers (host IP,
   port, packet size).
3. Trigger acquisition via a vendor-specific command register.
4. Receive one frame via :class:`~pyGigEVision.GVSPReceiver`.

Steps 1 and 4 are vendor-agnostic. Steps 2 and 3 reference register
addresses that you must look up in your camera's GenICam XML. The
script has a clearly marked placeholder for the acquisition-start
register.
