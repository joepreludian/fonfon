"""Derive the operator's sdci service-directory paths from a username."""

from pydantic import BaseModel


class SdciPaths(BaseModel):
    base: str
    tasks: str
    uploads: str


def sdci_paths(user: str) -> SdciPaths:
    """Return the sdci service-dir tree for `user` under their home directory."""
    base = f"/home/{user}/services/sdci"
    return SdciPaths(base=base, tasks=f"{base}/tasks", uploads=f"{base}/uploads")
