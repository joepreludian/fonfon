"""Derive the operator's Traefik service-directory paths from a username."""

from pydantic import BaseModel


class TraefikPaths(BaseModel):
    """Paths for the Traefik service-directory tree under a user's home."""

    base: str
    acme: str
    dynamic: str
    compose_file: str
    static_config: str


def traefik_paths(user: str) -> TraefikPaths:
    """Return the Traefik service-dir tree for `user` under their home directory."""
    base = f"/home/{user}/services/traefik"
    return TraefikPaths(
        base=base,
        acme=f"{base}/acme",
        dynamic=f"{base}/dynamic",
        compose_file=f"{base}/docker-compose.yml",
        static_config=f"{base}/traefik.yml",
    )
