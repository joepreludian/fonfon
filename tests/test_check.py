# tests/test_check.py
from fonfon.models import CheckStatus
from fonfon.services.check import SERVICES, build_report
from fonfon.services.docker_service import DockerReport
from fonfon.services.network_service import NetworkInfo
from fonfon.services.os_service import OSInfo
from fonfon.services.package_service import PackageReport
from fonfon.services.systemd_service import ServicesReport, ServiceState
from fonfon.system.dpkg import PackageState


def _items(report, title):
    section = next(s for s in report.sections if s.title == title)
    return {i.label: i for i in section.items}


def _base(**over):
    args = dict(
        os_info=OSInfo(distro="Debian 12", distro_id="debian", architecture="x86_64"),
        packages=PackageReport(
            packages=[
                PackageState(name="sudo", installed=True, version="1.9"),
                PackageState(name="docker-ce", installed=False, version=None),
            ]
        ),
        services=ServicesReport(
            services=[
                ServiceState(name="ssh", present=True, enabled=True, active=True),
                ServiceState(name="docker", present=False, enabled=False, active=False),
            ]
        ),
        network=NetworkInfo(
            interfaces={"eth0": "203.0.113.5"}, public_ip="203.0.113.5"
        ),
        docker=DockerReport(docker_installed=False),
        sdci_installed=False,
        is_root=False,
        can_sudo=True,
    )
    args.update(over)
    return build_report(**args)


def test_system_items_are_info():
    report = _base()
    assert _items(report, "System")["Architecture"].status is CheckStatus.INFO


def test_installed_package_ok_missing_fail():
    pkgs = _items(_base(), "Packages")
    assert pkgs["sudo"].status is CheckStatus.OK
    assert pkgs["docker-ce"].status is CheckStatus.FAIL


def test_enabled_service_ok_disabled_fail():
    svcs = _items(_base(), "Services")
    assert svcs["ssh"].status is CheckStatus.OK
    assert svcs["docker"].status is CheckStatus.FAIL


def test_network_items_are_info():
    net = _items(_base(), "Network")
    assert all(i.status is CheckStatus.INFO for i in net.values())


def test_docker_absent_section_is_skip():
    dock = _items(_base(), "Docker")
    # the sudo item is still reported even when docker itself is absent
    assert dock["docker"].status is CheckStatus.SKIP
    assert "sudo" in dock


def test_docker_gaps_are_warn():
    report = _base(
        docker=DockerReport(
            docker_installed=True,
            socket_ready=True,
            service="traefik",
            present=False,
            running=False,
            listening={80: False, 443: False},
            network_present=False,
        )
    )
    dock = _items(report, "Docker")
    assert dock["socket"].status is CheckStatus.OK
    gaps = [i for label, i in dock.items() if label not in ("socket", "sudo")]
    assert all(i.status is CheckStatus.WARN for i in gaps)


def test_docker_socket_not_ready_is_fail():
    report = _base(
        docker=DockerReport(
            docker_installed=True,
            socket_ready=False,
            service="traefik",
            present=False,
            running=False,
            listening={80: False, 443: False},
            network_present=False,
        )
    )
    item = _items(report, "Docker")["socket"]
    assert item.status is CheckStatus.FAIL
    assert "dockerd" in item.detail
    # an unreachable socket fails the gate
    assert report.ok is False


def test_docker_socket_denied_explains_permission():
    report = _base(
        docker=DockerReport(
            docker_installed=True,
            socket_ready=False,
            socket_reason="denied",
            service="traefik",
        )
    )
    item = _items(report, "Docker")["socket"]
    assert item.status is CheckStatus.FAIL
    assert "permission denied" in item.detail
    assert report.ok is False


def test_docker_sudo_available_is_ok():
    item = _items(_base(can_sudo=True, is_root=False), "Docker")["sudo"]
    assert item.status is CheckStatus.OK
    assert item.detail == "available"


def test_docker_sudo_root_is_ok():
    item = _items(_base(is_root=True), "Docker")["sudo"]
    assert item.status is CheckStatus.OK
    assert item.detail == "running as root"


def test_docker_sudo_unavailable_is_warn():
    item = _items(_base(can_sudo=False, is_root=False), "Docker")["sudo"]
    assert item.status is CheckStatus.WARN
    assert "sudo" in item.detail


