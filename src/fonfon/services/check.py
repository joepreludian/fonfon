"""The `check` use-case: compose domain services and apply status policy."""

from fonfon.models import CheckItem, CheckReport, CheckSection, CheckStatus
from fonfon.services.docker_service import DockerReport, DockerService
from fonfon.services.network_service import NetworkInfo, NetworkService
from fonfon.services.os_service import OSInfo, OSService
from fonfon.services.package_backends import (
    UnsupportedDistroError,
    select_package_backend,
)
from fonfon.services.package_service import PackageReport, PackageService
from fonfon.services.systemd_service import ServicesReport, SystemdService
from fonfon.system.pipx import Pipx

PACKAGES = ["sudo", "docker-ce", "tailscale", "pipx"]
SERVICES = ["docker", "ssh", "tailscaled", "sdci"]
TRAEFIK_PORTS = [80, 443]


def run_check() -> CheckReport:
    os_info = OSService().get_info()
    services = SystemdService().for_services(SERVICES).get_status()
    network = NetworkService().get_ips()
    docker = (
        DockerService()
        .for_service("traefik")
        .ensure_listening(host="0.0.0.0", ports=TRAEFIK_PORTS)
    )
    try:
        backend = select_package_backend(os_info.distro_id)
        packages: PackageReport | None = (
            PackageService(backend).for_packages(PACKAGES).ensure_installed()
        )
    except UnsupportedDistroError:
        packages = None
    sdci_installed = Pipx().has_executable("sdci-server")
    return build_report(
        os_info, packages, services, network, docker, sdci_installed=sdci_installed
    )


def build_report(
    os_info: OSInfo,
    packages: PackageReport | None,
    services: ServicesReport,
    network: NetworkInfo,
    docker: DockerReport,
    *,
    sdci_installed: bool = False,
) -> CheckReport:
    return CheckReport(
        sections=[
            _system_section(os_info),
            _packages_section(os_info, packages, sdci_installed),
            _services_section(services),
            _network_section(network),
            _docker_section(docker),
        ]
    )


def _system_section(os_info: OSInfo) -> CheckSection:
    return CheckSection(
        title="System",
        items=[
            CheckItem(
                key="system.distro",
                label="Distro",
                status=CheckStatus.INFO,
                detail=os_info.distro,
            ),
            CheckItem(
                key="system.arch",
                label="Architecture",
                status=CheckStatus.INFO,
                detail=os_info.architecture,
            ),
        ],
    )


def _packages_section(
    os_info: OSInfo, packages: PackageReport | None, sdci_installed: bool
) -> CheckSection:
    if packages is None:
        items: list[CheckItem] = [
            CheckItem(
                key="package.unsupported",
                label="packages",
                status=CheckStatus.SKIP,
                detail=f"package checks unsupported on {os_info.distro_id}",
            )
        ]
    else:
        items = [
            CheckItem(
                key=f"package.{p.name}",
                label=p.name,
                status=CheckStatus.OK if p.installed else CheckStatus.FAIL,
                detail=p.version if p.installed else "not installed",
            )
            for p in packages.packages
        ]
    # sdci is installed via pipx, which is distro-agnostic — always include it
    items.append(
        CheckItem(
            key="package.sdci",
            label="sdci",
            status=CheckStatus.OK if sdci_installed else CheckStatus.FAIL,
            detail="installed (sdci-server)" if sdci_installed else "not installed",
        )
    )
    return CheckSection(title="Packages", items=items)


def _services_section(services: ServicesReport) -> CheckSection:
    items = []
    for s in services.services:
        if s.enabled:
            detail = "enabled, active" if s.active else "enabled, inactive"
        elif not s.present:
            detail = "not found"
        else:
            detail = "not enabled"
        items.append(
            CheckItem(
                key=f"service.{s.name}",
                label=s.name,
                status=CheckStatus.OK if s.enabled else CheckStatus.FAIL,
                detail=detail,
            )
        )
    return CheckSection(title="Services", items=items)


def _network_section(network: NetworkInfo) -> CheckSection:
    items = [
        CheckItem(key=f"network.{name}", label=name, status=CheckStatus.INFO, detail=ip)
        for name, ip in network.interfaces.items()
    ]
    items.append(
        CheckItem(
            key="network.public",
            label="public",
            status=CheckStatus.INFO,
            detail=network.public_ip or "unknown",
        )
    )
    return CheckSection(title="Network", items=items)


def _docker_section(docker: DockerReport) -> CheckSection:
    if not docker.docker_installed:
        return CheckSection(
            title="Docker",
            items=[
                CheckItem(
                    key="docker.skip",
                    label="docker",
                    status=CheckStatus.SKIP,
                    detail="docker not installed",
                )
            ],
        )
    name = docker.service or "service"
    present = CheckItem(
        key="docker.traefik",
        label=name,
        status=CheckStatus.OK if docker.present else CheckStatus.WARN,
        detail="running" if docker.present else "container not running",
    )
    ports = CheckItem(
        key="docker.ports",
        label="ports 80/443",
        status=(
            CheckStatus.OK
            if all(docker.listening.values()) and docker.listening
            else CheckStatus.WARN
        ),
        detail=(
            "listening"
            if all(docker.listening.values()) and docker.listening
            else "not listening"
        ),
    )
    network = CheckItem(
        key="docker.network",
        label="ext. network",
        status=CheckStatus.OK if docker.external_network else CheckStatus.WARN,
        detail="attached" if docker.external_network else "none attached",
    )
    return CheckSection(title="Docker", items=[present, ports, network])
