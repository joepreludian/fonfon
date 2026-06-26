# Traefik

When `fonfon setup` is given `--traefik-cert-email`, it provisions
[Traefik](https://traefik.io) as the server's edge reverse proxy via Docker
Compose. Traefik serves your applications publicly on **:80** (HTTP→HTTPS
redirect + the ACME HTTP-01 challenge) and **:443** (TLS), while its
**dashboard is reachable only over the tailnet**.

## What gets created

Under the operator's home (`/home/<user>/services/traefik`):

| Path | Purpose |
|------|---------|
| `docker-compose.yml` | The Traefik service definition (image pinned to `traefik:v3.7.5`) |
| `traefik.yml` | Static configuration (entrypoints, providers, ACME resolver) |
| `acme/` | Stores `acme.json` (issued certificates) |
| `dynamic/` | File-provider directory for extra dynamic config (watched) |

Plus an **external Docker network** named `traefik`, and the running `traefik`
container.

## The dashboard is tailnet-only

The dashboard/API (`api.insecure: true`, port 8080 in the container) is
published on the host as `<tailnet_ip>:8080:8080` — bound solely to the
Tailscale interface. It is **not** reachable from the public internet. Browse to
`http://<tailnet_ip>:8080/dashboard/` from a device on your tailnet. Ports
`:80`/`:443` publish on all interfaces and remain public.

## Containers are not exposed by default

`providers.docker.exposedByDefault` is `false`. A container is only routed when
it opts in with `traefik.*` labels **and** joins the external `traefik` network.

## Exposing an application

In the application's own `docker-compose.yml`:

```yaml
services:
  myapp:
    image: ghcr.io/example/myapp:latest
    networks: [traefik]
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.myapp.rule=Host(`app.example.com`)"
      - "traefik.http.routers.myapp.entrypoints=websecure"
      - "traefik.http.routers.myapp.tls.certresolver=le"
      # only if the app does NOT listen on port 80 inside the container:
      - "traefik.http.services.myapp.loadbalancer.server.port=3000"

networks:
  traefik:
    external: true
```

- `traefik.enable=true` — opt this container in.
- `rule=Host(...)` — the public hostname (its DNS A record must point at the VPS).
- `entrypoints=websecure` — serve on :443.
- `tls.certresolver=le` — obtain/renew a Let's Encrypt certificate (HTTP-01).

## Certificates

Certificates are issued via Let's Encrypt's **HTTP-01** challenge on the `web`
entrypoint and stored in `acme/acme.json`. The registration email is the value
of `--traefik-cert-email`. Port 80 must be publicly reachable for issuance and
renewal; the global HTTP→HTTPS redirect does not interfere — Traefik serves the
challenge path ahead of the redirect.

!!! note "Re-running setup"
    The Traefik step is idempotent on the *running container*: if `traefik` is
    already up, re-running `fonfon setup` reports it `skipped` and does **not**
    rewrite `traefik.yml` / `docker-compose.yml`. To change configuration, edit
    the file under `~/services/traefik` and run `docker compose up -d` there.
