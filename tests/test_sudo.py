"""Tests for the Sudo privilege probe."""

from fonfon.system.sudo import Sudo
from tests.fakes import completed


def test_is_root_true_when_euid_zero():
    assert Sudo(geteuid=lambda: 0).is_root() is True


def test_is_root_false_when_euid_nonzero():
    assert Sudo(geteuid=lambda: 1000).is_root() is False


def test_can_sudo_true_for_root_without_probing():
    def run(args, timeout=10):
        raise AssertionError("root should not shell out to sudo")

    assert Sudo(run=run, geteuid=lambda: 0).can_sudo() is True


def test_can_sudo_true_when_passwordless():
    sudo = Sudo(run=lambda args, timeout=10: completed(args, 0), geteuid=lambda: 1000)
    assert sudo.can_sudo() is True


def test_can_sudo_true_when_password_required():
    """A sudoer who just needs a password still *has* sudo rights."""
    stderr = "sudo: a password is required"
    sudo = Sudo(
        run=lambda args, timeout=10: completed(args, 1, "", stderr),
        geteuid=lambda: 1000,
    )
    assert sudo.can_sudo() is True


def test_can_sudo_false_when_not_a_sudoer():
    stderr = "Sorry, user bob may not run sudo on host."
    sudo = Sudo(
        run=lambda args, timeout=10: completed(args, 1, "", stderr),
        geteuid=lambda: 1000,
    )
    assert sudo.can_sudo() is False


def test_can_sudo_false_when_sudo_binary_absent():
    sudo = Sudo(
        run=lambda args, timeout=10: completed(args, 127, "", ""),
        geteuid=lambda: 1000,
    )
    assert sudo.can_sudo() is False
