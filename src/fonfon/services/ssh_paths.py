"""Derive the operator's SSH paths (.ssh dir + authorized_keys) from a username."""

from pydantic import BaseModel


class SshPaths(BaseModel):
    """Paths for the operator's SSH setup under their home directory."""

    ssh_dir: str
    authorized_keys: str


def ssh_paths(user: str) -> SshPaths:
    """Return the `.ssh` dir and `authorized_keys` path for `user`."""
    ssh_dir = f"/home/{user}/.ssh"
    return SshPaths(ssh_dir=ssh_dir, authorized_keys=f"{ssh_dir}/authorized_keys")
