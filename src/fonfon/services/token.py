"""Generate a random alphanumeric token for service configuration."""

import secrets
import string

_ALPHABET = string.ascii_letters + string.digits


def generate_token(length: int = 42) -> str:
    """Return a cryptographically-random alphanumeric token of `length` chars."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))
