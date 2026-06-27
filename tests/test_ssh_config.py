from fonfon.services.ssh_config import (
    SSHD_DROPIN_DIR,
    SSHD_DROPIN_PATH,
    render_authorized_keys,
    render_sshd_hardening,
)


def test_dropin_path_under_sshd_config_d():
    assert SSHD_DROPIN_DIR == "/etc/ssh/sshd_config.d"
    assert SSHD_DROPIN_PATH == "/etc/ssh/sshd_config.d/99-fonfon-hardening.conf"


def test_render_sshd_hardening_sets_all_directives():
    out = render_sshd_hardening()
    assert out.startswith("#")  # managed header first
    assert "PermitRootLogin no" in out
    assert "PasswordAuthentication no" in out
    assert "PubkeyAuthentication yes" in out
    assert "KbdInteractiveAuthentication no" in out
    assert "PermitEmptyPasswords no" in out


def test_render_authorized_keys_has_header_and_keys():
    out = render_authorized_keys("octocat", ["ssh-ed25519 AAA", "ssh-rsa BBB"])
    assert "github.com/octocat" in out
    assert "ssh-ed25519 AAA" in out
    assert "ssh-rsa BBB" in out
    assert out.endswith("\n")
