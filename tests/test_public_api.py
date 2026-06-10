import pyGigEVision


def test_force_ip_is_public():
    assert hasattr(pyGigEVision, "force_ip")
    assert "force_ip" in pyGigEVision.__all__
    assert pyGigEVision.force_ip is pyGigEVision.GVCPClient.force_ip


def test_standard_is_importable():
    from pyGigEVision import standard

    assert hasattr(standard, "REG_CCP")
