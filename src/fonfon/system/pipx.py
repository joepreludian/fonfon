"""Boundary adapter for pipx: global install + package-presence check."""

from collections.abc import Callable

from fonfon.system._run import run as _default_run

PIPX_HOME = "/opt/pipx"
PIPX_BIN_DIR = "/usr/local/bin"
PIPX_TIMEOUT = 300
_GLOBAL_ENV = {"PIPX_HOME": PIPX_HOME, "PIPX_BIN_DIR": PIPX_BIN_DIR}


class Pipx:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def is_installed(self, package: str) -> bool:
        proc = self._run(["pipx", "list", "--short"], env=_GLOBAL_ENV)
        if proc.returncode != 0:
            return False
        return any(
            line.split()[:1] == [package]
            for line in proc.stdout.splitlines()
            if line.strip()
        )

    def install_global(self, package: str) -> None:
        proc = self._run(
            ["pipx", "install", package], timeout=PIPX_TIMEOUT, env=_GLOBAL_ENV
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"pipx install {package} failed: {detail}")
