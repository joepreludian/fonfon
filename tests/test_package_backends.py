"""Tests for package backend strategy and registry."""

import pytest

from fonfon.services.package_backends import (
    DebianPackageBackend,
    UnsupportedDistroError,
    select_package_backend,
)
from fonfon.system.dpkg import PackageState


class FakeDpkg:
    def __init__(self, installed):
        self._installed = installed

    def query(self, name):
        if name in self._installed:
            return PackageState(
                name=name, installed=True, version=self._installed[name]
            )
        return PackageState(name=name, installed=False, version=None)


def test_debian_backend_queries_via_dpkg():
    backend = DebianPackageBackend(dpkg=FakeDpkg({"sudo": "1.9.13"}))
    assert backend.query("sudo").installed is True
    assert backend.query("docker-ce").installed is False


def test_select_returns_debian_for_debian_family():
    assert isinstance(select_package_backend("debian"), DebianPackageBackend)
    assert isinstance(select_package_backend("ubuntu"), DebianPackageBackend)


def test_select_returns_debian_for_raspbian():
    assert isinstance(select_package_backend("raspbian"), DebianPackageBackend)


def test_select_raises_for_unknown_distro():
    with pytest.raises(UnsupportedDistroError):
        select_package_backend("fedora")


def test_select_is_case_insensitive():
    assert isinstance(select_package_backend("Debian"), DebianPackageBackend)
    assert isinstance(select_package_backend("UBUNTU"), DebianPackageBackend)
