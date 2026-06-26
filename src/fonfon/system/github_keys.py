"""Boundary adapter for fetching a GitHub user's public SSH keys.

Uses stdlib urllib behind an injectable opener (mirrors probes.public_ip), so it
needs no third-party HTTP dependency and runs inside the pex.
"""

import urllib.request
from collections.abc import Callable

GITHUB_KEYS_URL = "https://github.com/{username}.keys"
GITHUB_KEYS_TIMEOUT = 10


def _urlopen(url: str, timeout: int):
    return urllib.request.urlopen(url, timeout=timeout)


class GitHubKeys:
    def __init__(self, opener: Callable = _urlopen, timeout: int = GITHUB_KEYS_TIMEOUT):
        self._opener = opener
        self._timeout = timeout

    def fetch(self, username: str) -> list[str]:
        """Return `username`'s public SSH keys (one per line); raise on failure.

        An existing user with no keys yields an empty list; a missing user (404)
        or any network error raises RuntimeError.
        """
        url = GITHUB_KEYS_URL.format(username=username)
        try:
            with self._opener(url, self._timeout) as resp:
                body = resp.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001 — surface any fetch failure uniformly
            raise RuntimeError(
                f"failed to fetch SSH keys for github user '{username}': {exc}"
            ) from exc
        return [line.strip() for line in body.splitlines() if line.strip()]
