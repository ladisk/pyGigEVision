"""Tests for bootstrap() helper — uses a fake GVCPClient."""

import importlib
import sys
from unittest.mock import MagicMock, patch

import pyGigEVision  # noqa: F401 — ensures submodules are registered in sys.modules
import pyGigEVision.bootstrap  # ensure the submodule is loaded
from pyGigEVision.standard import REG_CCP, REG_HEARTBEAT_TIMEOUT

# Always resolve to the actual submodule, even when __init__ re-exports
# a `bootstrap` function under the same name.
boot_mod = sys.modules["pyGigEVision.bootstrap"]


def test_bootstrap_writes_ccp_and_heartbeat_then_fetches_xml():
    fake_client = MagicMock()
    raw_xml = b"<RegisterDescription/>"
    url = (b"Local:cam.xml;0x10000;%d\x00" % len(raw_xml)).ljust(512, b"\x00")
    fake_client.read_mem.side_effect = [url, raw_xml]

    with patch.object(boot_mod, "GVCPClient", return_value=fake_client) as gv_cls:
        client, xml = boot_mod.bootstrap("169.254.1.1")

    gv_cls.assert_called_once_with("169.254.1.1")
    fake_client.connect.assert_called_once()
    fake_client.write_reg.assert_any_call(REG_CCP, 0x00000002)
    fake_client.write_reg.assert_any_call(REG_HEARTBEAT_TIMEOUT, 3000)
    assert xml == raw_xml
    assert client is fake_client
