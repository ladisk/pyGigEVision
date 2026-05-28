"""GigE Vision standard register addresses.

Defined by the GigE Vision specification — same on every compliant
camera regardless of vendor. Vendor-specific registers (Width, Height,
ExposureTime, etc.) live in each vendor driver, derived from the
camera's GenICam XML.
"""

# ============================================================
# Bootstrap registers (GigE Vision spec section: device control)
# ============================================================
REG_CCP = 0x0A00  # Control Channel Privilege
REG_HEARTBEAT_TIMEOUT = 0x0938
REG_FIRST_URL = 0x0200  # Location of GenICam XML descriptor URL

# ============================================================
# Stream Channel 0 registers (GigE Vision spec)
# ============================================================
REG_SC_HOST_PORT = 0x0D00
REG_SC_PACKET_SIZE = 0x0D04
# REG_SC_PACKET_SIZE layout:
#   Bits 15:2 — packet size in bytes
#   Bit 1     — GevSCPSDoNotFragment (1=don't fragment, 0=allow)
#   Bit 0     — GevSCPSFireTestPacket (write-only trigger)
SC_PACKET_SIZE_MASK = 0xFFFC
SC_SCPS_DO_NOT_FRAGMENT = 1 << 1
SC_SCPS_FIRE_TEST_PACKET = 1 << 0
REG_SC_PACKET_DELAY = 0x0D08
REG_SC_DEST_ADDR = 0x0D18
