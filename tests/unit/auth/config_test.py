"""Unit tests for auth configuration loading and validation."""

import logging

import pytest
from pydantic import SecretStr

from yaai.server.auth.config import (
    AuthConfig,
    GoogleOAuthConfig,
    GoogleSAConfig,
    JWTConfig,
    load_auth_config,
    validate_auth_config,
)


class TestLoadAuthConfig:
    def test_returns_default_config(self):
        config = load_auth_config()
        assert isinstance(config, AuthConfig)
        assert config.enabled is True
        assert config.jwt.algorithm == "HS256"

    def test_reads_from_env_vars(self, monkeypatch):
        monkeypatch.setenv("AUTH_ENABLED", "false")
        monkeypatch.setenv("AUTH_JWT_SECRET", "my-secret")
        monkeypatch.setenv("AUTH_JWT_ALGORITHM", "HS512")
        monkeypatch.setenv("AUTH_JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
        config = load_auth_config()
        assert config.enabled is False
        assert config.jwt.secret.get_secret_value() == "my-secret"
        assert config.jwt.algorithm == "HS512"
        assert config.jwt.access_token_expire_minutes == 30

    def test_reads_nested_oauth_from_env(self, monkeypatch):
        monkeypatch.setenv("AUTH_OAUTH_GOOGLE_ENABLED", "true")
        monkeypatch.setenv("AUTH_OAUTH_GOOGLE_CLIENT_ID", "test-client-id")
        config = load_auth_config()
        assert config.oauth.google.enabled is True
        assert config.oauth.google.client_id.get_secret_value() == "test-client-id"

    def test_reads_service_accounts_from_env(self, monkeypatch):
        monkeypatch.setenv("AUTH_SERVICE_ACCOUNTS_GOOGLE_ENABLED", "true")
        monkeypatch.setenv("AUTH_SERVICE_ACCOUNTS_GOOGLE_AUDIENCE", "https://example.com")
        config = load_auth_config()
        assert config.service_accounts.google.enabled is True
        assert config.service_accounts.google.audience == "https://example.com"


class TestCommaSeparatedLists:
    def test_oauth_allowed_domains_from_json_env(self, monkeypatch):
        monkeypatch.setenv("AUTH_OAUTH_GOOGLE_ALLOWED_DOMAINS", '["example.com","foo.com"]')
        config = load_auth_config()
        assert config.oauth.google.allowed_domains == ["example.com", "foo.com"]

    def test_oauth_owner_emails_from_json_env(self, monkeypatch):
        monkeypatch.setenv("AUTH_OAUTH_GOOGLE_OWNER_EMAILS", '["a@x.com", "b@x.com"]')
        config = load_auth_config()
        assert config.oauth.google.owner_emails == ["a@x.com", "b@x.com"]

    def test_sa_allowed_emails_from_json_env(self, monkeypatch):
        monkeypatch.setenv(
            "AUTH_SERVICE_ACCOUNTS_GOOGLE_ALLOWED_EMAILS",
            '["sa@proj.iam.gserviceaccount.com"]',
        )
        config = load_auth_config()
        assert config.service_accounts.google.allowed_emails == ["sa@proj.iam.gserviceaccount.com"]

    def test_list_passed_directly(self):
        cfg = GoogleOAuthConfig(allowed_domains=["a.com", "b.com"])
        assert cfg.allowed_domains == ["a.com", "b.com"]

    def test_comma_separated_string_passed_directly(self):
        cfg = GoogleOAuthConfig(allowed_domains="a.com,b.com")
        assert cfg.allowed_domains == ["a.com", "b.com"]

    def test_sa_list_passed_directly(self):
        cfg = GoogleSAConfig(allowed_emails=["sa@example.com"])
        assert cfg.allowed_emails == ["sa@example.com"]

    def test_sa_comma_separated_passed_directly(self):
        cfg = GoogleSAConfig(allowed_emails="sa@example.com,other@example.com")
        assert cfg.allowed_emails == ["sa@example.com", "other@example.com"]


class TestGoogleOAuthConfig:
    def test_resolve_role_owner(self):
        cfg = GoogleOAuthConfig(
            enabled=True,
            owner_emails=["admin@example.com"],
            viewer_emails=["user@example.com"],
        )
        assert cfg.resolve_role("admin@example.com") == "owner"

    def test_resolve_role_viewer(self):
        cfg = GoogleOAuthConfig(
            enabled=True,
            owner_emails=["admin@example.com"],
            viewer_emails=["user@example.com"],
        )
        assert cfg.resolve_role("user@example.com") == "viewer"

    def test_resolve_role_not_listed(self):
        cfg = GoogleOAuthConfig(
            enabled=True,
            owner_emails=["admin@example.com"],
            viewer_emails=["user@example.com"],
        )
        assert cfg.resolve_role("unknown@example.com") is None

    def test_resolve_role_case_insensitive(self):
        cfg = GoogleOAuthConfig(
            enabled=True,
            owner_emails=["Admin@Example.Com"],
            viewer_emails=[],
        )
        assert cfg.resolve_role("admin@example.com") == "owner"


class TestValidateAuthConfig:
    def test_disabled_auth_logs_info(self, caplog):
        config = AuthConfig(enabled=False)
        with caplog.at_level(logging.INFO):
            result = validate_auth_config(config)
        assert result.enabled is False
        assert "DISABLED" in caplog.text

    def test_google_oauth_disables_local(self, caplog):
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("a-real-secret-value-here")),
        )
        config.oauth.google.enabled = True
        config.oauth.google.allowed_domains = ["example.com"]
        config.oauth.google.owner_emails = ["admin@example.com"]
        config.local.enabled = True

        with caplog.at_level(logging.INFO):
            result = validate_auth_config(config)
        assert result.local.enabled is False
        assert "auto-disabled" in caplog.text

    def test_empty_jwt_secret_generates_ephemeral(self, caplog, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("")),
        )
        with caplog.at_level(logging.WARNING):
            result = validate_auth_config(config)
        assert result.jwt.secret.get_secret_value() != ""
        assert "ephemeral" in caplog.text

    def test_insecure_jwt_secret_warns_in_dev(self, caplog, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("changeme")),
        )
        with caplog.at_level(logging.WARNING):
            validate_auth_config(config)
        assert "insecure" in caplog.text.lower()

    def test_insecure_jwt_secret_raises_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("changeme")),
        )
        with pytest.raises(RuntimeError, match="JWT secret is insecure"):
            validate_auth_config(config)

    def test_google_oauth_no_domains_raises_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("a-strong-production-secret-1234")),
        )
        config.oauth.google.enabled = True
        config.oauth.google.allowed_domains = []
        with pytest.raises(RuntimeError, match="allowed_domains"):
            validate_auth_config(config)

    def test_google_sa_no_audience_warns_in_dev(self, caplog, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("a-real-secret-value-here")),
        )
        config.service_accounts.google.enabled = True
        config.service_accounts.google.audience = ""
        with caplog.at_level(logging.WARNING):
            validate_auth_config(config)
        assert "audience" in caplog.text.lower()

    def test_google_sa_no_audience_raises_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("a-strong-production-secret-1234")),
        )
        config.service_accounts.google.enabled = True
        config.service_accounts.google.audience = ""
        with pytest.raises(RuntimeError, match="audience"):
            validate_auth_config(config)

    def test_google_sa_with_audience_passes(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        config = AuthConfig(
            enabled=True,
            jwt=JWTConfig(secret=SecretStr("a-strong-production-secret-1234")),
        )
        config.service_accounts.google.enabled = True
        config.service_accounts.google.audience = "https://yaai.example.com"
        config.service_accounts.google.allowed_emails = ["sa@project.iam.gserviceaccount.com"]
        # Should not raise
        validate_auth_config(config)
