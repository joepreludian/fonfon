"""Command-line entrypoint for Fonfon."""

import os

import click
from rich.console import Console

from fonfon import get_version
from fonfon.output import console as console_renderer
from fonfon.output import json as json_renderer
from fonfon.output import setup_console, setup_json
from fonfon.services.check import run_check
from fonfon.services.setup import run_setup
from fonfon.system.streaming import run_streamed
from fonfon.ui import build_banner


@click.group(invoke_without_command=True)
@click.version_option(version=get_version(), prog_name="Fonfon")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Fonfon — an opinionated VPS configurator."""
    if ctx.invoked_subcommand is None:
        Console().print(build_banner())


@main.command()
@click.option(
    "-o",
    "--output",
    "output_format",
    type=click.Choice(["console", "json"]),
    default="console",
    help="Output format.",
)
@click.pass_context
def check(ctx: click.Context, output_format: str) -> None:
    """Report whether this system is ready to serve applications."""
    report = run_check()
    console = Console()
    if output_format == "json":
        json_renderer.render(report, console)
    else:
        console_renderer.render(report, console)
    ctx.exit(0 if report.ok else 1)


@main.command()
@click.argument("new_user")
@click.option(
    "-o",
    "--output",
    "output_format",
    type=click.Choice(["console", "json"]),
    default="console",
    help="Output format.",
)
@click.pass_context
def setup(ctx: click.Context, new_user: str, output_format: str) -> None:
    """Provision this server (Docker, Tailscale, pipx, sdci) and an operator user."""
    if os.geteuid() != 0:
        Console().print("[red]fonfon setup must be run as root.[/red]")
        ctx.exit(1)
    console = Console()
    if output_format == "json":
        report = run_setup(new_user)
        setup_json.render(report, console)
    else:
        setup_console.render_header(console)
        setup_console.render_action(console)

        def _runner(args, timeout=10, env=None):
            return run_streamed(args, console, timeout=timeout, env=env)

        report = run_setup(
            new_user,
            run=_runner,
            on_step_start=lambda step: setup_console.render_step_start(step, console),
            on_result=lambda r: setup_console.render_step(r, console),
        )
        setup_console.render_summary(report, console)
    ctx.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
