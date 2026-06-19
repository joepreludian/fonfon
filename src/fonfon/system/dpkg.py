"""Boundary adapter for dpkg-query: package state + version."""

from collections.abc import Callable

from pydantic import BaseModel

from fonfon.system._run import run as _default_run


class PackageState(BaseModel):
    name: str
    installed: bool
    version: str | None = None


class Dpkg:
    def __init__(self, run: Callable = _default_run):
        self._run = run

    def query(self, name: str) -> PackageState:
        proc = self._run(["dpkg-query", "-W", "-f=${Status} ${Version}", name])
        if proc.returncode != 0:
            return PackageState(name=name, installed=False, version=None)
        parts = proc.stdout.strip().split()
        # Status format: "<want> <flag> <status> [<version>]"
        # held packages: "hold ok installed <version>"
        installed = len(parts) >= 3 and parts[2] == "installed"
        version = parts[3] if installed and len(parts) >= 4 else None
        return PackageState(name=name, installed=installed, version=version)
