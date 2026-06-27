# Getting Started

This page is a placeholder for the base manual. Flesh it out as Fonfon's
commands take shape.

## First run

Once `fonfon` is on the target host, run it with no arguments to get your
bearings:

```bash
fonfon
```

This prints the Fonfon banner and a quick-reference table showing the two
primary entry points:

- `fonfon check` — inspect the system and report readiness.
- `sudo fonfon setup <user> --tailscale-key <key>` — provision the server
  (Docker, Tailscale, sdci, and more).

## Requirements

- A fresh Linux VPS you can reach over SSH.
- The `fonfon` executable (a self-contained `pex` binary — no dependencies
  required on the target host).

## Running the manual locally

The manual is a MkDocs project stored in `docs/manual`. To preview it while
editing, serve it with live reload:

```bash
uv run mkdocs serve -f docs/manual/mkdocs.yml
```

Then open <http://127.0.0.1:8000> in your browser.

To produce the static site:

```bash
uv run mkdocs build -f docs/manual/mkdocs.yml
```

The rendered site is written to `docs/manual/site/` (git-ignored).
