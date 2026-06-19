"""Network domain service. Returns plain-fact DTO; no policy."""

from collections.abc import Callable

from pydantic import BaseModel

from fonfon.system import probes


class NetworkInfo(BaseModel):
    interfaces: dict[str, str]
    public_ip: str | None = None


class NetworkService:
    def __init__(
        self,
        interfaces: Callable = probes.interfaces,
        public_ip: Callable = probes.public_ip,
    ):
        self._interfaces = interfaces
        self._public_ip = public_ip

    def get_ips(self) -> NetworkInfo:
        return NetworkInfo(interfaces=self._interfaces(), public_ip=self._public_ip())
