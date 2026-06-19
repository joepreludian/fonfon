from fonfon.system.dpkg import Dpkg
from tests.fakes import completed


def test_query_installed_with_version():
    out = "install ok installed 1.9.13p3-1+deb12u1\n"
    dpkg = Dpkg(run=lambda args, timeout=10: completed(args, 0, out))
    state = dpkg.query("sudo")
    assert state.installed is True
    assert state.version == "1.9.13p3-1+deb12u1"
    assert state.name == "sudo"


def test_query_not_installed_returns_false_none():
    dpkg = Dpkg(
        run=lambda args, timeout=10: completed(args, 1, "", "no packages found")
    )
    state = dpkg.query("docker-ce")
    assert state.installed is False
    assert state.version is None


def test_query_held_package_is_installed():
    out = "hold ok installed 27.3.1-1\n"
    dpkg = Dpkg(run=lambda args, timeout=10: completed(args, 0, out))
    state = dpkg.query("docker-ce")
    assert state.installed is True
    assert state.version == "27.3.1-1"
