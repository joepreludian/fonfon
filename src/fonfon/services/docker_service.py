"""Docker domain service. Returns plain-fact DTO; no policy."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fonfon.system.docker_cli import DockerCli

_DEFAULT_NETWORKS = {"bridge", "host", "none"}


class DockerReport(BaseModel):
    docker_installed: bool
    service: str | None = None
    present: bool = False
    host: str | None = None
    listening: dict[int, bool] = Field(default_factory=dict)
    external_network: bool = False


class DockerService:
    def __init__(self, docker: DockerCli | None = None):
        self._docker = docker or DockerCli()
        self._service: str | None = None

    def for_service(self, name: str) -> DockerService:
        self._service = name
        return self

    def ensure_listening(self, host: str, ports: list[int]) -> DockerReport:
        if not self._docker.is_available():
            return DockerReport(
                docker_installed=False,
                service=self._service,
                host=host,
                listening={p: False for p in ports},
            )
        inspect = self._docker.inspect_container(self._service)
        if inspect is None:
            return DockerReport(
                docker_installed=True,
                service=self._service,
                present=False,
                host=host,
                listening={p: False for p in ports},
                external_network=False,
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
        networks = set(net.get("Networks", {}).keys())
        return DockerReport(
            docker_installed=True,
            service=self._service,
            present=True,
            host=host,
            listening=listening,
            external_network=bool(networks - _DEFAULT_NETWORKS),
        )
