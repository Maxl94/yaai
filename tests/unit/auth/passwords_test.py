"""Unit tests for password hashing utilities."""

from yaai.server.auth.passwords import hash_password, verify_password


def test_hash_password_returns_bcrypt_hash():
    hashed = hash_password("my-password")
    assert hashed.startswith("$2b$")
    assert len(hashed) == 60


def test_verify_password_correct():
    hashed = hash_password("correct-password")
    assert verify_password("correct-password", hashed) is True


def test_verify_password_incorrect():
    hashed = hash_password("correct-password")
    assert verify_password("wrong-password", hashed) is False


def test_hash_password_produces_unique_salts():
    h1 = hash_password("same-password")
    h2 = hash_password("same-password")
    assert h1 != h2  # different salts
    assert verify_password("same-password", h1) is True
    assert verify_password("same-password", h2) is True
