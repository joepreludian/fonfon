from fonfon.system.pipx import Pipx
from tests.fakes import completed


def test_is_installed_true_when_listed():
    out = "sdci 1.2.3\nsomething 0.1\n"
    pipx = Pipx(run=lambda args, timeout=10, env=None: completed(args, 0, out))
    assert pipx.is_installed("sdci") is True


def test_is_installed_false_when_absent():
    pipx = Pipx(
        run=lambda args, timeout=10, env=None: completed(args, 0, "other 1.0\n")
    )
    assert pipx.is_installed("sdci") is False


def test_is_installed_false_when_pipx_missing():
    pipx = Pipx(run=lambda args, timeout=10, env=None: completed(args, 127, "", ""))
    assert pipx.is_installed("sdci") is False


def test_install_global_invokes_pipx_with_global_env():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        seen["env"] = env
        return completed(args, 0, "")

    Pipx(run=run).install_global("sdci")
    assert seen["args"][:2] == ["pipx", "install"]
    assert "sdci" in seen["args"]
    assert seen["env"]["PIPX_HOME"] == "/opt/pipx"
    assert seen["env"]["PIPX_BIN_DIR"] == "/usr/local/bin"


def test_install_global_uses_long_timeout():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["timeout"] = timeout
        return completed(args, 0, "")

    Pipx(run=run).install_global("sdci")
    assert seen["timeout"] >= 120
