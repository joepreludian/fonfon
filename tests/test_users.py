"""Tests for the Users boundary adapter."""

import pytest

from fonfon.system.users import Users
from tests.fakes import completed


def _ok(stdout=""):
    return lambda args, timeout=10, env=None: completed(args, 0, stdout)


def _fail(stderr=""):
    return lambda args, timeout=10, env=None: completed(args, 1, "", stderr)


def test_exists_true_on_zero_exit():
    assert Users(run=_ok("1001\n")).exists("jon") is True


def test_exists_false_on_nonzero():
    assert Users(run=_fail("no such user")).exists("ghost") is False


def test_in_group_parses_id_nG():
    users = Users(run=_ok("jon sudo docker\n"))
    assert users.in_group("jon", "docker") is True
    assert users.in_group("jon", "wheel") is False


def test_in_group_false_on_nonzero():
    assert Users(run=_fail("no such user")).in_group("ghost", "sudo") is False


def test_create_invokes_useradd():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        return completed(args, 0, "")

    Users(run=run).create("jon")
    assert seen["args"][0] == "useradd" and "jon" in seen["args"]


def test_create_passes_shell_and_home_flags():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        return completed(args, 0, "")

    Users(run=run).create("alice")
    assert "-m" in seen["args"]
    assert "-s" in seen["args"]
    assert "/bin/bash" in seen["args"]


def test_create_raises_on_failure():
    def run(args, timeout=10, env=None):
        return completed(args, 9, "", "already exists")

    with pytest.raises(RuntimeError):
        Users(run=run).create("jon")


def test_add_to_group_invokes_usermod_aG():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        return completed(args, 0, "")

    Users(run=run).add_to_group("jon", "docker")
    assert seen["args"] == ["usermod", "-aG", "docker", "jon"]


def test_add_to_group_raises_on_failure():
    def run(args, timeout=10, env=None):
        return completed(args, 1, "", "group not found")

    with pytest.raises(RuntimeError):
        Users(run=run).add_to_group("jon", "docker")
