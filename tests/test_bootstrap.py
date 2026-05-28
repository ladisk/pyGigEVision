"""Tests for bootstrap() helper — uses a fake GVCPClient."""

import importlib
from unittest.mock import MagicMock, patch

from pyGigEVision.standard import REG_CCP, REG_HEARTBEAT_TIMEOUT

boot_mod = importlib.import_module("pyGigEVision.bootstrap")


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