def test_docker_present_but_stopped_is_warn():
    report = _base(
        docker=DockerReport(
            docker_installed=True,
            socket_ready=True,
            service="traefik",
            present=True,
            running=False,
            listening={80: False, 443: False},
            network_present=True,
            network_name="traefik",
        )
    )
    item = _items(report, "Docker")["traefik"]
    assert item.status is CheckStatus.WARN
    assert item.detail == "present but stopped"


def test_unsupported_distro_packages_section_has_skip_row():
    report = _base(packages=None)
    pkgs = _items(report, "Packages")
    assert pkgs["packages"].status is CheckStatus.SKIP


def test_report_ok_false_when_fail_present():
    assert _base().ok is False


def test_service_present_but_disabled_is_fail_not_not_found():
    svc = ServicesReport(
        services=[
            ServiceState(name="docker", present=True, enabled=False, active=False)
        ]
    )
    item = _items(_base(services=svc), "Services")["docker"]
    assert item.status is CheckStatus.FAIL
    assert item.detail == "not enabled"


def test_service_enabled_but_inactive_detail():
    svc = ServicesReport(
        services=[ServiceState(name="ssh", present=True, enabled=True, active=False)]
    )
    item = _items(_base(services=svc), "Services")["ssh"]
    assert item.status is CheckStatus.OK
    assert item.detail == "enabled, inactive"


def test_docker_all_ok_path():
    docker = DockerReport(
        docker_installed=True,
        socket_ready=True,
        service="traefik",
        present=True,
        running=True,
        listening={80: True, 443: True},
        network_present=True,
        network_name="traefik",
        dashboard_port=8080,
        dashboard_tailnet_only=True,
        tailnet_ip="100.64.0.1",
    )
    items = _items(_base(docker=docker), "Docker")
    assert all(i.status is CheckStatus.OK for i in items.values())


def test_docker_dashboard_public_is_fail():
    docker = DockerReport(
        docker_installed=True,
        socket_ready=True,
        service="traefik",
        present=True,
        running=True,
        listening={80: True, 443: True},
        network_present=True,
        network_name="traefik",
        dashboard_port=8080,
        dashboard_public=True,
        tailnet_ip="100.64.0.1",
    )
    item = _items(_base(docker=docker), "Docker")["dashboard (tailnet-only)"]
    assert item.status is CheckStatus.FAIL
    assert "publicly" in item.detail


def test_docker_dashboard_tailnet_only_is_ok_with_ip_detail():
    docker = DockerReport(
        docker_installed=True,
        socket_ready=True,
        service="traefik",
        present=True,
        running=True,
        listening={80: True, 443: True},
        network_present=True,
        network_name="traefik",
        dashboard_port=8080,
        dashboard_tailnet_only=True,
        tailnet_ip="100.64.0.1",
    )
    item = _items(_base(docker=docker), "Docker")["dashboard (tailnet-only)"]
    assert item.status is CheckStatus.OK
    assert "100.64.0.1" in item.detail


def test_docker_network_created_ok_missing_warn():
    common = dict(
        docker_installed=True,
        service="traefik",
        present=True,
        listening={80: True, 443: True},
        network_name="traefik",
        dashboard_port=8080,
        dashboard_tailnet_only=True,
        tailnet_ip="100.64.0.1",
    )
    created = DockerReport(network_present=True, **common)
    missing = DockerReport(network_present=False, **common)
    assert _items(_base(docker=created), "Docker")["network"].status is CheckStatus.OK
    assert _items(_base(docker=missing), "Docker")["network"].status is CheckStatus.WARN


def test_sdci_installed_is_ok():
    pkgs = _items(_base(sdci_installed=True), "Packages")
    assert pkgs["sdci"].status is CheckStatus.OK
    assert pkgs["sdci"].detail == "installed (sdci-server)"


def test_sdci_not_installed_is_fail():
    pkgs = _items(_base(sdci_installed=False), "Packages")
    assert pkgs["sdci"].status is CheckStatus.FAIL
    assert pkgs["sdci"].detail == "not installed"


def test_unsupported_distro_still_includes_sdci_item():
    report = _base(packages=None, sdci_installed=True)
    pkgs = _items(report, "Packages")
    # dpkg SKIP row is present alongside the sdci OK row
    assert pkgs["packages"].status is CheckStatus.SKIP
    assert pkgs["sdci"].status is CheckStatus.OK


def test_services_list_includes_sdci():
    assert "sdci" in SERVICES
