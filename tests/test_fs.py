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


def test_write_file_writes_content_and_sets_owner_and_mode():
    written = {}
    calls = []

    def fake_write_text(path, content):
        written[path] = content

    def run(args, timeout=10, env=None):
        calls.append(args)
        return completed(args, 0, "")

    fs = Fs(run=run, write_text=fake_write_text)
    fs.write_file("/srv/traefik/traefik.yml", "api: {}\n", "deploy", "0644")

    assert written["/srv/traefik/traefik.yml"] == "api: {}\n"
    assert ["chown", "deploy:deploy", "/srv/traefik/traefik.yml"] in calls
    assert ["chmod", "0644", "/srv/traefik/traefik.yml"] in calls


def test_write_file_raises_when_chown_fails():
    def run(args, timeout=10, env=None):
        if args[0] == "chown":
            return completed(args, 1, "", "boom")
        return completed(args, 0, "")

    fs = Fs(run=run, write_text=lambda p, c: None)
    with pytest.raises(RuntimeError, match="chown"):
        fs.write_file("/x", "c", "deploy", "0644")
