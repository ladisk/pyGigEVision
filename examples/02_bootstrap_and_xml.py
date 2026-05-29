"""Bootstrap a camera and save its GenICam XML descriptor.

The GenICam XML describes every register the camera exposes — its
addresses, types, allowed values, and human-readable names. Vendor
drivers parse this file to know how to talk to the camera.

Run with::

    python examples/02_bootstrap_and_xml.py [camera_ip]

If ``camera_ip`` is omitted, the script discovers the first camera
automatically.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pyGigEVision import bootstrap, discover


def main() -> None:
    if len(sys.argv) > 1:
        camera_ip = sys.argv[1]
    else:
        cameras = discover(timeout=2.0)
        if not cameras:
            print("No camera found and no IP supplied as argument.")
            sys.exit(1)
        camera_ip = cameras[0]["ip"]
        print(f"Auto-discovered: {camera_ip}")

    print(f"Bootstrapping {camera_ip}...")
    client, xml = bootstrap(camera_ip)
    try:
        print(f"Connected. Heartbeat ticking. Got {len(xml)} bytes of GenICam XML.")

        out_path = Path("camera_descriptor.xml")
        out_path.write_bytes(xml)
        print(f"Wrote descriptor to {out_path.resolve()}")
        print("Open it in any XML viewer to browse the camera's register map.")
    finally:
        client.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
