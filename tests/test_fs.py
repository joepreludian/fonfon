import pytest

from fonfon.system.fs import Fs
from tests.fakes import completed


def test_make_dir_invokes_install_with_owner_and_mode():
    seen = {}

    def run(args, timeout=10, env=None):
        seen["args"] = args
        return completed(args, 0, "")

    Fs(run=run).make_dir("/home/u/services/sdci", "u", "0700")
    assert seen["args"] == [
        "install",
        "-d",
        "-o",
        "u",
        "-g",
        "u",
        "-m",
        "0700",
        "/home/u/services/sdci",
    ]


def test_make_dir_raises_on_failure():
    fs = Fs(run=lambda args, timeout=10, env=None: completed(args, 1, "", "boom"))
    with pytest.raises(RuntimeError, match="boom"):
        fs.make_dir("/x", "u", "0700")


def test_exists_reflects_probe():
    fs = Fs(exists=lambda path: path == "/yes")
    assert fs.exists("/yes") is True
    assert fs.exists("/no") is False
