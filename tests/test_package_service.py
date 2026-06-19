"""Tests for PackageService and PackageReport."""

from fonfon.services.package_service import PackageService
from fonfon.system.dpkg import PackageState


class FakeBackend:
    def query(self, name):
        return PackageState(
            name=name,
            installed=(name == "sudo"),
            version="1" if name == "sudo" else None,
        )


def test_for_packages_then_ensure_installed_returns_report():
    svc = PackageService(FakeBackend()).for_packages(["sudo", "docker-ce"])
    report = svc.ensure_installed()
    by_name = {p.name: p for p in report.packages}
    assert by_name["sudo"].installed is True
    assert by_name["docker-ce"].installed is False


def test_for_packages_is_fluent():
    svc = PackageService(FakeBackend())
    assert svc.for_packages(["sudo"]) is svc
