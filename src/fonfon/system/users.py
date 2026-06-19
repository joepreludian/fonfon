"""Boundary adapter for local user/group management."""

from collections.abc import Callable

from fonfon.system._run import run as _default_run


class Users:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def exists(self, user: str) -> bool:
        return self._run(["id", "-u", user]).returncode == 0

    def in_group(self, user: str, group: str) -> bool:
        proc = self._run(["id", "-nG", user])
        return proc.returncode == 0 and group in proc.stdout.split()

    def create(self, user: str) -> None:
        proc = self._run(["useradd", "-m", "-s", "/bin/bash", user])
        if proc.returncode != 0:
            raise RuntimeError(f"useradd {user} failed: {proc.stderr.strip()}")

    def add_to_group(self, user: str, group: str) -> None:
        proc = self._run(["usermod", "-aG", group, user])
        if proc.returncode != 0:
            detail = proc.stderr.strip()
            raise RuntimeError(f"usermod -aG {group} {user} failed: {detail}")
