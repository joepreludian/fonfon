from subprocess import CompletedProcess


def fake_runner(responses: dict[tuple[str, ...], CompletedProcess]):
    """Return a runner that maps an argv tuple to a canned CompletedProcess."""

    def _run(args, timeout=10):
        return responses[tuple(args)]

    return _run


def completed(args, returncode=0, stdout="", stderr=""):
    return CompletedProcess(args, returncode, stdout, stderr)
