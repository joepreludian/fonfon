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
    "--tailscale-key",
    "tailscale_key",
    envvar="FONFON_TAILSCALE_KEY",
    default=None,
    help="Tailscale auth key to join the tailnet (or set FONFON_TAILSCALE_KEY).",
)
@click.option(
    "--traefik-cert-email",
    "traefik_cert_email",
    envvar="FONFON_TRAEFIK_CERT_EMAIL",
    default=None,
    help=(
        "Let's Encrypt email for Traefik certificates "
        "(or set FONFON_TRAEFIK_CERT_EMAIL). Provisions Traefik when set."
    ),
)
@click.option(
    "--github-user",
    "github_user",
    envvar="FONFON_GITHUB_USER",
    default=None,
    help=(
        "GitHub username whose public SSH keys seed the operator's "
        "authorized_keys (or set FONFON_GITHUB_USER). Hardens SSH when set."
    ),
)
@click.option(
    "-o",
    "--output",
    "output_format",
    type=click.Choice(["console", "json"]),
    default="console",
    help="Output format.",
)
@click.pass_context
def setup(
    ctx: click.Context,
    new_user: str,
    tailscale_key: str | None,
    traefik_cert_email: str | None,
    github_user: str | None,
    output_format: str,
) -> None:
    """Provision this server (Docker, Tailscale, pipx, sdci), join the tailnet,
    configure sdci-server, optionally deploy Traefik (--traefik-cert-email), and
    optionally harden SSH from a GitHub user's keys (--github-user)."""
    console = Console()
    if os.geteuid() != 0:
        console.print("[red]fonfon setup must be run as root.[/red]")
        ctx.exit(1)
    if not tailscale_key:
        console.print("[red]fonfon setup requires a Tailscale auth key.[/red]")
        console.print(
            "Generate one at: https://login.tailscale.com/admin/settings/keys"
        )
        console.print("Then re-run: fonfon setup <user> --tailscale-key <key>")
        ctx.exit(1)
    if output_format == "json":
        report = run_setup(new_user, tailscale_key, traefik_cert_email, github_user)
        setup_json.render(report, console)
    else:
        setup_console.render_header(console)
        setup_console.render_action(console)

        def _runner(args, timeout=10, env=None):
            return run_streamed(args, console, timeout=timeout, env=env)

        report = run_setup(
            new_user,
            tailscale_key,
            traefik_cert_email,
            github_user,
            run=_runner,
            on_step_start=lambda step: setup_console.render_step_start(step, console),
            on_result=lambda r: setup_console.render_step(r, console),
        )
        setup_console.render_summary(report, console)
    ctx.exit(0 if report.ok else 1)


if __name__ == "__main__":
    main()
