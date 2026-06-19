from fonfon.system.tailscale import Tailscale
from tests.fakes import completed


def test_up_invokes_tailscale_up_with_auth_key():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        seen["timeout"] = timeout
        return completed(args, 0, "")

    Tailscale(run=run).up("tskey-abc")
    assert seen["args"] == ["tailscale", "up", "--auth-key", "tskey-abc"]
    assert seen["timeout"] >= 60


def test_up_raises_on_failure():
    t = Tailscale(run=lambda args, timeout=10, env=None: completed(args, 1, "", "boom"))
    try:
        t.up("k")
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "boom" in str(exc)


def test_ipv4_returns_first_address():
    t = Tailscale(
        run=lambda args, timeout=10, env=None: completed(args, 0, "100.64.0.1\n")
    )
    assert t.ipv4() == "100.64.0.1"


def test_ipv4_none_when_command_fails():
    t = Tailscale(run=lambda args, timeout=10, env=None: completed(args, 1, "", ""))
    assert t.ipv4() is None


def test_ipv4_none_when_output_empty():
    t = Tailscale(run=lambda args, timeout=10, env=None: completed(args, 0, "\n"))
    assert t.ipv4() is None
