"""Unit tests for API key hashing and Google SA token validation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import SecretStr

from yaai.server.auth.config import (
    APIKeyServiceConfig,
    AuthConfig,
    GoogleSAConfig,
    JWTConfig,
    ServiceAccountsConfig,
)
from yaai.server.auth.service_auth import (
    _token_cache,
    _token_cache_key,
    hash_api_key,
    validate_api_key,
    validate_google_sa_token,
)


class TestHashApiKey:
    def test_returns_sha256_hex(self):
        result = hash_api_key("yaam_test_key_123")
        assert len(result) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self):
        assert hash_api_key("key1") == hash_api_key("key1")

    def test_different_keys_different_hashes(self):
        assert hash_api_key("key1") != hash_api_key("key2")


class TestValidateApiKey:
    @pytest.fixture
    def config_with_api_keys_enabled(self):
        return AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("test")),
            service_accounts=ServiceAccountsConfig(
                api_keys=APIKeyServiceConfig(enabled=True),
            ),
        )

    @pytest.fixture
    def config_with_api_keys_disabled(self):
        return AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("test")),
            service_accounts=ServiceAccountsConfig(
                api_keys=APIKeyServiceConfig(enabled=False),
            ),
        )

    async def test_returns_none_when_api_keys_disabled(self, config_with_api_keys_disabled):
        db = AsyncMock()
        result = await validate_api_key(config_with_api_keys_disabled, "some-key", db)
        assert result is None

    async def test_returns_none_for_unknown_key(self, config_with_api_keys_enabled):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute.return_value = mock_result

        result = await validate_api_key(config_with_api_keys_enabled, "unknown-key", db)
        assert result is None

    async def test_returns_identity_for_valid_key(self, config_with_api_keys_enabled):
        db = AsyncMock()
        mock_api_key = MagicMock()
        mock_api_key.id = "key-id-123"
        mock_api_key.is_active = True
        mock_api_key.expires_at = None
        mock_api_key.service_account_id = "sa-id-456"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_api_key
        db.execute.return_value = mock_result

        result = await validate_api_key(config_with_api_keys_enabled, "valid-key", db)
        assert result is not None
        assert result["identity_type"] == "api_key"
        assert result["api_key_id"] == "key-id-123"
        assert result["service_account_id"] == "sa-id-456"


class TestValidateGoogleSaToken:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _token_cache.clear()
        yield
        _token_cache.clear()

    @pytest.fixture
    def config_google_enabled(self):
        return AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("test")),
            service_accounts=ServiceAccountsConfig(
                google=GoogleSAConfig(
                    enabled=True,
                    allowed_emails=["sa@project.iam.gserviceaccount.com"],
                    audience="https://yaai.example.com",
                ),
            ),
        )

    @pytest.fixture
    def config_google_disabled(self):
        return AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("test")),
            service_accounts=ServiceAccountsConfig(
                google=GoogleSAConfig(enabled=False),
            ),
        )

    async def test_returns_none_when_google_disabled(self, config_google_disabled):
        db = AsyncMock()
        result = await validate_google_sa_token(config_google_disabled, "token", db)
        assert result is None

    @patch("yaai.server.auth.service_auth.google_id_token.verify_oauth2_token")
    async def test_returns_none_on_invalid_token(self, mock_verify, config_google_enabled):
        mock_verify.side_effect = ValueError("Invalid token")
        db = AsyncMock()
        result = await validate_google_sa_token(config_google_enabled, "bad-token", db)
        assert result is None

    @patch("yaai.server.auth.service_auth.google_id_token.verify_oauth2_token")
    async def test_returns_none_when_no_email_in_claims(self, mock_verify, config_google_enabled):
        mock_verify.return_value = {"sub": "12345"}
        db = AsyncMock()
        result = await validate_google_sa_token(config_google_enabled, "token-no-email", db)
        assert result is None

    @patch("yaai.server.auth.service_auth.google_id_token.verify_oauth2_token")
    async def test_returns_none_for_email_not_in_allowed_list(self, mock_verify, config_google_enabled):
        mock_verify.return_value = {"email": "other@project.iam.gserviceaccount.com"}
        db = AsyncMock()
        result = await validate_google_sa_token(config_google_enabled, "token-wrong-email", db)
        assert result is None

    @patch("yaai.server.auth.service_auth.google_id_token.verify_oauth2_token")
    async def test_returns_none_when_sa_not_in_db(self, mock_verify, config_google_enabled):
        mock_verify.return_value = {"email": "sa@project.iam.gserviceaccount.com"}
        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = None
        db.execute.return_value = db_result
        result = await validate_google_sa_token(config_google_enabled, "token-no-sa", db)
        assert result is None

    @patch("yaai.server.auth.service_auth.google_id_token.verify_oauth2_token")
    async def test_returns_identity_for_valid_token(self, mock_verify, config_google_enabled):
        mock_verify.return_value = {"email": "sa@project.iam.gserviceaccount.com"}
        mock_sa = MagicMock()
        mock_sa.id = "sa-123"
        mock_sa.is_active = True
        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = mock_sa
        db.execute.return_value = db_result

        result = await validate_google_sa_token(config_google_enabled, "valid-google-token", db)
        assert result is not None
        assert result["identity_type"] == "google_sa"
        assert result["email"] == "sa@project.iam.gserviceaccount.com"

    @patch("yaai.server.auth.service_auth.google_id_token.verify_oauth2_token")
    async def test_verify_called_with_correct_audience(self, mock_verify, config_google_enabled):
        mock_verify.return_value = {"email": "sa@project.iam.gserviceaccount.com"}
        mock_sa = MagicMock()
        mock_sa.id = "sa-123"
        mock_sa.is_active = True
        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = mock_sa
        db.execute.return_value = db_result

        await validate_google_sa_token(config_google_enabled, "token", db)
        mock_verify.assert_called_once()
        call_args = mock_verify.call_args
        assert call_args[0][0] == "token"
        assert call_args[0][2] == "https://yaai.example.com"

    @patch("yaai.server.auth.service_auth.google_id_token.verify_oauth2_token")
    async def test_caches_valid_result_by_token_hash(self, mock_verify, config_google_enabled):
        mock_verify.return_value = {"email": "sa@project.iam.gserviceaccount.com"}
        mock_sa = MagicMock()
        mock_sa.id = "sa-123"
        mock_sa.is_active = True
        db = AsyncMock()
        db_result = MagicMock()
        db_result.scalar_one_or_none.return_value = mock_sa
        db.execute.return_value = db_result

        # First call populates cache
        await validate_google_sa_token(config_google_enabled, "cached-token", db)
        cache_key = _token_cache_key("cached-token")
        assert cache_key in _token_cache

        # Second call uses cache (verify not called again)
        mock_verify.reset_mock()
        result2 = await validate_google_sa_token(config_google_enabled, "cached-token", db)
        assert result2 is not None
        mock_verify.assert_not_called()


class TestValidateGoogleSaTokenAudience:
    @pytest.fixture(autouse=True)
    def clear_cache(self):
        _token_cache.clear()
        yield
        _token_cache.clear()

    @patch("yaai.server.auth.service_auth.google_id_token.verify_oauth2_token")
    async def test_audience_mismatch_returns_none(self, mock_verify):
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("test")),
            service_accounts=ServiceAccountsConfig(
                google=GoogleSAConfig(
                    enabled=True,
                    allowed_emails=["sa@project.iam.gserviceaccount.com"],
                    audience="expected-audience",
                ),
            ),
        )
        # verify_oauth2_token raises ValueError when audience doesn't match
        mock_verify.side_effect = ValueError("Token has wrong audience")
        db = AsyncMock()
        result = await validate_google_sa_token(config, "token", db)
        assert result is None
