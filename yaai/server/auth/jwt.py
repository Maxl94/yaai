"""JWT token creation and validation."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt

from yaai.server.auth.config import AuthConfig


def create_access_token(auth_config: AuthConfig, subject: str, role: str) -> str:
    """Create a short-lived access token."""
    expire = datetime.now(UTC) + timedelta(minutes=auth_config.jwt.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "role": role,
        "type": "access",
        "exp": expire,
        "iat": datetime.now(UTC),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, auth_config.jwt.secret.get_secret_value(), algorithm=auth_config.jwt.ALGORITHM)


def create_refresh_token(auth_config: AuthConfig, subject: str, role: str) -> tuple[str, str]:
    """Create a long-lived refresh token. Returns (encoded_token, jti)."""
    expire = datetime.now(UTC) + timedelta(days=auth_config.jwt.REFRESH_TOKEN_EXPIRE_DAYS)
    jti = str(uuid.uuid4())
    payload = {
        "sub": subject,
        "role": role,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.now(UTC),
        "jti": jti,
    }
    token = jwt.encode(payload, auth_config.jwt.secret.get_secret_value(), algorithm=auth_config.jwt.ALGORITHM)
    return token, jti


def decode_token(auth_config: AuthConfig, token: str) -> dict:
    """Decode and validate a JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, auth_config.jwt.secret.get_secret_value(), algorithms=[auth_config.jwt.ALGORITHM])
