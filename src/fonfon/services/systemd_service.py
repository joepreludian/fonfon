"""Systemd domain service. Returns plain-fact DTOs; no policy."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from fonfon.system.systemctl import Systemctl


class ServiceState(BaseModel):
    name: str
    present: bool
    enabled: bool
    active: bool


class ServicesReport(BaseModel):
    services: list[ServiceState]


class SystemdService:
    def __init__(self, systemctl: Systemctl | None = None):
        self._systemctl = systemctl or Systemctl()
        self._names: list[str] = []

    def for_services(self, names: Iterable[str]) -> SystemdService:
        self._names = list(names)
        return self

    def get_status(self) -> ServicesReport:
        states = [
            ServiceState(
                name=name,
                present=self._systemctl.exists(name),
                enabled=self._systemctl.is_enabled(name),
                active=self._systemctl.is_active(name),
            )
            for name in self._names
        ]
        return ServicesReport(services=states)
