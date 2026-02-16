"""Unit tests for auth dependency injection functions."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from yaai.server.auth.config import AuthConfig, JWTConfig
from yaai.server.auth.dependencies import (
    CurrentIdentity,
    _try_api_key,
    _try_google_sa,
    _try_jwt,
    check_model_read_access,
    check_model_write_access,
    get_accessible_model_ids,
    get_auth_config,
    require_auth,
    require_owner,
    resolve_model_id_from_job,
    resolve_model_id_from_version,
    set_auth_config,
)
from yaai.server.auth.jwt import create_access_token, create_refresh_token
from yaai.server.models.auth import UserRole


@pytest.fixture
def auth_config():
    config = AuthConfig(
        enabled=True,
        jwt=JWTConfig(
            secret=SecretStr("test-secret-for-dependencies-test!"),
            algorithm="HS256",
            access_token_expire_minutes=60,
        ),
    )
    set_auth_config(config)
    yield config
    set_auth_config(AuthConfig(enabled=False))


class TestCurrentIdentity:
    def test_is_owner(self):
        identity = CurrentIdentity(user_id="u1", role=UserRole.OWNER)
        assert identity.is_owner is True

    def test_is_not_owner(self):
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER)
        assert identity.is_owner is False

    def test_is_service_account_api_key(self):
        identity = CurrentIdentity(user_id=None, role=UserRole.VIEWER, identity_type="api_key")
        assert identity.is_service_account is True

    def test_is_service_account_google_sa(self):
        identity = CurrentIdentity(user_id=None, role=UserRole.VIEWER, identity_type="google_sa")
        assert identity.is_service_account is True

    def test_user_is_not_service_account(self):
        identity = CurrentIdentity(user_id="u1", role=UserRole.OWNER, identity_type="user")
        assert identity.is_service_account is False


class TestGetAuthConfig:
    def test_returns_set_config(self, auth_config):
        result = get_auth_config()
        assert result.enabled is True
        assert result.jwt.secret.get_secret_value() == "test-secret-for-dependencies-test!"

    def test_returns_default_when_not_set(self):
        set_auth_config(None)
        result = get_auth_config()
        assert isinstance(result, AuthConfig)
        # Reset
        set_auth_config(AuthConfig(enabled=False))


class TestTryJwt:
    async def test_valid_access_token(self, auth_config):
        token = create_access_token(auth_config, subject="user-1", role="owner")
        identity = await _try_jwt(auth_config, token)
        assert identity is not None
        assert identity.user_id == "user-1"
        assert identity.role == UserRole.OWNER
        assert identity.identity_type == "user"

    async def test_refresh_token_rejected(self, auth_config):
        token, _ = create_refresh_token(auth_config, subject="user-1", role="owner")
        identity = await _try_jwt(auth_config, token)
        assert identity is None

    async def test_invalid_token_returns_none(self, auth_config):
        identity = await _try_jwt(auth_config, "garbage-token")
        assert identity is None


class TestTryApiKey:
    @patch("yaai.server.auth.dependencies.validate_api_key")
    async def test_valid_api_key(self, mock_validate):
        mock_validate.return_value = {
            "identity_type": "api_key",
            "api_key_id": "key-1",
            "service_account_id": "sa-1",
        }
        config = AuthConfig(enabled=True)
        db = AsyncMock()
        identity = await _try_api_key(config, "yaam_test", db)
        assert identity is not None
        assert identity.identity_type == "api_key"
        assert identity.service_account_id == "sa-1"
        assert identity.role == UserRole.VIEWER

    @patch("yaai.server.auth.dependencies.validate_api_key")
    async def test_invalid_api_key(self, mock_validate):
        mock_validate.return_value = None
        config = AuthConfig(enabled=True)
        db = AsyncMock()
        identity = await _try_api_key(config, "bad-key", db)
        assert identity is None


class TestTryGoogleSa:
    @patch("yaai.server.auth.dependencies.validate_google_sa_token")
    async def test_valid_google_token(self, mock_validate):
        mock_validate.return_value = {
            "identity_type": "google_sa",
            "email": "sa@project.iam.gserviceaccount.com",
            "service_account_id": "sa-2",
        }
        config = AuthConfig(enabled=True)
        db = AsyncMock()
        identity = await _try_google_sa(config, "google-token", db)
        assert identity is not None
        assert identity.identity_type == "google_sa"
        assert identity.username == "sa@project.iam.gserviceaccount.com"
        assert identity.service_account_id == "sa-2"

    @patch("yaai.server.auth.dependencies.validate_google_sa_token")
    async def test_invalid_google_token(self, mock_validate):
        mock_validate.return_value = None
        config = AuthConfig(enabled=True)
        db = AsyncMock()
        identity = await _try_google_sa(config, "bad-google-token", db)
        assert identity is None


class TestRequireAuth:
    def test_returns_identity_when_provided(self, auth_config):
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER)
        result = require_auth(identity)
        assert result.user_id == "u1"

    def test_returns_anonymous_owner_when_auth_disabled(self):
        set_auth_config(AuthConfig(enabled=False))
        result = require_auth(None)
        assert result.role == UserRole.OWNER
        assert result.identity_type == "anonymous"
        set_auth_config(AuthConfig(enabled=False))

    def test_raises_401_when_auth_enabled_and_no_identity(self, auth_config):
        with pytest.raises(HTTPException) as exc_info:
            require_auth(None)
        assert exc_info.value.status_code == 401


class TestRequireOwner:
    def test_allows_owner(self, auth_config):
        identity = CurrentIdentity(user_id="u1", role=UserRole.OWNER)
        result = require_owner(identity)
        assert result.is_owner is True

    def test_rejects_viewer(self, auth_config):
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER)
        with pytest.raises(HTTPException) as exc_info:
            require_owner(identity)
        assert exc_info.value.status_code == 403

    def test_allows_any_when_auth_disabled(self):
        set_auth_config(AuthConfig(enabled=False))
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER)
        result = require_owner(identity)
        assert result is identity
        set_auth_config(AuthConfig(enabled=False))


class TestCheckModelWriteAccess:
    async def test_allows_owner(self, auth_config):
        identity = CurrentIdentity(user_id="u1", role=UserRole.OWNER)
        db = AsyncMock()
        await check_model_write_access(uuid.uuid4(), identity, db)  # no exception

    async def test_rejects_viewer(self, auth_config):
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER, identity_type="user")
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await check_model_write_access(uuid.uuid4(), identity, db)
        assert exc_info.value.status_code == 403

    async def test_sa_with_access(self, auth_config):
        sa_id = str(uuid.uuid4())
        model_id = uuid.uuid4()
        identity = CurrentIdentity(
            user_id=sa_id,
            role=UserRole.VIEWER,
            identity_type="api_key",
            service_account_id=sa_id,
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()  # access exists
        db.execute.return_value = mock_result

        await check_model_write_access(model_id, identity, db)  # no exception

    async def test_sa_without_access(self, auth_config):
        sa_id = str(uuid.uuid4())
        model_id = uuid.uuid4()
        identity = CurrentIdentity(
            user_id=sa_id,
            role=UserRole.VIEWER,
            identity_type="api_key",
            service_account_id=sa_id,
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None  # no access
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await check_model_write_access(model_id, identity, db)
        assert exc_info.value.status_code == 403

    async def test_sa_without_id_raises(self, auth_config):
        identity = CurrentIdentity(
            user_id=None,
            role=UserRole.VIEWER,
            identity_type="api_key",
            service_account_id=None,
        )
        db = AsyncMock()
        with pytest.raises(HTTPException) as exc_info:
            await check_model_write_access(uuid.uuid4(), identity, db)
        assert exc_info.value.status_code == 403

    async def test_skipped_when_auth_disabled(self):
        set_auth_config(AuthConfig(enabled=False))
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER)
        db = AsyncMock()
        await check_model_write_access(uuid.uuid4(), identity, db)
        set_auth_config(AuthConfig(enabled=False))


class TestCheckModelReadAccess:
    async def test_user_always_allowed(self, auth_config):
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER, identity_type="user")
        db = AsyncMock()
        await check_model_read_access(uuid.uuid4(), identity, db)  # no exception

    async def test_sa_with_access(self, auth_config):
        sa_id = str(uuid.uuid4())
        identity = CurrentIdentity(
            user_id=None,
            role=UserRole.VIEWER,
            identity_type="api_key",
            service_account_id=sa_id,
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = MagicMock()
        db.execute.return_value = mock_result

        await check_model_read_access(uuid.uuid4(), identity, db)

    async def test_sa_without_access(self, auth_config):
        sa_id = str(uuid.uuid4())
        identity = CurrentIdentity(
            user_id=None,
            role=UserRole.VIEWER,
            identity_type="api_key",
            service_account_id=sa_id,
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await check_model_read_access(uuid.uuid4(), identity, db)
        assert exc_info.value.status_code == 403


class TestGetAccessibleModelIds:
    async def test_returns_none_for_user(self, auth_config):
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER, identity_type="user")
        db = AsyncMock()
        result = await get_accessible_model_ids(identity, db)
        assert result is None

    async def test_returns_none_when_auth_disabled(self):
        set_auth_config(AuthConfig(enabled=False))
        identity = CurrentIdentity(user_id="u1", role=UserRole.VIEWER, identity_type="api_key")
        db = AsyncMock()
        result = await get_accessible_model_ids(identity, db)
        assert result is None
        set_auth_config(AuthConfig(enabled=False))

    async def test_returns_empty_for_sa_without_id(self, auth_config):
        identity = CurrentIdentity(
            user_id=None,
            role=UserRole.VIEWER,
            identity_type="api_key",
            service_account_id=None,
        )
        db = AsyncMock()
        result = await get_accessible_model_ids(identity, db)
        assert result == []

    async def test_returns_model_ids_for_sa(self, auth_config):
        sa_id = str(uuid.uuid4())
        model_id = uuid.uuid4()
        identity = CurrentIdentity(
            user_id=None,
            role=UserRole.VIEWER,
            identity_type="api_key",
            service_account_id=sa_id,
        )
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [model_id]
        db.execute.return_value = mock_result

        result = await get_accessible_model_ids(identity, db)
        assert result == [model_id]


class TestResolveModelIdFromVersion:
    async def test_returns_model_id(self):
        model_id = uuid.uuid4()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = model_id
        db.execute.return_value = mock_result

        result = await resolve_model_id_from_version(uuid.uuid4(), db)
        assert result == model_id

    async def test_raises_404_if_not_found(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await resolve_model_id_from_version(uuid.uuid4(), db)
        assert exc_info.value.status_code == 404


class TestResolveModelIdFromJob:
    async def test_returns_model_id(self):
        model_id = uuid.uuid4()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = model_id
        db.execute.return_value = mock_result

        result = await resolve_model_id_from_job(uuid.uuid4(), db)
        assert result == model_id

    async def test_raises_404_if_not_found(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        with pytest.raises(HTTPException) as exc_info:
            await resolve_model_id_from_job(uuid.uuid4(), db)
        assert exc_info.value.status_code == 404
