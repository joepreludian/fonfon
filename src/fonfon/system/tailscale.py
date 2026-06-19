"""Boundary adapter for the Tailscale CLI: join the tailnet and read its IP."""

from collections.abc import Callable

from fonfon.system._run import run as _default_run

TAILSCALE_UP_TIMEOUT = 60


class Tailscale:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def up(self, auth_key: str) -> None:
        proc = self._run(
            ["tailscale", "up", "--auth-key", auth_key],
            timeout=TAILSCALE_UP_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"tailscale up failed (rc {proc.returncode}): {detail}")

    def ipv4(self) -> str | None:
        proc = self._run(["tailscale", "ip", "-4"])
        if proc.returncode != 0:
            return None
        for line in proc.stdout.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return None
