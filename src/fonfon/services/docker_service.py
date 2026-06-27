"""Docker domain service. Returns plain-fact DTO; no policy."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fonfon.system.docker_cli import DockerCli


class DockerReport(BaseModel):
    docker_installed: bool
    service: str | None = None
    present: bool = False
    host: str | None = None
    listening: dict[int, bool] = Field(default_factory=dict)
    network_name: str | None = None
    network_present: bool = False
    dashboard_port: int | None = None
    dashboard_tailnet_only: bool = False
    dashboard_public: bool = False
    tailnet_ip: str | None = None


class DockerService:
    def __init__(self, docker: DockerCli | None = None):
        self._docker = docker or DockerCli()
        self._service: str | None = None

    def for_service(self, name: str) -> DockerService:
        self._service = name
        return self

    def ensure_listening(
        self,
        host: str,
        ports: list[int],
        *,
        network: str | None = None,
        dashboard_port: int | None = None,
        tailnet_ip: str | None = None,
    ) -> DockerReport:
        if not self._docker.is_available():
            return DockerReport(
                docker_installed=False,
                service=self._service,
                host=host,
                listening={p: False for p in ports},
                network_name=network,
                dashboard_port=dashboard_port,
                tailnet_ip=tailnet_ip,
            )
        network_present = self._docker.network_exists(network) if network else False
        inspect = self._docker.inspect_container(self._service)
        if inspect is None:
            return DockerReport(
                docker_installed=True,
                service=self._service,
                present=False,
                host=host,
                listening={p: False for p in ports},
                network_name=network,
                network_present=network_present,
                dashboard_port=dashboard_port,
                tailnet_ip=tailnet_ip,
            )
        net = inspect.get("NetworkSettings", {})
        published = net.get("Ports") or {}
        listening = {
            port: any(
                b.get("HostPort") == str(port) and b.get("HostIp") in (host, "0.0.0.0")
                for b in (published.get(f"{port}/tcp") or [])
            )
            for port in ports
        }
        dashboard_public = False
        dashboard_tailnet_only = False
        if dashboard_port is not None:
            binds = published.get(f"{dashboard_port}/tcp") or []
            host_ips = [b.get("HostIp") for b in binds]
            dashboard_public = any(ip in {"0.0.0.0", "::", ""} for ip in host_ips)
            dashboard_tailnet_only = (
                bool(binds)
                and tailnet_ip is not None
                and all(ip == tailnet_ip for ip in host_ips)
            )
        return DockerReport(
            docker_installed=True,
            service=self._service,
            present=True,
            host=host,
            listening=listening,
            network_name=network,
            network_present=network_present,
            dashboard_port=dashboard_port,
            dashboard_public=dashboard_public,
            dashboard_tailnet_only=dashboard_tailnet_only,
            tailnet_ip=tailnet_ip,
        )
