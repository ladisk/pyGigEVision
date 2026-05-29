"""Connect, configure the stream channel, grab one frame.

This example shows the full protocol-level dance:

1. Bootstrap the camera (open GVCP, take CCP, start heartbeat,
   fetch GenICam XML).
2. Configure the GigE Vision standard stream channel registers
   (host IP, port, packet size).
3. Trigger acquisition via a vendor-specific command register.
4. Receive one frame via GVSPReceiver.

Steps 1 and 4 are vendor-agnostic. Steps 2 (which standard SC
registers to write) and 3 (which vendor-specific command register to
trigger) require knowing your camera's register layout — typically
discovered from the GenICam XML (see ``02_bootstrap_and_xml.py``).

The placeholder register addresses below must be replaced with the
correct values for your specific camera. The script will not work
out-of-the-box; it is a template.

Run with::

    python examples/03_grab_one_frame.py [camera_ip] [local_ip]
"""

from __future__ import annotations

import socket
import struct
import sys

from pyGigEVision import GVSPReceiver, bootstrap, discover
from pyGigEVision.standard import (
    REG_SC_DEST_ADDR,
    REG_SC_HOST_PORT,
    REG_SC_PACKET_SIZE,
    SC_PACKET_SIZE_MASK,
)

# ---- Vendor-specific registers (replace with your camera's values) ----
# Look these up by name in your camera's GenICam XML descriptor.
REG_ACQUISITION_START = 0x0000  # <- example placeholder
# Set BYTESWAP=True for big-endian cameras, False for little-endian.
BYTESWAP = False


def main() -> None:
    camera_ip = sys.argv[1] if len(sys.argv) > 1 else None
    local_ip = sys.argv[2] if len(sys.argv) > 2 else ""

    if camera_ip is None:
        cameras = discover(timeout=2.0)
        if not cameras:
            print("No camera found.")
            sys.exit(1)
        camera_ip = cameras[0]["ip"]
        print(f"Auto-discovered: {camera_ip}")

    print(f"Bootstrapping {camera_ip}...")
    client, _xml = bootstrap(camera_ip)

    try:
        # 1. Start the streaming receiver first, so we know which port to
        #    tell the camera to push to.
        rx = GVSPReceiver(local_ip=local_ip, local_port=0, byteswap=BYTESWAP)
        rx.start()
        print(f"GVSPReceiver listening on port {rx.port}")

        # 2. Tell the camera where to push (standard SC registers).
        if not local_ip:
            # If unspecified, pick the local IP that can reach the camera.
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect((camera_ip, 3956))
            local_ip = s.getsockname()[0]
            s.close()

        local_ip_int = struct.unpack(">I", socket.inet_aton(local_ip))[0]
        client.write_reg(REG_SC_DEST_ADDR, local_ip_int)
        client.write_reg(REG_SC_HOST_PORT, rx.port)

        # Pick a packet size that fits in your network MTU (1500 for
        # standard Ethernet; 9000 for jumbo frames).
        target_packet_size = 1500
        pkt_reg = client.read_reg(REG_SC_PACKET_SIZE)
        flags = pkt_reg & ~SC_PACKET_SIZE_MASK
        client.write_reg(
            REG_SC_PACKET_SIZE,
            flags | (target_packet_size & SC_PACKET_SIZE_MASK),
        )

        # 3. Trigger acquisition (vendor-specific register).
        if REG_ACQUISITION_START == 0x0000:
            print(
                "REG_ACQUISITION_START is a placeholder (0x0000). "
                "Edit this script and fill in your camera's value."
            )
            sys.exit(1)
        client.write_reg(REG_ACQUISITION_START, 1)
        print("Acquisition triggered. Waiting for a frame...")

        # 4. Grab one frame.
        frame = rx.get_frame(timeout=5.0)
        if frame is None:
            print("Timeout waiting for frame. Check camera state and network.")
        else:
            print(f"Got frame: shape={frame.shape}, dtype={frame.dtype}")

        rx.stop()
    finally:
        client.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    main()
