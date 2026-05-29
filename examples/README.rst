Examples
========

Vendor-neutral runnable scripts demonstrating the ``pyGigEVision`` API.

01_discover.py
--------------

Broadcasts a GigE Vision discovery packet and prints every camera that
responds. No arguments. Useful first sanity check that the network is
set up correctly.

02_bootstrap_and_xml.py
-----------------------

Boots a camera (control privilege + heartbeat) and saves its GenICam
XML descriptor to ``camera_descriptor.xml`` in the current directory.
The XML lists every register the camera exposes. Open it in any XML
viewer to learn the register addresses you need for your own driver.

Pass an IP as the first argument to target a specific camera; omit to
auto-discover the first one.

03_grab_one_frame.py
--------------------

The full protocol-level dance: bootstrap, configure stream channel via
standard registers, trigger acquisition via a vendor-specific register,
receive one frame. The vendor-specific register addresses in the
script are placeholders; edit them to match your camera (look them up
in the GenICam XML from script 02).

Pass camera IP and optional local IP as positional arguments.
