"""Unit tests for AuthService Google OAuth user handling."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from yaai.server.auth.config import AuthConfig, GoogleOAuthConfig, JWTConfig, OAuthConfig
from yaai.server.models.auth import UserRole
from yaai.server.services.auth_service import AuthService


def _config() -> AuthConfig:
    return AuthConfig(
        enabled=True,
        jwt=JWTConfig(secret=SecretStr("test")),
        oauth=OAuthConfig(google=GoogleOAuthConfig(enabled=True, allowed_domains=["example.com"])),
    )


def _db_returning(*users) -> AsyncMock:
    """Mock session whose successive execute() calls return the given users."""
    results = []
    for user in users:
        result = MagicMock()
        result.scalar_one_or_none.return_value = user
        results.append(result)
    db = AsyncMock()
    db.execute.side_effect = results
    return db


def _user(is_active: bool) -> MagicMock:
    user = MagicMock()
    user.is_active = is_active
    user.role = UserRole.VIEWER
    return user


class TestGetOrCreateGoogleUser:
    async def test_inactive_user_found_by_google_sub_is_rejected(self):
        db = _db_returning(_user(is_active=False))
        svc = AuthService(db, _config())

        result = await svc.get_or_create_google_user(email="a@example.com", google_sub="sub-1")

        assert result is None
        db.commit.assert_not_called()

    async def test_inactive_user_found_by_email_is_rejected(self):
        inactive = _user(is_active=False)
        db = _db_returning(None, inactive)
        svc = AuthService(db, _config())

        result = await svc.get_or_create_google_user(email="a@example.com", google_sub="sub-1")

        assert result is None
        db.commit.assert_not_called()

    async def test_active_user_found_by_google_sub_is_returned(self):
        active = _user(is_active=True)
        db = _db_returning(active)
        svc = AuthService(db, _config())

        result = await svc.get_or_create_google_user(email="a@example.com", google_sub="sub-1")

        assert result is active

    @pytest.mark.parametrize("email", ["a@evil.com", "no-at-sign"])
    async def test_disallowed_domain_is_rejected(self, email):
        db = _db_returning()
        svc = AuthService(db, _config())

        result = await svc.get_or_create_google_user(email=email, google_sub="sub-1")

        assert result is None
        db.execute.assert_not_called()
