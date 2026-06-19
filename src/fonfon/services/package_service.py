"""Package domain service. Returns plain-fact DTO; no policy."""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from fonfon.services.package_backends import PackageBackend
from fonfon.system.dpkg import PackageState


class PackageReport(BaseModel):
    packages: list[PackageState]


class PackageService:
    def __init__(self, backend: PackageBackend):
        self._backend = backend
        self._names: list[str] = []

    def for_packages(self, names: Iterable[str]) -> PackageService:
        self._names = list(names)
        return self

    def ensure_installed(self) -> PackageReport:
        return PackageReport(packages=[self._backend.query(n) for n in self._names])
