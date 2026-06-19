"""OS identity domain service. Returns plain-fact DTO; no policy."""

from collections.abc import Callable

from pydantic import BaseModel

from fonfon.system import probes


class OSInfo(BaseModel):
    distro: str
    distro_id: str
    architecture: str


class OSService:
    def __init__(
        self,
        read_os_release: Callable = probes.read_os_release,
        machine: Callable = probes.machine,
    ):
        self._read_os_release = read_os_release
        self._machine = machine

    def get_info(self) -> OSInfo:
        data = self._read_os_release()
        return OSInfo(
            distro=data.get("PRETTY_NAME", "unknown"),
            distro_id=data.get("ID", "unknown"),
            architecture=self._machine(),
        )
