"""Discover GigE Vision cameras on the network.

Run with::

    python examples/01_discover.py
"""

from __future__ import annotations

from pyGigEVision import discover


def main() -> None:
    print("Searching for GigE Vision cameras on all interfaces...")
    cameras = discover(timeout=2.0)

    if not cameras:
        print("\nNo cameras found.")
        print("\nTroubleshooting:")
        print("  * Verify camera is powered on and on the same subnet as a NIC")
        print("  * On Windows: set the Ethernet adapter profile to Private")
        print("  * Stop VPN services that own a link-local interface (e.g. Tailscale)")
        return

    print(f"\nFound {len(cameras)} camera(s):\n")
    header = f"{'Manufacturer':30s} {'Model':30s} {'IP address':18s} {'Serial':15s}"
    print(header)
    print("-" * len(header))
    for cam in cameras:
        print(
            f"{cam.get('manufacturer', '?'):30s} "
            f"{cam.get('model', '?'):30s} "
            f"{cam.get('ip', '?'):18s} "
            f"{cam.get('serial', '?'):15s}"
        )


if __name__ == "__main__":
    main()
