"""JSON renderer for CheckReport — emits parseable JSON via rich's print_json."""

from rich.console import Console

from fonfon.models import CheckReport


def render(report: CheckReport, console: Console) -> None:
    """Emit the full CheckReport as compact JSON.

    rich emits plain (parseable) JSON when not attached to a terminal;
    this module intentionally avoids importing stdlib json to sidestep the
    module-name collision with this file's own name.
    """
    console.print_json(report.model_dump_json())
