"""Boundary adapter for apt: update, install, repo/keyring setup."""

import pathlib
from collections.abc import Callable

from fonfon.system._run import run as _default_run

_NONINTERACTIVE = {"DEBIAN_FRONTEND": "noninteractive"}
APT_TIMEOUT = 600  # installs can be slow


class Apt:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def _check(self, proc, what: str) -> None:
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"{what} failed (rc {proc.returncode}): {detail}")

    def update(self) -> None:
        self._check(
            self._run(["apt-get", "update"], timeout=APT_TIMEOUT, env=_NONINTERACTIVE),
            "apt-get update",
        )

    def install(self, *packages: str) -> None:
        self._check(
            self._run(
                ["apt-get", "install", "-y", *packages],
                timeout=APT_TIMEOUT,
                env=_NONINTERACTIVE,
            ),
            f"apt-get install {' '.join(packages)}",
        )

    def add_keyring(self, url: str, dest: str) -> None:
        self._check(
            self._run(["install", "-m", "0755", "-d", "/etc/apt/keyrings"]),
            "mkdir keyrings",
        )
        self._check(
            self._run(["curl", "-fsSL", url, "-o", dest], timeout=APT_TIMEOUT),
            f"curl {url}",
        )
        self._check(
            self._run(["chmod", "a+r", dest]),
            f"chmod {dest}",
        )

    def add_repo(self, content: str, dest: str) -> None:
        pathlib.Path(dest).write_text(content)
