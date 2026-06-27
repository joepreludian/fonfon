# Bare `fonfon` usage hint — design + implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Date:** 2026-06-27
**Status:** Approved

## Summary

Today `fonfon` with no subcommand prints only the hello banner
(`cli.main` → `build_banner()`). This adds a **usage hint** beneath the banner
showing how to run the two primary commands:

- `fonfon check` — report whether the server is ready to serve apps.
- `sudo fonfon setup <user> --tailscale-key <key>` — provision the server
  (shown **with `sudo`**, since setup must run as root).

Nothing else changes: the banner still prints, exit code stays `0`, and the hint
appears only on the bare `fonfon` invocation (not for subcommands or `--help`).

## Design

- New renderable `build_usage_hint() -> RenderableType` in `src/fonfon/ui.py`,
  styled like the existing `build_banner`/`build_action_box` (orange palette,
  `Panel.fit`). A two-column `Table.grid`: command (bold bright) → one-line
  description (dim), inside a `Panel.fit` titled "Get started".
- `cli.main` prints it right after the banner when `ctx.invoked_subcommand is
  None`.

```python
# ui.py
def build_usage_hint() -> RenderableType:
    """Panel listing the two primary commands and how to run them."""
    grid = Table.grid(padding=(0, 3))
    grid.add_column(style=f"bold {ORANGE_BRIGHT}")
    grid.add_column(style=ORANGE_DIM)
    grid.add_row(
        "fonfon check", "Report whether this server is ready to serve apps"
    )
    grid.add_row(
        "sudo fonfon setup <user> --tailscale-key <key>", "Provision this server"
    )
    return Panel.fit(grid, title="Get started", border_style=ORANGE, padding=(1, 2))
```

```python
# cli.py main()
    if ctx.invoked_subcommand is None:
        console = Console()
        console.print(build_banner())
        console.print(build_usage_hint())
```

## Global Constraints

- The hint shows exactly the two commands above; `setup` is shown with `sudo`.
- Only the bare-`fonfon` path changes; subcommands and `--help` are untouched.
- TDD: failing test first; `uv run pytest`; pre-commit hook on every commit;
  conventional commits; no "Co-authored-by".
- Do NOT bump the version in per-task commits — the single minor bump happens in
  the final docs task only.

---

### Task 1: `build_usage_hint` + wire into the bare command

**Files:**
- Modify: `src/fonfon/ui.py`, `src/fonfon/cli.py`
- Test: `tests/test_ui.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `build_usage_hint() -> RenderableType`; `cli.main` prints the banner
  then the usage hint on the no-subcommand path.

- [ ] **Step 1: Write the failing tests**

In `tests/test_ui.py`, add `build_usage_hint` to the existing
`from fonfon.ui import ...` line, then append:

```python
def test_usage_hint_shows_check_and_setup_commands():
    out = _render(build_usage_hint())
    assert "fonfon check" in out
    assert "sudo fonfon setup" in out
```

In `tests/test_cli.py`, append:

```python
def test_cli_shows_usage_hints():
    result = CliRunner().invoke(main)
    assert "fonfon check" in result.output
    assert "sudo fonfon setup" in result.output
```

- [ ] **Step 2: Run the tests to confirm they fail**

`uv run pytest tests/test_ui.py tests/test_cli.py -v` — fail (no `build_usage_hint`; bare output lacks the hints).

- [ ] **Step 3: Implement** `build_usage_hint` in `ui.py` (code above) and import + call it in `cli.py`'s `main` (code above).

- [ ] **Step 4: Run** `uv run pytest tests/test_ui.py tests/test_cli.py -v` → green; then `uv run pytest -q` once.

- [ ] **Step 5: Commit** — `feat: show check/setup usage hint on bare fonfon`.

---

### Task 2: Documentation + version bump

**Files:**
- Modify: `docs/manual/docs/getting-started.md`
- Modify: `pyproject.toml`
- Regenerate: `docs/manual/site/`

- [ ] **Step 1:** `uv run pytest` → green baseline.
- [ ] **Step 2:** In `docs/manual/docs/getting-started.md`, add a short note that running `fonfon` with no arguments prints the banner plus quick usage for `fonfon check` and `sudo fonfon setup`.
- [ ] **Step 3:** Bump `pyproject.toml` by one minor (new feature) over whatever it currently reads.
- [ ] **Step 4:** `uv run mkdocs build -f docs/manual/mkdocs.yml` → no errors.
- [ ] **Step 5:** Commit — `docs: note the bare-fonfon usage hint; bump version`.

## Self-review notes (author)

- Substring assertions (`"fonfon check"`, `"sudo fonfon setup"`) are contiguous at the start of their grid cells, so rich wrapping at width 80 cannot split them.
- The hint is gated on `ctx.invoked_subcommand is None`, so `--help` and subcommands are unaffected.
