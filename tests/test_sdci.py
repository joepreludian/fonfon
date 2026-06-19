from fonfon.system.sdci import Sdci
from tests.fakes import completed


def test_setup_invokes_sdci_server_setup():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        return completed(args, 0, "")

    Sdci(run=run).setup("100.64.0.1", "tok")
    assert seen["args"] == [
        "sdci-server",
        "setup",
        "--ip",
        "100.64.0.1",
        "--token",
        "tok",
    ]
    assert seen["timeout"] >= 60


def test_setup_raises_on_failure():
    s = Sdci(run=lambda args, timeout=10, env=None: completed(args, 1, "", "nope"))
    try:
        s.setup("ip", "tok")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "nope" in str(exc)


def test_is_configured_true_when_config_present():
    s = Sdci(
        run=lambda *a, **k: completed([], 0),
        exists=lambda path: path == "/etc/sdci/config",
    )
    assert s.is_configured() is True


def test_is_configured_false_when_absent():
    s = Sdci(run=lambda *a, **k: completed([], 0), exists=lambda path: False)
    assert s.is_configured() is False
