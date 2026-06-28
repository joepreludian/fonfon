"""Boundary adapter for the docker CLI: availability and container inspection."""

import json
from collections.abc import Callable
from typing import Any

from fonfon.system._run import run as _default_run


class DockerCli:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def cli_present(self) -> bool:
        """True if the docker client is installed (no daemon contact)."""
        return self._run(["docker", "--version"]).returncode == 0

    def socket_status(self) -> str:
        """Report reachability of the docker daemon over its socket.

        Asking for `.Server.Version` forces a round-trip to the daemon through
        `/var/run/docker.sock` — the very socket Traefik mounts to discover
        containers. Returns one of:

        - ``"ready"``  — the daemon answered.
        - ``"denied"`` — the socket exists but the current user can't read it
          (needs sudo or membership of the ``docker`` group).
        - ``"down"``   — the daemon is unreachable (not running / no socket).
        """
        proc = self._run(["docker", "version", "--format", "{{.Server.Version}}"])
        if proc.returncode == 0:
            return "ready"
        if "permission denied" in (proc.stderr or "").lower():
            return "denied"
        return "down"

    def inspect_container(self, name: str) -> dict[str, Any] | None:
        proc = self._run(["docker", "inspect", name])
        if proc.returncode != 0:
            return None
        data = json.loads(proc.stdout or "[]")
        return data[0] if data else None

    def network_exists(self, name: str) -> bool:
        return self._run(["docker", "network", "inspect", name]).returncode == 0

    def create_network(self, name: str) -> None:
        proc = self._run(["docker", "network", "create", name])
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"docker network create {name} failed (rc {proc.returncode}): {detail}"
            )
