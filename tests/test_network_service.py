from fonfon.services.network_service import NetworkService


def test_get_ips_collects_interfaces_and_public():
    svc = NetworkService(
        interfaces=lambda: {"eth0": "203.0.113.5", "tailscale0": "100.101.102.103"},
        public_ip=lambda: "203.0.113.5",
    )
    info = svc.get_ips()
    assert info.interfaces["eth0"] == "203.0.113.5"
    assert info.public_ip == "203.0.113.5"


def test_get_ips_public_none_when_unreachable():
    svc = NetworkService(interfaces=lambda: {}, public_ip=lambda: None)
    assert svc.get_ips().public_ip is None
