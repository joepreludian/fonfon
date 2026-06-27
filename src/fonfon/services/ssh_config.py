"""Pure renderers for the SSH hardening drop-in and authorized_keys file."""

SSHD_DROPIN_DIR = "/etc/ssh/sshd_config.d"
SSHD_DROPIN_PATH = f"{SSHD_DROPIN_DIR}/99-fonfon-hardening.conf"


def render_sshd_hardening() -> str:
    """Return fonfon's sshd hardening drop-in.

    Lands in /etc/ssh/sshd_config.d/, which Debian's stock sshd_config Includes,
    so these directives override the distro defaults. Disables root login and
    every password path (password + keyboard-interactive + empty) and enables
    public-key auth.
    """
    return """\
# Managed by fonfon — do not edit. Hardens SSH; see `fonfon setup --github-user`.
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
KbdInteractiveAuthentication no
PermitEmptyPasswords no
"""


def render_authorized_keys(github_user: str, keys: list[str]) -> str:
    """Return a fonfon-managed authorized_keys file for the given GitHub keys."""
    header = f"# Managed by fonfon — keys from github.com/{github_user}.keys"
    return "\n".join([header, *keys]) + "\n"
