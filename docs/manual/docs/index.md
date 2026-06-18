# Fonfon

**Fonfon** is an opinionated VPS configurator. It sets up a base Linux system,
ready to serve applications, with sensible defaults so you don't have to wire
everything by hand.

!!! info "About the name"
    "Fonfon" is an homage to my cat Persephone — an orange one with a short
    tail. 🐱

## What it does

- **SSH hardening** — lock down remote access out of the box.
- **Package installation** — Docker, Tailscale, and SDCI.
- **Service setup** — wire up the services needed for a simple, ready system.

## How it ships

Fonfon is a self-contained `pex` executable, so you can run it on a fresh
server without installing any dependencies first.

```bash
fonfon --help
```

## Next steps

Head over to [Getting Started](getting-started.md) to configure your first
server.
