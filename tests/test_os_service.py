from fonfon.services.os_service import OSService


def test_get_info_maps_pretty_name_id_and_machine():
    os_data = {"PRETTY_NAME": "Debian GNU/Linux 12 (bookworm)", "ID": "debian"}
    svc = OSService(
        read_os_release=lambda: os_data,
        machine=lambda: "x86_64",
    )
    info = svc.get_info()
    assert info.distro == "Debian GNU/Linux 12 (bookworm)"
    assert info.distro_id == "debian"
    assert info.architecture == "x86_64"


def test_get_info_falls_back_when_os_release_empty():
    svc = OSService(read_os_release=lambda: {}, machine=lambda: "aarch64")
    info = svc.get_info()
    assert info.distro_id == "unknown"
    assert info.architecture == "aarch64"
