"""Command-line entrypoint for Fonfon."""

import click
from rich.console import Console

from fonfon import get_version
from fonfon.ui import build_banner


@click.group(invoke_without_command=True)
@click.version_option(version=get_version(), prog_name="Fonfon")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Fonfon — an opinionated VPS configurator."""
    if ctx.invoked_subcommand is None:
        Console().print(build_banner())


if __name__ == "__main__":
    main()
