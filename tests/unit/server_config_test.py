"""Unit tests for production-aware server settings helpers."""

import pytest

from yaai.server.config import api_docs_enabled, is_production, resolve_session_secret


@pytest.mark.parametrize(
    ("env", "expected"), [("production", True), ("PROD", True), ("development", False), ("", False)]
)
def test_is_production(monkeypatch, env, expected):
    monkeypatch.setenv("ENVIRONMENT", env)
    assert is_production() is expected


class TestApiDocsEnabled:
    def test_enabled_by_default_in_dev(self, monkeypatch):
        monkeypatch.delenv("ENVIRONMENT", raising=False)
        monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
        assert api_docs_enabled() is True

    def test_disabled_by_default_in_prod(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.delenv("API_DOCS_ENABLED", raising=False)
        assert api_docs_enabled() is False

    def test_explicit_true_overrides_prod_default(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("API_DOCS_ENABLED", "true")
        assert api_docs_enabled() is True

    def test_explicit_false_overrides_dev_default(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("API_DOCS_ENABLED", "false")
        assert api_docs_enabled() is False


class TestResolveSessionSecret:
    def test_returns_configured_secret(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "production")
        monkeypatch.setenv("SESSION_SECRET", "a-strong-session-secret")
        assert resolve_session_secret() == "a-strong-session-secret"

    @pytest.mark.parametrize("value", [None, "", "dev-session-secret-change-me"])
    def test_generates_ephemeral_secret_in_dev(self, monkeypatch, caplog, value):
        monkeypatch.setenv("ENVIRONMENT", "development")
        if value is None:
            monkeypatch.delenv("SESSION_SECRET", raising=False)
        else:
            monkeypatch.setenv("SESSION_SECRET", value)
        secret = resolve_session_secret()
        assert len(secret) >= 32
        assert "ephemeral" in caplog.text

    @pytest.mark.parametrize("value", [None, "", "dev-session-secret-change-me"])
    def test_raises_in_prod_when_missing_or_default(self, monkeypatch, value):
        monkeypatch.setenv("ENVIRONMENT", "production")
        if value is None:
            monkeypatch.delenv("SESSION_SECRET", raising=False)
        else:
            monkeypatch.setenv("SESSION_SECRET", value)
        with pytest.raises(RuntimeError, match="SESSION_SECRET must be set in production"):
            resolve_session_secret()
