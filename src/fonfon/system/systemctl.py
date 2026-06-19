"""Boundary adapter for systemctl: enabled/active/exists queries."""

from collections.abc import Callable

from fonfon.system._run import run as _default_run


class Systemctl:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def is_enabled(self, unit: str) -> bool:
        proc = self._run(["systemctl", "is-enabled", unit])
        return proc.returncode == 0 and proc.stdout.strip() == "enabled"

    def is_active(self, unit: str) -> bool:
        proc = self._run(["systemctl", "is-active", unit])
        return proc.returncode == 0 and proc.stdout.strip() == "active"

    def exists(self, unit: str) -> bool:
        proc = self._run(["systemctl", "is-enabled", unit])
        # is-enabled prints a known state for existing units; "not-found" -> absent
        return "not-found" not in (proc.stderr + proc.stdout).lower()
