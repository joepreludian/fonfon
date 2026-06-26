"""Boundary adapter for docker compose: bring a stack up."""

from collections.abc import Callable

from fonfon.system._run import run as _default_run

DOCKER_COMPOSE_TIMEOUT = 600  # image pulls + container start can be slow


class DockerCompose:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def up(self, compose_file: str) -> None:
        proc = self._run(
            ["docker", "compose", "-f", compose_file, "up", "-d"],
            timeout=DOCKER_COMPOSE_TIMEOUT,
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(
                f"docker compose up failed (rc {proc.returncode}): {detail}"
            )
