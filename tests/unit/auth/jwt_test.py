"""Unit tests for JWT token creation and validation."""

import time

import jwt as pyjwt
import pytest
from pydantic import SecretStr

from yaai.server.auth.config import AuthConfig, JWTConfig
from yaai.server.auth.jwt import create_access_token, create_refresh_token, decode_token


@pytest.fixture
def auth_config():
    return AuthConfig(
        enabled=True,
        jwt=JWTConfig(
            secret=SecretStr("test-secret-key-for-unit-tests!!"),
            algorithm="HS256",
            access_token_expire_minutes=60,
            refresh_token_expire_days=30,
        ),
    )


def test_create_access_token_returns_valid_jwt(auth_config):
    token = create_access_token(auth_config, subject="user-123", role="owner")
    payload = pyjwt.decode(token, "test-secret-key-for-unit-tests!!", algorithms=["HS256"])
    assert payload["sub"] == "user-123"
    assert payload["role"] == "owner"
    assert payload["type"] == "access"
    assert "exp" in payload
    assert "iat" in payload
    assert "jti" in payload


def test_create_refresh_token_returns_token_and_jti(auth_config):
    token, jti = create_refresh_token(auth_config, subject="user-456", role="viewer")
    assert isinstance(jti, str)
    assert len(jti) > 0
    payload = pyjwt.decode(token, "test-secret-key-for-unit-tests!!", algorithms=["HS256"])
    assert payload["sub"] == "user-456"
    assert payload["role"] == "viewer"
    assert payload["type"] == "refresh"
    assert payload["jti"] == jti


def test_decode_token_roundtrip(auth_config):
    token = create_access_token(auth_config, subject="roundtrip", role="owner")
    payload = decode_token(auth_config, token)
    assert payload["sub"] == "roundtrip"
    assert payload["role"] == "owner"
    assert payload["type"] == "access"


def test_decode_token_invalid_secret(auth_config):
    token = create_access_token(auth_config, subject="user", role="owner")
    bad_config = AuthConfig(
        enabled=True,
        jwt=JWTConfig(secret=SecretStr("wrong-secret-that-is-long-enough!")),
    )
    with pytest.raises(pyjwt.InvalidSignatureError):
        decode_token(bad_config, token)


def test_decode_token_expired(auth_config):
    config = AuthConfig(
        enabled=True,
        jwt=JWTConfig(
            secret=SecretStr("test-secret-key-for-unit-tests!!"),
            access_token_expire_minutes=0,  # expires immediately
        ),
    )
    token = create_access_token(config, subject="user", role="owner")
    time.sleep(0.1)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        decode_token(config, token)


def test_decode_token_malformed(auth_config):
    with pytest.raises(pyjwt.DecodeError):
        decode_token(auth_config, "not-a-valid-jwt")


def test_access_and_refresh_tokens_have_different_types(auth_config):
    access = create_access_token(auth_config, subject="user", role="owner")
    refresh, _ = create_refresh_token(auth_config, subject="user", role="owner")
    access_payload = decode_token(auth_config, access)
    refresh_payload = decode_token(auth_config, refresh)
    assert access_payload["type"] == "access"
    assert refresh_payload["type"] == "refresh"


def test_each_token_has_unique_jti(auth_config):
    t1 = create_access_token(auth_config, subject="user", role="owner")
    t2 = create_access_token(auth_config, subject="user", role="owner")
    p1 = decode_token(auth_config, t1)
    p2 = decode_token(auth_config, t2)
    assert p1["jti"] != p2["jti"]
