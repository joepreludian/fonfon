"""Package detection strategy keyed on distro ID."""

from __future__ import annotations

from abc import ABC, abstractmethod

from fonfon.system.dpkg import Dpkg, PackageState


class PackageBackend(ABC):
    @abstractmethod
    def query(self, name: str) -> PackageState: ...


class DebianPackageBackend(PackageBackend):
    """dpkg family: debian, ubuntu, raspbian."""

    def __init__(self, dpkg: Dpkg | None = None):
        self._dpkg = dpkg or Dpkg()

    def query(self, name: str) -> PackageState:
        return self._dpkg.query(name)


class UnsupportedDistroError(Exception):
    """Raised when no package backend is registered for a distro."""


_REGISTRY: dict[str, type[PackageBackend]] = {
    "debian": DebianPackageBackend,
    "ubuntu": DebianPackageBackend,
    "raspbian": DebianPackageBackend,
}


def select_package_backend(distro_id: str) -> PackageBackend:
    backend_cls = _REGISTRY.get(distro_id.lower())
    if backend_cls is None:
        raise UnsupportedDistroError(distro_id)
    return backend_cls()
