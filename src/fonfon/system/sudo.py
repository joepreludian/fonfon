"""Boundary adapter for privilege detection: root and sudo availability."""

import os
from collections.abc import Callable

from fonfon.system._run import run as _default_run


class Sudo:
    def __init__(
        self,
        run: Callable = _default_run,
        geteuid: Callable[[], int] = os.geteuid,
    ):
        self._run = run
        self._geteuid = geteuid

    def is_root(self) -> bool:
        return self._geteuid() == 0

    def can_sudo(self) -> bool:
        """True if the current user can elevate via sudo.

        Root always can. Otherwise probe non-interactively with `sudo -nv`:
        a zero exit means passwordless sudo, while a non-zero exit whose stderr
        asks for a password still means the user *is* a sudoer (just needs one).
        A genuine "may not run sudo" reply — or a missing binary — is False.
        """
        if self.is_root():
            return True
        proc = self._run(["sudo", "-nv"])
        if proc.returncode == 0:
            return True
        return "password is required" in (proc.stderr or "").lower()
