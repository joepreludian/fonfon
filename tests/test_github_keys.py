import pytest

from fonfon.system.github_keys import GITHUB_KEYS_URL, GitHubKeys


class _FakeResp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_returns_key_lines():
    def opener(url, timeout):
        return _FakeResp(b"ssh-ed25519 AAA\nssh-rsa BBB\n")

    assert GitHubKeys(opener=opener).fetch("octocat") == [
        "ssh-ed25519 AAA",
        "ssh-rsa BBB",
    ]


def test_fetch_builds_user_keys_url():
    seen = {}

    def opener(url, timeout):
        seen["url"] = url
        return _FakeResp(b"ssh-ed25519 AAA\n")

    GitHubKeys(opener=opener).fetch("octocat")
    assert seen["url"] == GITHUB_KEYS_URL.format(username="octocat")
    assert seen["url"] == "https://github.com/octocat.keys"


def test_fetch_returns_empty_list_when_no_keys():
    def opener(url, timeout):
        return _FakeResp(b"")

    assert GitHubKeys(opener=opener).fetch("ghost") == []


def test_fetch_raises_on_network_error():
    def opener(url, timeout):
        raise OSError("404")

    with pytest.raises(RuntimeError, match="ghost"):
        GitHubKeys(opener=opener).fetch("ghost")
