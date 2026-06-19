import string

from fonfon.services.token import generate_token


def test_generate_token_default_length():
    assert len(generate_token()) == 42


def test_generate_token_custom_length():
    assert len(generate_token(10)) == 10


def test_generate_token_is_alphanumeric():
    assert set(generate_token()) <= set(string.ascii_letters + string.digits)


def test_generate_token_varies_between_calls():
    assert generate_token() != generate_token()
