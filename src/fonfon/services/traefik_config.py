"""Pure renderers for Traefik's static config and docker-compose file.

YAML is emitted as plain strings to avoid a pyyaml runtime dependency.
"""

from fonfon.services.traefik_paths import TraefikPaths

TRAEFIK_IMAGE = "traefik:v3.7.5"
TRAEFIK_NETWORK = "traefik"


def render_static_config(cert_email: str) -> str:
    """Return Traefik's static `traefik.yml`.

    Entrypoints: web (:80, redirects to websecure + serves the ACME HTTP-01
    challenge) and websecure (:443). The Docker provider does not expose
    containers unless they opt in with labels. The dashboard is served on the
    `traefik` API (:8080); host-side port binding keeps it tailnet-only.
    """
    return f"""\
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

api:
  dashboard: true
  insecure: true

providers:
  docker:
    exposedByDefault: false
    network: {TRAEFIK_NETWORK}
  file:
    directory: /etc/traefik/dynamic
    watch: true

certificatesResolvers:
  le:
    acme:
      email: {cert_email}
      storage: /acme/acme.json
      httpChallenge:
        entryPoint: web
"""


def render_compose(tailnet_ip: str, paths: TraefikPaths) -> str:
    """Return the Traefik `docker-compose.yml`.

    Publishes :80 and :443 on all interfaces and the dashboard (:8080) only on
    the host's tailnet IP, mounts the docker socket read-only plus the generated
    config, and joins the external `traefik` network.
    """
    return f"""\
services:
  traefik:
    image: {TRAEFIK_IMAGE}
    container_name: traefik
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "{tailnet_ip}:8080:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - {paths.static_config}:/etc/traefik/traefik.yml:ro
      - {paths.dynamic}:/etc/traefik/dynamic:ro
      - {paths.acme}:/acme
    networks:
      - {TRAEFIK_NETWORK}

networks:
  {TRAEFIK_NETWORK}:
    external: true
"""
