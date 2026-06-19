from fonfon.system.pipx import Pipx
from tests.fakes import completed


def test_has_executable_true_when_found():
    pipx = Pipx(run=lambda args, timeout=10, env=None: completed(args, 0, "found\n"))
    assert pipx.has_executable("sdci-server") is True


def test_has_executable_false_when_not_found():
    pipx = Pipx(run=lambda args, timeout=10, env=None: completed(args, 1, "", ""))
    assert pipx.has_executable("sdci-server") is False


def test_has_executable_false_when_which_missing():
    pipx = Pipx(run=lambda args, timeout=10, env=None: completed(args, 127, "", ""))
    assert pipx.has_executable("sdci-server") is False


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
