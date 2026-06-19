"""Tests for the Apt boundary adapter."""

import pytest

from fonfon.system.apt import Apt
from tests.fakes import completed


def _record():
    calls = []

    def run(args, timeout=10, env=None):
        calls.append((args, env))
        return completed(args, 0, "")

    return calls, run


def test_update_runs_apt_get_update():
    calls, run = _record()
    Apt(run=run).update()
    assert calls[-1][0] == ["apt-get", "update"]


def test_install_uses_noninteractive_yes():
    calls, run = _record()
    Apt(run=run).install("ca-certificates", "curl")
    args, env = calls[-1]
    assert args[:3] == ["apt-get", "install", "-y"]
    assert "ca-certificates" in args and "curl" in args
    assert env["DEBIAN_FRONTEND"] == "noninteractive"


def test_install_raises_on_failure():
    def run(args, timeout=10, env=None):
        return completed(args, 100, "", "boom")

    with pytest.raises(RuntimeError):
        Apt(run=run).install("docker-ce")


def test_update_raises_on_failure():
    def run(args, timeout=10, env=None):
        return completed(args, 1, "", "E: failed")

    with pytest.raises(RuntimeError):
        Apt(run=run).update()


def test_add_keyring_issues_install_curl_chmod():
    calls, run = _record()
    Apt(run=run).add_keyring("https://example.com/key.asc", "/etc/apt/keyrings/key.asc")
    argv_list = [c[0] for c in calls]
    assert any(a[0] == "install" and "-d" in a for a in argv_list), "mkdir step missing"
    assert any(a[0] == "curl" for a in argv_list), "curl step missing"
    assert any(a[0] == "chmod" for a in argv_list), "chmod step missing"


def test_add_keyring_raises_on_curl_failure():
    def run(args, timeout=10, env=None):
        rc = 1 if args[0] == "curl" else 0
        return completed(args, rc, "", "curl error")

    with pytest.raises(RuntimeError):
        Apt(run=run).add_keyring("https://example.com/key.asc", "/tmp/key.asc")


def test_add_repo_writes_file_content(tmp_path):
    dest = str(tmp_path / "docker.list")
    calls, run = _record()
    Apt(run=run).add_repo("deb https://example.com stable main\n", dest)
    import pathlib

    assert pathlib.Path(dest).read_text() == "deb https://example.com stable main\n"
    # add_repo must NOT have issued any run calls
    assert calls == []
